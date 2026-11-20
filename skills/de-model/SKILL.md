---
name: de-model
description: Scaffold and ship a dbt model from a one-line spec with its grain, materialization, schema.yml, and tests decided up front, then run and verify it. Use whenever the user wants to create, add, build, scaffold, or design a dbt model, mart, fact or dimension table, staging model, incremental model, or "a new table in the warehouse", asks what grain or unique key a model should have, how to make a model incremental, which dbt tests to add, or says "model this data" or "turn this query into a model". Fallback for the design.data-model capability; the lifecycle-router picks the user's own modeling skill or the ECC database-reviewer agent first when they fit better.
---

# DE Model

## Why this skill exists

Most data bugs are grain bugs. A model whose author never wrote down "one row per X"
cannot be tested for fan-out, cannot be made incremental safely, and cannot be reconciled
after a change. This skill forces the grain, materialization, and null contract to be
decided before any SQL is written, and encodes them as dbt tests so the decisions survive
the next person's edit. When the lifecycle-router found a better provider (the user's own
modeling skill, or ECC's `database-reviewer` agent for warehouse-specific design), use
that; this skill is the fallback.

## Step 0: Decide before scaffolding

Answer every row. If the user cannot, ask; a guess here becomes a production incident.

| Decision | Question | Encoded as |
|---|---|---|
| Grain | What does one row mean? Which column(s) identify it? | `unique` + `not_null` on a single key; `dbt_utils.unique_combination_of_columns` on a composite key |
| Materialization | `view` (cheap, always fresh), `table` (rebuilt each run), `incremental` (big, append-heavy)? | `config(materialized=...)` |
| Incremental contract | Which `unique_key`? Which column drives the filter? How late does source data land, in days? | `unique_key`, lookback window in the `is_incremental()` block |
| Partition / cluster | Which date column do consumers filter on? | `partition_by` config, `not_null` test |
| SCD handling | Does the source change history? Current-row flag, effective dates, or snapshot? | Join on `is_current` or date range; never on the natural key alone |
| Null contract | Which measures may be null and what does null mean? | `not_null` tests; a `COALESCE` is a decision, not a fix |
| Source freshness | How stale can the source be before this model is wrong? | `freshness` block on the source |
| Consumers | Who reads this and at what grain do they aggregate? | Description; exposures if a dashboard depends on it |

Verify the grain claim against the source before building on it:

```sql
select <grain cols>, count(*) from <source> group by all having count(*) > 1 limit 5;
```

If rows come back, the grain is wrong or the source needs deduping. Fix that first.

## Step 1: Scaffold

Run the script next to this file. It writes `<name>.sql` and `<name>.yml` and refuses to
overwrite without `--force`.

```bash
python3 -I <this skill>/scripts/scaffold_model.py fct_orders \
  --grain order_id --measures gross_amount,net_amount \
  --source "{{ ref('stg_shop__orders') }}" --materialized incremental \
  --partition order_date --lookback-days 3 \
  --description "One row per placed order, finance's revenue source of truth" \
  --out models/marts/finance/
```

What it produces, and why each piece is there:

- **SQL** with `source`, `renamed`, `final` CTEs. The `final` CTE carries a comment pinning
  the grain so a later join cannot fan out unnoticed.
- **Incremental filter** with a lookback window and a comment saying the default is a
  guess. Check the source's landing lag before trusting it; a 1-day lookback on a source
  that lands 3 days late silently drops rows.
- **`on_schema_change='append_new_columns'`** so a new upstream column does not break
  the run.
- **schema.yml** with tests matching Step 0. Composite grains get
  `dbt_utils.unique_combination_of_columns`; add `dbt-utils` to `packages.yml` if missing.

Then fill in the `renamed` CTE with real column logic and write the measure descriptions
with units. Descriptions that say "amount" without a currency are documentation that lies.

## Step 2: Verify

Climb the ladder. Quote each command and its result in your report; a step you could not
run is an open question, not a pass.

1. `dbt parse` compiles the project. Catches bad refs and YAML before anything runs.
2. `dbt run --select <name>` builds it. For incremental, run twice: the second run must
   not change row counts.
3. `dbt test --select <name>` runs the grain and null tests you just declared.
4. Grain check on the built model, same query as Step 0 against the target. Zero rows.
5. Row count against the source at the same grain:

```sql
select (select count(*) from <model>) as model_rows,
       (select count(distinct <grain cols>) from <source>) as source_keys;
```

A mismatch means a filter or join changed the grain.

## Step 3: Hand off

- Changing an existing model rather than creating one? Run `de-verify` (capability
  `verify.reconcile`) for before/after row counts and measure sums. New models have no
  "before", so Step 2 is the verification.
- Before the PR, run `de-code-review` on the diff. It will check the incremental logic,
  partition pruning, and the tests against the failure-mode list.
- Add the model to the relevant exposure if a dashboard will read it, so lineage shows
  who breaks when it changes.

## Common mistakes this skill is here to prevent

- Declaring a grain in prose and not in a test.
- `incremental` with `unique_key` on a column that is not unique in the source.
- A lookback window chosen without looking at source latency.
- `view` materialization for a model queried thousands of times a day.
- `SELECT *` from a wide source into a `table` model.
