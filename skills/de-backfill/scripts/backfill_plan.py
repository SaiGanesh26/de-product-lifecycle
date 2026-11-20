#!/usr/bin/env python3
"""Generate a markdown backfill plan: ordered date batches, rendered commands, a per-batch
checklist, and a rollback section. Never executes anything.

Example:
  python3 -I backfill_plan.py --start 2026-10-01 --end 2026-11-01 --chunk 1 \
      --cmd "dbt run --select fct_orders --vars '{start_date: \"{start}\", end_date: \"{end}\"}'" \
      --out plan.md

Placeholders in --cmd: {start} {end} (dates, half-open window: >= start, < end),
{start_iso} {end_iso} (midnight timestamps), {n} (batch number).
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_DAYS_WITHOUT_FLAG = 3 * 365


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not a YYYY-MM-DD date")


def batches(start, end, chunk, order):
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk), end)
        out.append((cur, nxt))
        cur = nxt
    if order == "newest-first":
        out.reverse()
    return out


def render(cmd, n, s, e):
    # Only our placeholders are substituted; braces that are not ours (e.g. dbt --vars) are kept.
    return (cmd.replace("{start}", s.isoformat()).replace("{end}", e.isoformat())
               .replace("{start_iso}", f"{s.isoformat()}T00:00:00").replace("{end_iso}", f"{e.isoformat()}T00:00:00")
               .replace("{n}", str(n)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=parse_date, required=True, help="first day to backfill (inclusive)")
    p.add_argument("--end", type=parse_date, required=True, help="day after the last day to backfill (exclusive)")
    p.add_argument("--chunk", type=int, default=1, help="days per batch (default 1)")
    p.add_argument("--cmd", required=True, help="command template with {start} {end} placeholders")
    p.add_argument("--order", choices=["newest-first", "oldest-first"], default="newest-first")
    p.add_argument("--max-parallel", type=int, default=1, help="batches allowed to run at once (default 1)")
    p.add_argument("--target", default="<table or model>", help="name of the table/model, for the header")
    p.add_argument("--out", type=Path, default=Path("backfill-plan.md"))
    p.add_argument("--i-know", action="store_true", help="allow ranges longer than 3 years")
    a = p.parse_args()

    if a.end <= a.start:
        sys.exit("--end must be after --start (the window is half-open: >= start, < end)")
    if a.chunk < 1 or a.max_parallel < 1:
        sys.exit("--chunk and --max-parallel must be at least 1")
    span = (a.end - a.start).days
    if span > MAX_DAYS_WITHOUT_FLAG and not a.i_know:
        sys.exit(f"range is {span} days (> 3 years). A rebuild into a shadow table plus swap is usually the "
                 f"right tool. Pass --i-know to generate the plan anyway.")
    if "{start}" not in a.cmd and "{start_iso}" not in a.cmd:
        sys.exit("--cmd must contain {start} (or {start_iso}); a command without the window is not a backfill")

    bs = batches(a.start, a.end, a.chunk, a.order)
    today = date.today().isoformat()
    L = []
    L += [f"# Backfill plan: {a.target}", "",
          f"Generated {today} by backfill_plan.py. **Nothing below has run.** Fill the header, get it",
          "approved by the table owner, then work the checklist in order.", "",
          "## Header (answer before batch 1)", "",
          "| Question | Answer |", "|---|---|",
          f"| Target and partition column | {a.target} / `<partition column>` |",
          f"| Bounds (half-open) and evidence | `{a.start}` to `{a.end}` ({span} days). Evidence: `<commit / query>` |",
          "| Source landing lag | `<hours or days>`; batches inside the lag re-run last |",
          "| Write mode (idempotent?) | `<overwrite-partition / delete+insert / merge on key>` |",
          "| Scheduled job paused or excluded | `<dag/job>` paused at `<time>` by `<who>` |",
          "| Cost per batch (dry run) and total | `<bytes or credits>` x " + f"{len(bs)} = `<total>` |",
          "| Downstream consumers to re-run | `<models / extracts / dashboards>` |",
          "| Rollback method | `<time travel / snapshot table / recompute>` |",
          "| Approved by | `<name>` on `<date>` |", "",
          "## Summary", "",
          f"- Range: `{a.start}` to `{a.end}` (half-open), {span} days",
          f"- Batches: {len(bs)} of up to {a.chunk} day(s), order **{a.order}**, max parallel **{a.max_parallel}**",
          f"- Command template: `{a.cmd}`", "",
          "## Stop conditions", "",
          "Stop and roll back the current batch if any of these happens; do not continue to the next batch.", "",
          "- Verification mismatch (row count, grain uniqueness, measure sums, date bounds) against the reference",
          "- Batch cost above 2x the dry-run estimate",
          "- The paused schedule ran, or a downstream alert fired",
          "- Any error that is not understood", "",
          "## Batches", "",
          "| # | Window (>= start, < end) | Command |", "|---|---|---|"]
    for i, (s, e) in enumerate(bs, 1):
        L.append(f"| {i} | {s} to {e} | `{render(a.cmd, i, s, e)}` |")
    L += ["", "## Checklist", "",
          "One line per batch. Fill every cell; an empty cell means the batch did not happen.", ""]
    for i, (s, e) in enumerate(bs, 1):
        L.append(f"- [ ] **Batch {i}** `{s}` to `{e}`: dry run `[ ]` ran `[ ]` verified `[ ]` (rows: __ grain unique: __ sums: __) recorded by __ at __")
    L += ["", "## Rollback", "",
          "Per partition, the exact statement that restores it. Write it before batch 1, test it on one partition in a dev target.", "",
          "```sql", "-- e.g. CREATE OR REPLACE TABLE target PARTITION ... AS SELECT * FROM target FOR SYSTEM_TIME AS OF '<ts before batch>' WHERE dt = '<dt>';",
          "```", "",
          "## Done means", "",
          "- Every batch above has a verified, recorded checklist line",
          "- Scheduled job unpaused; downstream consumers re-run or notified",
          "- This file is attached to the ticket or PR", ""]
    a.out.write_text("\n".join(L))
    print(f"wrote {a.out} ({len(bs)} batches, {span} days, {a.order}). Nothing was executed.")


if __name__ == "__main__":
    main()
