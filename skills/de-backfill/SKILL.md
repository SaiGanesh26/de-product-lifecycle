---
name: de-backfill
description: Plan and run a bounded, idempotent, partition-aware backfill of a table, dbt model, Spark job, or DAG over a date range, producing a written plan with ordered batches, per-batch verification, stop conditions, and rollback before any command runs. Use whenever the user wants to backfill, reprocess, reload, replay, re-run partitions, fix historical data, catch up a DAG, recompute a model for past dates, or asks "how do I safely re-run this for last month", even if they never say "backfill". Also use when someone proposes `--full-refresh` or `catchup=True` as a quick fix.
---

# DE Backfill

## Why this skill exists

A backfill is the most dangerous routine thing a data engineer does. It writes to
production tables on purpose, over many partitions, often while the scheduled run is also
writing. Done well it is boring. Done loosely it double-counts a quarter, blows a day's
warehouse budget in an hour, or overwrites good partitions with ones computed from
late-arriving sources that had not landed yet. Every failure mode has the same root: a
command typed before the questions below were answered. So the rule is simple: **no
command runs before the plan is written to a file and read back.**

Anything here that writes to production is **needs a human** in the sense `de-code-review`
uses: a named person reads the plan and approves the first batch. Do not approve it yourself.

## Step 0: Answer these before writing a single command

Write the answers into the plan header. If one is unknown, finding it out is the next task.

1. **Target and partition column.** Which table or model, and what column partitions it
   (`dt`, `event_date`, `_PARTITIONTIME`)? Verify: `SHOW PARTITIONS`, `INFORMATION_SCHEMA.PARTITIONS`,
   or the dbt `partition_by` config. A target without partitions cannot be backfilled in
   batches; say so and plan a full rebuild into a shadow table instead.
2. **Exact bounds and why.** `start` and `end` as dates, half-open (`>= start`, `< end`), and
   the evidence that fixed them (the bug's deploy commit date, the first bad partition from a
   reconciliation query). "Last month" is not a bound.
3. **Source landing lag.** How late does the upstream land? Any batch whose window ends
   inside the lag will be recomputed from incomplete data. Push `end` back or re-run those
   partitions last, after the lag has passed.
4. **Write mode.** Overwrite-partition, delete-then-insert, or merge on a key? Append is not
   an option; a second run must produce the same table as the first. Confirm by reading the
   model or job, not the ticket.
5. **Concurrency with the schedule.** Will the scheduled DAG or dbt job write the same
   partitions while the backfill runs? Pause it, or exclude the partitions it owns (usually
   the last one or two days).
6. **Cost.** Dry-run one batch: `bq query --dry_run`, `EXPLAIN`, `dbt run --empty`, or a Spark
   plan. Multiply by batch count and write the number down. A number nobody wrote down is the
   one that ends up in the incident review.
7. **Downstream.** Who reads this table? Which of them need their own re-run after each
   batch or after the whole thing? `dbt ls --select <model>+`, the lineage graph, BI extracts.
8. **Rollback.** How do you restore a partition if a batch is wrong? Time travel
   (`FOR SYSTEM_TIME AS OF`, `AT (TIMESTAMP => ...)`), a snapshot table, or recomputing from
   source. If the answer is "recompute", the rollback is itself a backfill; plan it too.

## Step 1: Generate the plan file

Use the bundled script so batches, commands, and the checklist are produced the same way
every time and nothing is typed by hand twice:

```
python3 -I <this skill>/scripts/backfill_plan.py \
  --start 2026-10-01 --end 2026-11-01 --chunk 1 \
  --order newest-first --max-parallel 1 \
  --cmd "dbt run --select fct_orders --vars '{start_date: \"{start}\", end_date: \"{end}\"}'" \
  --out backfill-fct_orders-2026-10.md
```

`{start}` and `{end}` are rendered per batch as half-open dates; `{start_iso}` and `{end_iso}`
give midnight timestamps. Chunk size: one day for anything heavy or high-risk, up to a week
for small dimension-like tables. **Newest first** is the default for a reason: the most
recent partitions are the ones people are looking at, so a wrong result shows up fastest,
before the bulk of the range has been written. Choose oldest-first only when later
partitions depend on earlier ones (running totals, SCD chains).

Then fill in the header questions and the rollback section in the generated file. Ranges
over three years are refused unless you pass `--i-know`; that refusal exists because such
ranges are almost always a sign the real fix is a rebuild into a new table plus a swap.

## Step 2: Review the plan before batch 1

Read the file back and check, in this order: bounds match the evidence, write mode is
idempotent, the scheduled job is paused or excluded, cost is written down and acceptable,
rollback is concrete. Then hand it to the human who owns the table. Only after their
approval does batch 1 run.

## Step 3: Run batches with verification between them

For each batch, in the plan's order:

1. **Dry run** the rendered command where the tool supports it.
2. **Run** it. Never more batches in parallel than `--max-parallel`; the default of one is
   the right starting point until the first two batches have verified clean.
3. **Verify** with `de-verify` (or its reconciliation query by hand until it is built):
   row count, distinct count on the grain key, sum of the key measures, min and max of the
   partition column, for the batch window only. Compare with a known-good reference: the
   pre-backfill snapshot, a source aggregate, or a reconciled sibling table.
4. **Record** the result in the plan file's checklist. A backfill with no written record of
   which batches ran is unfinished by definition.

**Stop conditions**, written in the plan: any verification mismatch, any batch exceeding
twice the dry-run cost estimate, any failure of the paused schedule's guard, any downstream
alert. On stop, do not continue; roll back the failed batch using the rollback section and
reassess.

## Tool patterns

**Airflow.**
```
airflow tasks clear <dag_id> -t <task_id> -s 2026-10-01 -e 2026-10-31 --yes   # re-run existing runs
airflow dags backfill <dag_id> -s 2026-10-01 -e 2026-10-31 --reset-dagruns     # create runs for the range
```
Tasks must use the logical date (`{{ ds }}`, `data_interval_start`), never `datetime.now()`,
or every backfilled run recomputes today. Never flip `catchup=True` on a live DAG to
backfill; it schedules every missed interval at once with no batching, no verification,
and no stop condition.

**dbt.**
```
dbt run --select fct_orders --vars '{start_date: "2026-10-01", end_date: "2026-10-02"}'
```
The model must read those vars in its incremental filter and the materialization must be
`insert_overwrite` (or `delete+insert` / `merge` on a true unique key). `--full-refresh` is
the wrong tool for a backfill: it rebuilds every partition, costs the whole table, and
removes the ability to stop between batches.

**Spark and SQL partition overwrite.**
```
spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
df.write.mode("overwrite").partitionBy("dt").saveAsTable("...")      # overwrites only touched dt values
INSERT OVERWRITE TABLE t PARTITION (dt) SELECT ... WHERE dt >= '{start}' AND dt < '{end}';
```
Confirm the overwrite mode is dynamic, or `overwrite` replaces the whole table.

**Warehouse MERGE.**
```
MERGE INTO target t USING (SELECT ... WHERE dt >= '{start}' AND dt < '{end}') s
ON t.key = s.key AND t.dt = s.dt
WHEN MATCHED AND (t.hash <> s.hash) THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...;
```
Scope the `USING` side to the batch window, include the partition column in the `ON`
clause so pruning works, and add a change predicate so unchanged rows are not rewritten.

## Done means

Every batch has a verified checklist line, the schedule is unpaused, downstream consumers
were re-run or notified, and the plan file is attached to the ticket or PR as the record.
