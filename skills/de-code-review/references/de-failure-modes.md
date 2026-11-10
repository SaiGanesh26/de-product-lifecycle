# Data-engineering failure modes

A checklist for the adversarial pass. Work only the sections the diff touches. For each
item, the question is not "did the author think about this" but "can I show it goes
wrong, and with what input". Where a verification command exists, run it and quote it.

Contents:
1. Grain and joins
2. Nulls, types, and time
3. Idempotency, reruns, and backfills
4. Incremental and merge logic
5. Schema changes and contracts
6. Orchestration (Airflow / Dagster / Prefect)
7. Spark and distributed jobs
8. Performance and cost
9. Security and governance
10. Observability and data quality
11. Infra and config

---

## 1. Grain and joins

- **Fan-out.** Any join where the right side is not unique on the join key multiplies
  rows. Verify: `SELECT key, COUNT(*) FROM right GROUP BY 1 HAVING COUNT(*) > 1 LIMIT 5`.
  Then compare row counts of the model before and after the change.
- **Grain drift.** A CTE aggregates to one grain, a later CTE joins it at another.
  Trace the declared grain (model docs, `unique_key`, primary-key test) through every CTE.
- **`LEFT JOIN` turned inner.** A `WHERE right.col = ...` filter on the nullable side
  silently drops unmatched rows. The filter belongs in the `ON` clause.
- **Missing dedup on a slowly changing source.** Joining to a dimension with multiple
  versions per key without `is_current` or an effective-date range.
- **Accidental cross join.** Comma joins, or a join condition that got lost in a refactor.
  `EXPLAIN` shows it as a nested loop over both inputs.
- **Semi-join as join.** Using a join to filter where `EXISTS` was meant, then selecting
  from the left side with duplicated rows.

## 2. Nulls, types, and time

- **Three-valued logic.** `col NOT IN (subquery)` returns nothing if the subquery yields
  a single null. `col != 'x'` excludes nulls. `COUNT(col)` vs `COUNT(*)`.
- **Null-swallowing fixes.** `COALESCE(measure, 0)` makes a data-quality problem invisible
  and wrong instead of visible and wrong. Ask where the nulls come from.
- **Silent casts.** Integer division, string-to-number casts that fail on one bad row in
  production but not in dev, `SAFE_CAST` hiding garbage, float for money.
- **Timezone.** Mixing `TIMESTAMP` and `TIMESTAMP_TZ`/`TIMESTAMPTZ`, `DATE(ts)` in the
  warehouse's default zone vs. the business's zone, DST making a day 23 or 25 hours.
- **Boundaries.** `BETWEEN` is inclusive on both ends. `< end_date` vs `<= end_date` on a
  half-open daily partition. Off-by-one on week or month starts.
- **Late-arriving data.** Any aggregation by event date assumes the data for that date
  has all arrived. Check the source's landing lag against the lookback window.
- **String comparisons.** Case, trailing whitespace, unicode normalization on keys that
  come from humans.
- **Division by zero and empty sets.** Ratios with a zero denominator; `AVG` over an
  empty group returning null and then being summed.

## 3. Idempotency, reruns, and backfills

- **Run it twice.** Does the second run double-count? Append-only writes without a
  delete-and-insert or merge on the partition are the usual culprit.
- **Partial writes.** A mid-run failure after step 3 of 5: is the target left in a state
  the next run can recover from? Transactions, write-then-swap, or partition overwrite.
- **Hardcoded dates.** `WHERE dt = '2026-11-01'` or `CURRENT_DATE()` where the run's
  logical date (`{{ ds }}`, `context.partition_key`) should be used. Backfills then
  reprocess the wrong day.
- **Backfill window.** Is the backfill parameterized and bounded? Does it respect the
  target's partitioning so it overwrites exactly the partitions it recomputes?
- **Side effects.** Sending notifications, calling external APIs, or incrementing
  counters inside a task that may be retried.

## 4. Incremental and merge logic

- **Unique key is actually unique.** Confirm with a query on the source. A composite key
  declared as a single column produces silent updates of the wrong rows.
- **Lookback covers reality.** `WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})`
  misses rows that landed out of order. Compare the source's latency distribution to the
  lookback.
- **Full-refresh path.** The `is_incremental()` branch and the full-refresh branch must
  produce the same table. Run both on a sample and diff.
- **Deletes.** Soft-deleted or hard-deleted source rows: does the incremental model ever
  remove them?
- **Schema change under incremental.** `on_schema_change` config, or what happens when a
  new column appears mid-stream.
- **Merge predicates.** `MERGE ... WHEN MATCHED` without a change-detection predicate
  rewrites every row every run (cost) and resets `updated_at` (correctness).

## 5. Schema changes and contracts

- **Breaking changes.** Column drops, renames, type narrowing, nullable to not-null,
  changed grain, changed semantics under the same name. Grep downstream models, BI
  layers, exports, and API consumers for the column.
- **Reversibility.** Can the migration be rolled back without data loss? Is there a
  `down` path, or at least a copy of the old table?
- **Ordering.** Is the migration applied before the code that depends on it, and does the
  old code survive the new schema during the deploy window?
- **Contracts and tests.** New columns get a description, a type, and at least a
  not-null or accepted-values test where that is the invariant. Public models with
  `contract: enforced` need the change reflected in the contract.
- **Defaults.** Adding a NOT NULL column to a big table with a default can rewrite the
  table or lock it; check the warehouse's behavior.

## 6. Orchestration (Airflow / Dagster / Prefect)

- **Dependencies.** Every data dependency is a declared task dependency or sensor.
  A task that reads a table another DAG writes needs a cross-DAG dependency, not hope.
- **`start_date` and `catchup`.** A new DAG with `catchup=True` and an old `start_date`
  launches hundreds of runs on deploy. A dynamic `start_date` (`datetime.now()`) breaks
  scheduling.
- **Retries and timeouts.** Tasks without `retries` fail on transient errors; tasks
  without `execution_timeout` hang forever. Sensors need `mode='reschedule'` or a
  timeout, or they hold a worker slot indefinitely.
- **Logical date usage.** Tasks use the run's logical date, not wall-clock time, so
  reruns and backfills compute the right partition.
- **Top-level code.** DB connections, API calls, or heavy imports at DAG-file top level
  run on every scheduler parse.
- **Pools and concurrency.** New heavy tasks that will contend with existing ones;
  `max_active_runs` for DAGs that must not overlap.
- **Schedule vs upstream.** A DAG scheduled at 02:00 reading a source that lands at
  03:00 produces yesterday's numbers with today's date.
- **Alerting.** `on_failure_callback` or equivalent wired for anything that matters;
  SLA misses routed somewhere a human reads.

## 7. Spark and distributed jobs

- **Skew.** Joins or aggregations on a key with a few giant values (null, 'unknown',
  default IDs). Salting or broadcast as fixes.
- **Shuffles.** Repartitions and wide transformations introduced by the change; check
  the physical plan.
- **Collect to driver.** `.collect()`, `.toPandas()` on an unbounded DataFrame.
- **Caching.** `cache()` without `unpersist()`, or caching something used once.
- **Non-deterministic UDFs** with retries produce different results per attempt.
- **Small files.** Writes without `coalesce`/`repartition` that produce thousands of
  tiny files; or the opposite, one giant file.
- **Schema inference** on read in production paths instead of an explicit schema.

## 8. Performance and cost

- **Partition pruning.** A function wrapped around the partition column
  (`DATE(partition_ts) = ...`) or a join to a non-literal disables pruning. `EXPLAIN` or
  `--dry_run` bytes before vs after.
- **`SELECT *`.** Into a wide table, or in a CTE that then gets materialized.
- **Clustering and sort keys.** Changes that drop or reorder them; queries that stop
  benefiting.
- **Materialization.** A view that is queried thousands of times a day and should be a
  table; a table rebuilt hourly that nobody reads.
- **Warehouse and cluster sizing.** Changes to size, autoscaling, auto-suspend, or
  retention have a monthly bill attached. Ask for the estimate.
- **Full scans in incremental models.** The incremental filter has to reach the
  expensive source, not just the final select.

## 9. Security and governance

- **Secrets.** Credentials, tokens, or connection strings in code, config, notebooks,
  DAG params, or log statements. Check `git diff` for anything that looks like a key.
- **PII.** New columns carrying email, phone, address, free text, or IDs that join to a
  person, without masking, hashing, column-level tags, or access policy. New tables in
  schemas with broad grants.
- **Access.** IAM, grants, or service-account scope widened "temporarily".
- **Injection.** SQL built with f-strings from any input that is not a constant.
- **Data residency and retention.** Copies of regulated data into new regions or
  into tables without a retention policy.

## 10. Observability and data quality

- **Tests for new logic.** New models and columns ship with the tests that encode their
  invariants: uniqueness on the grain, not-null on keys, accepted values, relationships,
  freshness on sources.
- **Tests that no longer test.** A changed grain makes an old uniqueness test pass
  trivially or fail spuriously; a removed test needs a reason in the PR.
- **Reconciliation.** For anything financial or customer-facing, a check that the new
  number ties out to a known source of truth.
- **Lineage.** Renamed or moved models that break `ref()`s, exposures, or downstream
  docs.
- **Logs and metrics.** Row counts, durations, and rejects emitted somewhere queryable.

## 11. Infra and config

- **Environment leakage.** Dev pointing at prod (or the reverse) through a default,
  a hardcoded project ID, or a profile target.
- **Terraform and IaC.** `plan` output reviewed, no `-auto-approve`, state locking,
  resources that will be destroyed and recreated rather than updated in place.
- **CI workflows.** Any change here is High tier: it decides what runs on every PR, and
  it can exfiltrate secrets.
- **Dependency bumps.** Major-version bumps of dbt, Airflow, Spark, or connectors with
  changelog entries that affect the project.
