#!/usr/bin/env python3
"""Summarize failures in a dbt run_results.json and print the selector to rerun just those.

Reads only results[].status, unique_id, message, and timing, which have been stable across
dbt versions. Exit code 1 if any node failed or errored, 0 otherwise, 2 if the file is missing.
"""
import argparse, json, sys
from pathlib import Path

BAD = {"fail", "error", "runtime error", "warn"}


def node_name(uid):
    # unique_id looks like model.project.name or test.project.name.hash
    parts = uid.split(".")
    return parts[2] if len(parts) >= 3 else uid


def timing_seconds(r):
    if isinstance(r.get("execution_time"), (int, float)):
        return round(r["execution_time"], 1)
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", nargs="?", default="target/run_results.json", help="path to run_results.json (default: target/run_results.json)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--include-warn", action="store_true", help="also list warn-status tests")
    a = p.parse_args()

    f = Path(a.path)
    if not f.is_file():
        sys.exit(f"run_results.json not found at {f}. Run dbt first, or pass the path (dbt writes it under the project's target/ directory).")
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{f} is not valid JSON: {e}")

    results = data.get("results", [])
    bad_statuses = BAD if a.include_warn else BAD - {"warn"}
    bad = []
    for r in results:
        st = str(r.get("status", "")).lower()
        if st in bad_statuses:
            msg = (r.get("message") or "").strip().splitlines()
            bad.append({
                "unique_id": r.get("unique_id", "?"),
                "name": node_name(r.get("unique_id", "?")),
                "resource_type": r.get("unique_id", "").split(".")[0] or "?",
                "status": st,
                "message": msg[0] if msg else "",
                "seconds": timing_seconds(r),
            })

    total = len(results)
    gen = (data.get("metadata") or {}).get("generated_at", "")
    elapsed = data.get("elapsed_time")
    selector = " ".join(sorted({b["name"] for b in bad}))

    if a.json:
        print(json.dumps({"generated_at": gen, "total_nodes": total, "bad_nodes": bad,
                          "rerun": f"dbt build --select {selector}" if selector else None}, indent=1))
    else:
        head = f"{total} nodes" + (f", {elapsed:.0f}s" if isinstance(elapsed, (int, float)) else "") + (f", generated {gen}" if gen else "")
        print(head)
        if not bad:
            print("No failed or errored nodes.")
        else:
            print(f"{len(bad)} failed/errored:")
            for b in bad:
                t = f"{b['seconds']}s" if b["seconds"] is not None else "-"
                print(f"  {b['status']:<6} {b['resource_type']:<5} {b['name']:<40} {t:>7}  {b['message'][:120]}")
            print(f"\nrerun just these:\n  dbt build --select {selector}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
