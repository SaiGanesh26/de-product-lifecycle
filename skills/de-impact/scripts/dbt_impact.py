#!/usr/bin/env python3
"""dbt_impact: downstream consumers of a dbt model or column, from target/manifest.json.

Walks `child_map` transitively from the model, reports every downstream node with its
depth, resource type, and materialization, and for --column keeps only nodes whose raw or
compiled SQL mentions the column as a whole word. Exposures that depend on the model (or on
any downstream model) are listed separately: they are the BI dashboards, exports, and apps
the manifest knows about. --grep-paths extends the search to directories outside dbt
(a BI repo, an exports folder) for the column or model name.

Stdlib only. Run with `python3 -I`.
"""
import argparse, json, os, re, sys
from pathlib import Path


def load_manifest(path):
    p = Path(path)
    if not p.is_file():
        sys.exit(f"manifest not found at {p}. Run `dbt parse` (or `dbt compile`) in the dbt project "
                 f"and point --manifest at its target/manifest.json.")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"manifest at {p} is not valid JSON: {e}")


def find_model_id(manifest, name):
    hits = [uid for uid, n in manifest.get("nodes", {}).items()
            if n.get("name") == name and n.get("resource_type") in ("model", "snapshot", "seed", "source")]
    hits += [uid for uid, n in manifest.get("sources", {}).items() if n.get("name") == name]
    if not hits:
        sys.exit(f"no model/snapshot/seed/source named {name!r} in manifest")
    if len(hits) > 1:
        print(f"note: {len(hits)} nodes named {name!r}; using {hits[0]}", file=sys.stderr)
    return hits[0]


def node_info(manifest, uid):
    n = manifest.get("nodes", {}).get(uid) or manifest.get("exposures", {}).get(uid) or \
        manifest.get("sources", {}).get(uid) or manifest.get("metrics", {}).get(uid) or {}
    cfg = n.get("config", {}) or {}
    return {
        "unique_id": uid,
        "name": n.get("name", uid.split(".")[-1]),
        "resource_type": n.get("resource_type", uid.split(".")[0]),
        "materialized": cfg.get("materialized", ""),
        "path": n.get("original_file_path", ""),
        "owner": ((n.get("owner") or {}).get("name") if isinstance(n.get("owner"), dict) else n.get("owner")) or
                 (n.get("meta") or {}).get("owner") or cfg.get("meta", {}).get("owner") or "",
        "sql": " ".join(filter(None, [n.get("raw_code", n.get("raw_sql", "")), n.get("compiled_code", n.get("compiled_sql", ""))])),
        "exposure_type": n.get("type", "") if n.get("resource_type") == "exposure" else "",
        "url": n.get("url", "") if n.get("resource_type") == "exposure" else "",
    }


def downstream(manifest, root):
    child_map = manifest.get("child_map", {})
    seen, order, frontier, depth = {root}, [], [root], 0
    while frontier:
        depth += 1
        nxt = []
        for uid in frontier:
            for child in child_map.get(uid, []):
                if child not in seen:
                    seen.add(child); order.append((child, depth)); nxt.append(child)
        frontier = nxt
    return order


def mentions(sql, column):
    return bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(column) + r"(?![A-Za-z0-9_])", sql, re.I))


def grep_paths(paths, needle, exts=(".sql", ".py", ".yml", ".yaml", ".json", ".lkml", ".lookml", ".tml", ".tds", ".twb", ".md", ".js", ".ts")):
    pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(needle) + r"(?![A-Za-z0-9_])", re.I)
    hits = []
    for base in paths:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "target", "dbt_packages", "__pycache__")]
            for f in files:
                if not f.lower().endswith(exts):
                    continue
                fp = Path(root) / f
                try:
                    for i, line in enumerate(fp.read_text(errors="ignore").splitlines(), 1):
                        if pat.search(line):
                            hits.append({"file": str(fp), "line": i, "text": line.strip()[:120]})
                            if len([h for h in hits if h["file"] == str(fp)]) >= 3:
                                break
                except OSError:
                    continue
    return hits


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", default="./target/manifest.json")
    p.add_argument("--model", help="model, snapshot, seed, or source name to start from")
    p.add_argument("--column", help="column name; keeps only downstream nodes whose SQL mentions it")
    p.add_argument("--grep-paths", nargs="*", default=[], help="extra directories to search for the column (or model) name")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if not a.model:
        sys.exit("--model is required (the --column filter applies to what is downstream of it)")

    m = load_manifest(a.manifest)
    root = find_model_id(m, a.model)
    rows, exposures = [], []
    for uid, depth in downstream(m, root):
        info = node_info(m, uid)
        if a.column and info["resource_type"] not in ("exposure",) and not mentions(info["sql"], a.column):
            continue
        info["depth"] = depth
        (exposures if info["resource_type"] == "exposure" else rows).append(info)
    # exposures reachable only via depends_on (older manifests may not put them in child_map)
    known = {e["unique_id"] for e in exposures}
    reach = {root} | {uid for uid, _ in downstream(m, root)}
    for uid, e in m.get("exposures", {}).items():
        if uid not in known and set((e.get("depends_on") or {}).get("nodes", [])) & reach:
            info = node_info(m, uid); info["depth"] = "-"; exposures.append(info)
    needle = a.column or a.model
    ext = grep_paths(a.grep_paths, needle) if a.grep_paths else []

    if a.json:
        strip = lambda d: {k: v for k, v in d.items() if k != "sql"}
        print(json.dumps({"root": root, "column": a.column, "downstream": [strip(r) for r in rows],
                          "exposures": [strip(e) for e in exposures], "external_hits": ext}, indent=1))
        return

    print(f"root: {root}" + (f"   column filter: {a.column}" if a.column else ""))
    print(f"\nDownstream nodes ({len(rows)}):")
    if rows:
        print(f"  {'depth':5} {'type':9} {'materialized':13} {'name':40} {'owner':12} path")
        for r in rows:
            print(f"  {r['depth']:<5} {r['resource_type']:9} {r['materialized']:13} {r['name']:40} {r['owner']:12} {r['path']}")
    else:
        print("  none" + (" mention this column" if a.column else ""))
    print(f"\nExposures (BI, exports, apps the manifest knows about) ({len(exposures)}):")
    if exposures:
        for e in exposures:
            print(f"  {e['exposure_type'] or 'exposure':10} {e['name']:30} owner={e['owner'] or '?':14} {e['url']}")
    else:
        print("  none declared. If dashboards read these tables, they are not in the manifest; use --grep-paths or ask the BI owner.")
    if a.grep_paths:
        print(f"\nExternal mentions of {needle!r} under {', '.join(a.grep_paths)} ({len(ext)}):")
        for h in ext[:40]:
            print(f"  {h['file']}:{h['line']}  {h['text']}")
        if len(ext) > 40:
            print(f"  ... {len(ext) - 40} more (use --json)")


if __name__ == "__main__":
    main()
