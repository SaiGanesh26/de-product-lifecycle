---
name: de-impact
description: Blast-radius analysis for a data change before it is made. Given a dbt model, table, or column that will be dropped, renamed, retyped, made nullable, re-grained, or redefined, finds every downstream consumer from the dbt manifest (models, tests, snapshots, exposures) and the BI/export layer, and classifies each contract break with a migration step. Use whenever the user asks what breaks if they change a column or model, who depends on a table, whether a rename is safe, what the downstream impact or lineage of a schema change is, or before any migration that touches a shared mart; also when reviewing a PR that changes a model's columns or grain, even if they never say "impact".
---

# DE Impact

## Why

In application code a renamed field fails at compile time. In a warehouse it fails at 6am in
a dashboard nobody on the data team opens. The manifest knows most consumers; the BI layer
knows the rest; neither is read by default. This skill reads both before a change, so the
contract break is a table the author sees, not a Slack thread the stakeholder starts.

It extends ECC's `change-impact` skill rather than replacing it: that skill owns the generic
pass (callers, tests, docs, release order, rollback). This one owns data lineage and the
contract-break classification that generic tooling cannot see.

## Step 1: Generic pass with `change-impact`, if installed

Check for it:

```bash
ls ~/.claude/skills/change-impact ~/.claude/plugins/marketplaces/ecc/skills/change-impact 2>/dev/null
```

If present (first path means it is loaded; second means it is in the ECC library and can be
read directly), run its "Before the Change" questions for the code, interfaces, tests, docs,
and release sections. Skip its data section; Step 2 does that properly. If it is absent, say
so and answer those sections briefly yourself. Do not skip the release and rollback
questions; a data migration without a rollback path is a blocker, not a nit.

## Step 2: Lineage pass with the manifest

Make sure the manifest is current, then run the script. A stale manifest lists consumers that
no longer exist and misses new ones, which is worse than no list.

```bash
dbt parse
python3 -I <this skill>/scripts/dbt_impact.py --model fct_orders --column net_revenue \
  --grep-paths ../bi-repo ../exports
```

- `--model` alone lists everything downstream, transitively, with depth.
- `--column` keeps only nodes whose SQL mentions the column as a whole word. Exposures are
  always listed because a dashboard's column usage is not in the manifest.
- `--grep-paths` searches directories outside dbt (Looker, Tableau, Metabase exports, Python
  jobs) for the column or model name. Always pass the BI repo if one exists; undeclared
  exposures are the most common miss.
- `--json` for anything you will feed into a table.

Read the output critically. A node that mentions the column in a comment is a false positive;
a node that reads `SELECT *` from a model that mentions it is a false negative. Open the
`SELECT *` consumers and check them by hand.

## Step 3: Classify each break

For every consumer the script found, decide the break kind from what the change does to the
column or model as seen by that consumer:

| Break kind | What the consumer experiences | Typical severity |
|---|---|---|
| drop | column or model gone; query fails | High |
| rename | same as drop unless an alias is kept | High |
| retype | casts fail on some rows, or silent precision loss (float for money, int for id) | High |
| nullability | new nulls hit `NOT IN`, `!=`, joins, `SUM` | Medium |
| grain | row counts change; joins fan out or collapse; aggregates drift | High |
| semantics | same name, different meaning (gross vs net, UTC vs local); nothing fails, numbers are wrong | High, and the hardest to catch |

Severity goes up one level when the consumer is an exposure, is in a finance or
customer-facing mart, or has no test covering the column. It goes down one level when the
consumer is a test or analysis that the same PR updates.

Produce this table and nothing looser:

```
## Impact: <model or column> ,  <break kind(s)>

| Consumer | Type | Depth | Break | Severity | Owner | Migration step |
|---|---|---|---|---|---|---|
| fct_revenue_daily | model (incremental) | 1 | rename | High | finance-data | add alias `revenue` until 2026-12-01, then drop |
| Revenue dashboard | exposure (dashboard) | - | rename | High | @finance | update field in Looker view before merge |
| exports/stripe_recon.py | external | - | retype | High | ? | confirm cast; owner unknown, blocker |

Undeclared consumers: <count from --grep-paths, or "none searched" with the reason>
Unverified: <SELECT * consumers not opened, repos not searched>
```

An empty "Unverified" line is a claim; make sure it is true before writing it.

## Step 4: Recommend expand/contract when anything is High

A High break with a live consumer means the change ships in two steps, not one:

1. **Expand.** Add the new column or model beside the old one; backfill; add the new tests.
   Point consumers at the new name in their own PRs. Keep the old name as an alias or view.
2. **Contract.** Once every consumer in the table has moved (verify with the script again),
   drop the old name. Separate PR, separate review.

Say which consumers block the contract step and who owns them. For the migration mechanics
(concurrent indexes, batched backfills, zero-downtime renames per warehouse) hand off to ECC's
`database-migrations` skill. For the reconciliation that proves the new column matches the old
one, hand off to `de-verify` once it exists; until then, state the row-count and sum checks
inline.

## Honest limits

- Exposures only exist if someone declared them in dbt. "No exposures" means "none declared",
  and the output says so.
- Column mentions are text matches on raw and compiled SQL. Macros that build column names
  dynamically, and `SELECT *`, escape it. Say so under Unverified.
- Non-dbt consumers (Spark jobs, reverse ETL, notebooks) are only found if their directory is
  in `--grep-paths`.
