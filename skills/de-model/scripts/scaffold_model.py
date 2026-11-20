#!/usr/bin/env python3
"""Scaffold a dbt model (.sql + .yml) from a one-line spec.

The point is not to save typing. It is to force the three decisions that cause most
data bugs to be made explicitly, up front, and encoded as tests: the grain, the
materialization (and its incremental lookback), and which columns can never be null.

Example:
  scaffold_model.py fct_orders --grain order_id --measures gross_amount,net_amount \
      --source "{{ ref('stg_shop__orders') }}" --materialized incremental \
      --partition order_date --description "One row per order" --out models/marts/
"""
import argparse
import sys
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"


def csv(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def build_config(args, grain):
    lines = [f"        materialized='{args.materialized}'"]
    if args.materialized == "incremental":
        uk = args.unique_key or (grain[0] if len(grain) == 1 else "[" + ", ".join(f"'{g}'" for g in grain) + "]")
        if not uk.startswith("["):
            uk = f"'{uk}'"
        lines.append(f"        unique_key={uk}")
        lines.append("        on_schema_change='append_new_columns'")
    if args.partition:
        lines.append(f"        partition_by={{'field': '{args.partition}', 'data_type': 'date'}}")
    return ",\n".join(lines)


def build_incremental_filter(args):
    if args.materialized != "incremental":
        return ""
    col = args.partition or "updated_at"
    return (
        "\n    {% if is_incremental() %}\n"
        f"    -- Lookback covers late-arriving rows. {args.lookback_days} days is a guess:\n"
        "    -- check the source's actual landing lag before trusting it.\n"
        f"    where {col} >= (select dateadd(day, -{args.lookback_days}, max({col})) from {{{{ this }}}})\n"
        "    {% endif %}\n"
    )


def build_select(grain, measures, partition):
    cols = list(grain)
    if partition and partition not in cols:
        cols.append(partition)
    cols += [m for m in measures if m not in cols]
    return ",\n".join(f"        {c}" for c in cols) if cols else "        *"


def build_columns(grain, measures, partition):
    out = []
    for g in grain:
        tests = ["not_null"] + (["unique"] if len(grain) == 1 else [])
        out.append(f"      - name: {g}\n        description: \"Grain key.\"\n        data_tests:\n"
                   + "".join(f"          - {t}\n" for t in tests))
    if partition and partition not in grain:
        out.append(f"      - name: {partition}\n        description: \"Partition column.\"\n        data_tests:\n          - not_null\n")
    for m in measures:
        out.append(f"      - name: {m}\n        description: \"Measure. State the unit and whether nulls are meaningful.\"\n"
                   "        data_tests:\n          - not_null\n")
    return "".join(out).rstrip("\n")


def build_model_tests(grain):
    if len(grain) <= 1:
        return ""
    cols = "\n".join(f"            - {g}" for g in grain)
    return ("    data_tests:\n"
            "      - dbt_utils.unique_combination_of_columns:\n"
            "          combination_of_columns:\n"
            f"{cols}")


def write(path, content, force):
    if path.exists() and not force:
        sys.exit(f"refusing to overwrite {path} (pass --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"wrote {path}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", help="model name, e.g. fct_orders")
    p.add_argument("--grain", required=True, help="comma-separated grain key column(s)")
    p.add_argument("--measures", default="", help="comma-separated measure columns")
    p.add_argument("--source", required=True, help="source ref, e.g. \"{{ ref('stg_orders') }}\" or \"{{ source('shop','orders') }}\"")
    p.add_argument("--materialized", default="view", choices=["view", "table", "incremental", "ephemeral"])
    p.add_argument("--unique-key", dest="unique_key", default="", help="override unique_key for incremental (defaults to the grain)")
    p.add_argument("--partition", default="", help="partition / cluster date column")
    p.add_argument("--lookback-days", dest="lookback_days", type=int, default=3)
    p.add_argument("--description", default="TODO: what one row means and who consumes it.")
    p.add_argument("--out", default=".", help="output directory")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    args = p.parse_args()

    grain, measures = csv(args.grain), csv(args.measures)
    if not grain:
        sys.exit("--grain must name at least one column; a model without a declared grain cannot be tested")
    grain_human = " + ".join(grain)

    sql = Template((TEMPLATES / "model.sql.tmpl").read_text()).substitute(
        name=args.name, grain_human=grain_human, description=args.description,
        source_ref=args.source, config_lines=build_config(args, grain),
        incremental_filter=build_incremental_filter(args),
        select_lines=build_select(grain, measures, args.partition),
    )
    yml = Template((TEMPLATES / "schema.yml.tmpl").read_text()).substitute(
        name=args.name, description=args.description, grain_human=grain_human,
        model_tests=build_model_tests(grain),
        column_lines=build_columns(grain, measures, args.partition),
    )
    yml = "\n".join(line for line in yml.splitlines() if line.strip() != "") + "\n"

    out = Path(args.out)
    write(out / f"{args.name}.sql", sql, args.force)
    write(out / f"{args.name}.yml", yml, args.force)
    print(f"\nnext: dbt parse && dbt run --select {args.name} && dbt test --select {args.name}")


if __name__ == "__main__":
    main()
