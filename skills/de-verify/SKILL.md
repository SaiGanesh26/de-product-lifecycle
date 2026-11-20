---
name: de-verify
description: Prove that a change to a table, dbt model, Spark job, or SQL transformation did or did not change the numbers, with a before/after reconciliation you can paste into a PR. Compares row counts, grain uniqueness, null counts, measure sums and bounds, date ranges, and keys present on only one side, then flags what moved. Use after building or changing any model or pipeline output, before opening a PR, when asked "did this change the numbers", "does it still tie out", "compare old vs new", "verify the backfill", "is the refactor behavior-preserving", or whenever de-code-review or de-backfill needs evidence rather than a claim.
---

# DE Verify

## Why

A transformation change with no before/after comparison is unverified by definition. Tests
tell you the model still satisfies its declared invariants; they do not tell you whether
revenue moved by 3%. Reviewers who have to trust "I checked, it looks fine" either spend
their time re-checking or stop reading. A reconciliation table takes two minutes and ends
the argument. This is the outside judge the plugin's sources insist on: a query result, not
the model's or the author's opinion.

The lifecycle-router sends `verify.reconcile` here because nothing in ECC does it. If the
user has their own reconciliation tooling (a data-diff tool, a dbt audit package), prefer it
and use this skill's output format for the write-up.

## Steps

1. **Pin the two sides.** `a` is before: production, `main`, or the pre-change build. `b` is
   after: the dev schema, the branch build, the backfilled partitions. Both must be
   queryable from one place for the anti-join; otherwise run per side and compare files.
   Say which is which in the write-up; swapped sides invert every sign.
2. **Name the grain, measures, and date column.** Read them from the model's `schema.yml`
   or docs; do not guess. The grain keys are what `unique`/`unique_combination_of_columns`
   tests cover. Measures are the columns finance or product actually read. One date column
   bounds the comparison.
3. **Bound the comparison.** Full-table on a billion rows is cost, not rigor. Use `--where`
   to pick recent partitions, plus one older one if the change touches history. A dry run
   first on BigQuery or Snowflake tells you the bytes.
4. **Generate and run the query.**
   ```
   python3 -I <this skill>/scripts/reconcile.py sql --dialect bigquery \
     --a proj.prod.fct_orders --b proj.dev_ganesh.fct_orders \
     --keys order_id --measures net_revenue,quantity --date-col order_date \
     --where "order_date >= '2026-11-01'" --anti-join > /tmp/recon.sql
   bq query --use_legacy_sql=false --format=csv < /tmp/recon.sql > /tmp/recon.csv
   ```
   Snowflake: `snowsql -o output_format=csv -o header=true -f /tmp/recon.sql`. Postgres:
   `psql --csv -f /tmp/recon.sql`. dbt users: `dbt show --inline "$(cat /tmp/recon.sql)"`.
   Local files or tests: `reconcile.py run --engine duckdb --db dev.duckdb ...`.
5. **Compare and read the flags.**
   ```
   python3 -I <this skill>/scripts/reconcile.py compare /tmp/recon.csv --tolerance 0.5 \
     --expect-equal row_count,distinct_keys
   ```
   Exit code 1 means a flag fired. Flags are facts, not verdicts: a 3% revenue move is the
   point of a bug fix and a defect in a refactor. Match each flag to the change's stated
   intent and write one line per flag saying "expected because ..." or "unexpected, investigating".
6. **Duplicates and missing keys are never "expected".** `dup_rows` above zero on either side
   means the grain is wrong or a join fanned out; `keys_only_here` on side `a` means the
   change dropped rows. Stop and find the cause before anything else.
7. **Write the evidence block** and put it in the PR's Testing section (de-pr picks it up):

   ```
   ### Reconciliation: fct_orders, order_date >= 2026-11-01, a=prod b=dev_ganesh
   | metric | before | after | diff | pct | note |
   | row_count | 1,204,311 | 1,204,311 | 0 | 0.00% | |
   | distinct_keys | 1,204,311 | 1,204,311 | 0 | 0.00% | grain holds |
   | sum_net_revenue | 8,412,006.12 | 8,398,114.90 | -13,891.22 | -0.17% | expected: refunds now netted (TICKET-412) |
   | keys_only_here (a) | 0 | | | | |
   Command: reconcile.py sql ... (full command in PR)
   ```

## Interpreting common patterns

| Pattern | Usual cause |
|---|---|
| row_count up, distinct_keys flat | join fan-out or missing dedup |
| row_count down, keys_only_here(a) > 0 | filter moved into `WHERE` on a `LEFT JOIN`, or incremental lookback too short |
| sums flat, null_* up | silent cast or `SAFE_CAST` hiding bad rows |
| max_date behind | late data or a run that stopped early |
| everything flat on a bug fix | the fix did not reach the rows it was meant to |

## Limits

- The query is plain SQL so it runs anywhere; it does not do row-level diffs. For those,
  use the anti-join counts to confirm a mismatch exists, then sample with a targeted query.
- Sums of floats can differ in the last digits across engines; use `--tolerance` for that,
  never to wave through a real move.
- `compare` reads CSV or JSON with columns `side, metric, value`. Export your client's result
  with headers.
