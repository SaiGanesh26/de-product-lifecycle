#!/usr/bin/env python3
"""reconcile: before/after verification of a changed table or model.

Three steps, each usable alone:

  sql      generate one reconciliation query for your warehouse dialect. It returns rows of
           (side, metric, value) for both relations: row_count, distinct_keys, dup_rows,
           null_<key>, sum_/min_/max_<measure>, min_/max_<date>, and (optionally) anti-join
           counts of keys present on one side only. Run it with your own client.
  run      generate and execute directly for sqlite (stdlib) or duckdb (if installed).
  compare  read the (side, metric, value) results (CSV or JSON) and print a diff table with
           flags. Exit code 1 when a flag fires, so it can gate a PR.

The query is deliberately plain SQL (no window functions, no dialect-specific aggregates) so
it runs the same everywhere. Every value is cast to a string column so one result shape fits
all engines; `compare` parses numbers back.
"""
import argparse, csv, io, json, sqlite3, sys
from pathlib import Path

STR_TYPE = {"bigquery": "STRING", "snowflake": "VARCHAR", "postgres": "TEXT", "redshift": "VARCHAR",
            "duckdb": "VARCHAR", "spark": "STRING", "databricks": "STRING", "sqlite": "TEXT", "trino": "VARCHAR"}


def rel(r):
    """Accept a table name or a parenthesised subquery."""
    r = r.strip()
    return r if r.startswith("(") else r


def side_sql(side, relation, keys, measures, date_col, dialect, where):
    S = STR_TYPE[dialect]
    w = f" WHERE {where}" if where else ""
    src = f"{rel(relation)} src{w}" if not relation.strip().startswith("(") else f"{relation} src{w}"
    def m(name, expr):
        return f"SELECT '{side}' AS side, '{name}' AS metric, CAST({expr} AS {S}) AS value FROM {src}"
    parts = [m("row_count", "COUNT(*)")]
    if keys:
        klist = ", ".join(keys)
        parts.append(f"SELECT '{side}', 'distinct_keys', CAST(COUNT(*) AS {S}) FROM (SELECT DISTINCT {klist} FROM {src}) dk")
        for k in keys:
            parts.append(m(f"null_{k}", f"SUM(CASE WHEN {k} IS NULL THEN 1 ELSE 0 END)"))
    for c in measures:
        parts.append(m(f"sum_{c}", f"SUM({c})"))
        parts.append(m(f"min_{c}", f"MIN({c})"))
        parts.append(m(f"max_{c}", f"MAX({c})"))
        parts.append(m(f"null_{c}", f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)"))
    if date_col:
        parts.append(m(f"min_{date_col}", f"MIN({date_col})"))
        parts.append(m(f"max_{date_col}", f"MAX({date_col})"))
        parts.append(m(f"null_{date_col}", f"SUM(CASE WHEN {date_col} IS NULL THEN 1 ELSE 0 END)"))
    return parts


def anti_sql(a, b, keys, dialect, where):
    S = STR_TYPE[dialect]
    on = " AND ".join(f"x.{k} = y.{k}" for k in keys)
    k0 = keys[0]
    def one(side, left, right):
        wl = f" WHERE {where}" if where else ""
        lq = f"(SELECT DISTINCT {', '.join(keys)} FROM {left} l{wl}) x"
        rq = f"(SELECT DISTINCT {', '.join(keys)} FROM {right} r{wl}) y"
        return (f"SELECT '{side}' AS side, 'keys_only_here' AS metric, CAST(COUNT(*) AS {S}) AS value "
                f"FROM {lq} LEFT JOIN {rq} ON {on} WHERE y.{k0} IS NULL")
    return [one("a", a, b), one("b", b, a)]


def build_sql(a, b, keys, measures, date_col, dialect, where, anti):
    parts = side_sql("a", a, keys, measures, date_col, dialect, where) + side_sql("b", b, keys, measures, date_col, dialect, where)
    if anti and keys:
        parts += anti_sql(a, b, keys, dialect, where)
    return "\nUNION ALL\n".join(parts) + "\nORDER BY 2, 1"


def parse_results(paths):
    rows = []
    for p in paths:
        text = Path(p).read_text()
        if text.lstrip().startswith("[") or text.lstrip().startswith("{"):
            data = json.loads(text)
            data = data if isinstance(data, list) else data.get("rows") or data.get("data") or []
            for r in data:
                rows.append((str(r["side"]).strip().lower(), str(r["metric"]).strip(), r.get("value")))
        else:
            rdr = csv.DictReader(io.StringIO(text))
            cols = {c.lower().strip(): c for c in (rdr.fieldnames or [])}
            if not {"side", "metric", "value"} <= set(cols):
                sys.exit(f"{p}: need columns side, metric, value (got {rdr.fieldnames})")
            for r in rdr:
                rows.append((r[cols["side"]].strip().lower(), r[cols["metric"]].strip(), r[cols["value"]]))
    return rows


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(rows, tolerance, expect_equal):
    a = {m: v for s, m, v in rows if s == "a"}
    b = {m: v for s, m, v in rows if s == "b"}
    metrics = sorted(set(a) | set(b), key=lambda m: (m != "row_count", m != "distinct_keys", m))
    flags, out = [], []
    ra, rb = num(a.get("row_count")), num(b.get("row_count"))
    da, db = num(a.get("distinct_keys")), num(b.get("distinct_keys"))
    if ra is not None and da is not None and ra - da > 0:
        flags.append(f"before: {int(ra - da)} duplicate rows at the stated grain")
    if rb is not None and db is not None and rb - db > 0:
        flags.append(f"after: {int(rb - db)} duplicate rows at the stated grain")
    for m in metrics:
        va, vb = a.get(m), b.get(m)
        na, nb = num(va), num(vb)
        if na is not None and nb is not None:
            diff = nb - na
            pct = (diff / na * 100) if na else (0.0 if diff == 0 else float("inf"))
            flag = ""
            if m in expect_equal and diff != 0:
                flag = "EXPECTED EQUAL"
            elif m.startswith(("row_count", "distinct_keys", "sum_")) and na and abs(pct) > tolerance:
                flag = f"> {tolerance}%"
            elif m.startswith("null_") and diff > 0:
                flag = "more nulls"
            elif m == "keys_only_here" and (na or nb):
                flag = "key sets differ"
            if flag:
                flags.append(f"{m}: {va} -> {vb} ({pct:+.2f}%) {flag}")
            out.append((m, va, vb, f"{diff:+g}", f"{pct:+.2f}%", flag))
        else:
            flag = "changed" if (va or "") != (vb or "") and m not in ("keys_only_here",) else ""
            if flag and m in expect_equal:
                flags.append(f"{m}: {va} -> {vb} EXPECTED EQUAL")
            out.append((m, va, vb, "", "", flag))
    return out, flags


def print_table(out):
    w = [max(len(str(r[i])) for r in out + [("metric", "before (a)", "after (b)", "diff", "pct", "flag")]) for i in range(6)]
    hdr = ("metric", "before (a)", "after (b)", "diff", "pct", "flag")
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    print("  ".join("-" * w[i] for i in range(6)))
    for r in out:
        print("  ".join(str(c if c is not None else "").ljust(w[i]) for i, c in enumerate(r)))


def common_args(s):
    s.add_argument("--a", required=True, help="BEFORE relation: table name or (subquery)")
    s.add_argument("--b", required=True, help="AFTER relation: table name or (subquery)")
    s.add_argument("--keys", default="", help="comma list of grain key columns")
    s.add_argument("--measures", default="", help="comma list of numeric columns to sum/min/max")
    s.add_argument("--date-col", default="", help="date/timestamp column for bounds")
    s.add_argument("--where", default="", help="filter applied to both sides, e.g. \"dt >= '2026-11-01'\"")
    s.add_argument("--anti-join", action="store_true", help="also count keys present on one side only")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sql", help="print the reconciliation query"); common_args(s)
    s.add_argument("--dialect", default="bigquery", choices=sorted(STR_TYPE))
    s = sub.add_parser("run", help="generate and execute on sqlite/duckdb, print CSV"); common_args(s)
    s.add_argument("--engine", choices=["sqlite", "duckdb"], required=True); s.add_argument("--db", required=True)
    s = sub.add_parser("compare", help="diff (side,metric,value) results; exit 1 on flags")
    s.add_argument("files", nargs="+", help="CSV or JSON result files (one with both sides, or one per side)")
    s.add_argument("--tolerance", type=float, default=0.0, help="allowed %% change for counts and sums")
    s.add_argument("--expect-equal", default="", help="comma list of metrics that must not change")
    a = p.parse_args()

    if a.cmd in ("sql", "run"):
        keys = [k.strip() for k in a.keys.split(",") if k.strip()]
        meas = [m.strip() for m in a.measures.split(",") if m.strip()]
        dialect = a.dialect if a.cmd == "sql" else a.engine
        q = build_sql(a.a, a.b, keys, meas, a.date_col, dialect, a.where, a.anti_join)
        if a.cmd == "sql":
            print(q + ";"); return
        if a.engine == "sqlite":
            con = sqlite3.connect(a.db); rows = con.execute(q).fetchall()
        else:
            try:
                import duckdb  # noqa
            except ImportError:
                sys.exit("duckdb is not installed in this python; use `sql` and your own client")
            rows = duckdb.connect(a.db).execute(q).fetchall()
        w = csv.writer(sys.stdout); w.writerow(["side", "metric", "value"]); w.writerows(rows); return

    rows = parse_results(a.files)
    if not rows:
        sys.exit("no rows parsed")
    out, flags = compare(rows, a.tolerance, [m for m in a.expect_equal.split(",") if m])
    print_table(out)
    if flags:
        print("\nFLAGS:"); [print(f"  - {f}") for f in flags]; sys.exit(1)
    print("\nNo flags. Differences, if any, are within tolerance.")


if __name__ == "__main__":
    main()
