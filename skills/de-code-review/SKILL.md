---
name: de-code-review
description: Review a diff, pull request, branch, or set of files for data-engineering code (SQL, dbt models, Spark/PySpark jobs, Airflow/Dagster/Prefect DAGs, Python ETL, schema migrations, warehouse or lakehouse infra) the way the Claude Code team reviews its own PRs. Verifies with tools it can actually run instead of trusting the author's or its own reading, scales rigor to blast radius, and reports only real bugs with file:line and an Important / Nit / Pre-existing label. Use this whenever the user asks to review, check, audit, sanity-check, double-check, or "look over" a change, PR, pipeline, model, DAG, query, backfill, or migration, asks "does this look right / is this safe to merge / what could go wrong", or wants a second opinion on data code they or an agent wrote, even when they never say "code review".
---

# DE Code Review

## Why this skill exists

Review has two jobs: catch what could go wrong before it ships, and build shared
understanding of the system. "Did someone read the code?" is a weak proxy for either.
The useful question is: **what could go wrong with this change, and which check,
automated or human, is the right one to catch it?** Data code raises the stakes. A bad
merge in an app breaks a feature; a bad merge in a pipeline silently corrupts every
table downstream and gets found by a stakeholder in a dashboard a week later.

Two principles from the sources this skill is built on shape everything below:

- **Never be your own judge.** Reading a diff and concluding it looks fine is the model
  judging itself. Insist on an outside judge: a compiler, a test suite, a dry run, a
  row-count comparison, a fresh-context second reviewer. If a tool can answer a
  question, run the tool. Only when nothing runnable exists do you fall back to reasoning,
  and then you say so.
- **Do, don't role-play.** "Pretend to be a staff engineer" changes vocabulary, not
  outcomes. Do what a demanding reviewer does: trace the join keys, execute the model
  against real data, diff the output, look for the goal beyond the ticket.

## Step 0: Pin down the target and the risk tier

Work out what is being reviewed. In order of preference: a PR number (`gh pr diff`,
`gh pr view`), a branch against its base (`git diff main...HEAD`), the working tree
(`git diff`, plus untracked files), or explicit paths. Read the **actual diff**, not the
PR description's summary of it. Then set the risk tier **from the change, not the
author**. An agent-authored PR and a principal's PR touching a backfill get the same
scrutiny.

| Tier | What's in the diff | What review looks like |
|---|---|---|
| Low | Docs, comments, dashboard-only SQL, test-only changes, formatting | Quick pass. Confirm it does what it says, stop. |
| Medium | New or changed transformation logic, new models or tables, DAG task changes, non-destructive schema additions, config | Full verification ladder (Step 2) plus the failure-mode pass (Step 3). |
| High | Anything that writes to or deletes from production tables, backfills, `MERGE`/upsert/incremental logic, migrations that drop, rename, or retype columns, partitioning or clustering changes, PII or access-control changes, secrets, IAM, CI workflow files, schedule or SLA changes, anything with a cost lever (cluster size, scan volume, retention) | Everything in Medium, plus a fresh-context second reviewer (Step 4), plus an explicit **"needs a human"** call-out in the report. |

Say which tier you chose and why, in one line, at the top of the report. Scaling rigor
is not laziness: a Deep review on a comment typo wastes the author's time and buries real
findings in noise, and noise is what gets reviews ignored.

## Step 1: Understand the intent, then the goal beyond the goal

Read the PR description, linked ticket, and any `CLAUDE.md` or `REVIEW.md` in the repo
(the latter holds the project's own definition of failure and its ignore list; honor it).
Answer three questions for yourself before hunting bugs:

1. Does the diff address the stated issue, all of it and only it?
2. Does it fit the larger system? Who reads these tables, who depends on this DAG,
   what schema contract is implied downstream?
3. What is the goal beyond the goal? A ticket says "fix the nulls in `revenue`". The
   real goal is "finance trusts the revenue number". A `COALESCE(revenue, 0)` closes the
   ticket and defeats the goal. For bug fixes, find the root cause; reject a symptom
   patch and say what the root cause is.

If the approach itself is wrong, say that first and briefly. Agents make new work cheap,
so "close this and do X instead" is a legitimate review outcome, and it is far cheaper
to pivot now than after another ten review cycles.

## Step 2: Verify with tools you can run

This is the heart of the skill. Climb as far up this ladder as the repo allows, record the
exact command and its output as evidence, and report where you had to stop. A finding
backed by a command is worth ten backed by a hunch. Treat anything you could not run as
an open question in the report, never as "looks fine".

1. **Parse and compile.** `dbt parse` / `dbt compile --select state:modified+`,
   `python -m py_compile`, `sqlfluff lint`, `terraform validate`, `airflow dags
   list-import-errors` or importing the DAG module in a shell. Cheapest possible proof
   that the change at least loads.
2. **Static and type checks.** `mypy`, `ruff`, the project's linters. Hook into whatever
   `pre-commit` config exists rather than inventing your own.
3. **Existing tests.** Run the project's test suite, or the subset touching changed
   paths. For dbt: `dbt test --select state:modified+`. Read failures, do not just count
   them.
4. **Dry runs and plans.** `EXPLAIN` / `EXPLAIN ANALYZE`, `bq query --dry_run` (scan
   bytes), `terraform plan`, `dbt run --empty`, `spark-submit` against a sample. Cost and
   blast radius show up here, before anything is written.
5. **Execute on real or representative data.** Run the changed model or function against
   a dev schema or a sampled slice. Then compare: row counts before vs after, distinct
   counts on the grain keys, sums on key measures, min/max on dates. A transformation
   change with no before/after comparison is unverified by definition.
6. **End to end.** Trigger the DAG in a dev environment, or run the pipeline on one
   partition, and look at the output table.

If a subagent or test runner can do the expensive steps in parallel while you read the
diff, use it. The author may have attached proof already (test output, a screenshot, a
row-count diff). Check that proof against what the diff actually touches: a green test
run proves nothing if no test covers the changed join.

## Step 3: Adversarial pass against data-engineering failure modes

Now assume the change is wrong and try to show how. Work through
[`references/de-failure-modes.md`](references/de-failure-modes.md) for the areas the diff
touches; the headline categories are:

- **Grain and joins:** fan-out from many-to-many joins, missing dedup, grain drift between CTEs, `LEFT JOIN` filtered in `WHERE` into an inner join.
- **Nulls, types, time:** three-valued logic in `NOT IN` and `!=`, silent casts, timezone and DST assumptions, inclusive/exclusive date boundaries, late-arriving data.
- **Idempotency and reruns:** does running it twice double-count? Does a mid-run failure leave partial writes? Is the backfill window parameterized or hardcoded?
- **Incremental and merge logic:** unique key truly unique, lookback window covers late data, full-refresh path still works, deletes handled.
- **Schema and contracts:** column drops, renames, retypes, nullability changes, and who downstream breaks. Migrations reversible?
- **Orchestration:** dependencies declared, `catchup`/`start_date` sane, retries and timeouts set, sensors that can hang forever, schedule vs. upstream freshness.
- **Performance and cost:** partition pruning preserved, no `SELECT *` into wide scans, no accidental cross join, cluster/warehouse sizing, retention.
- **Security and governance:** secrets in code or logs, PII in new columns without masking or tagging, over-broad IAM.
- **Observability:** data-quality tests added for new columns and models, alerts for new DAGs, lineage not broken.

Check the raw inputs, not the author's description of them: open the upstream model to
confirm the grain the diff assumes, look at the actual `unique_key` config, read the
real schedule. Most review misses come from trusting a summary.

## Step 4: Get a second opinion with fresh context (Medium and High)

You have been staring at this diff and have formed a story about it. That story is the
model judging itself. For Medium and High tiers, when you can spawn a subagent, hand a
fresh one the diff, the risk tier, the repo's `REVIEW.md`, and the failure-mode
reference. Pick that reviewer through the `lifecycle-router` skill
(`resolve.py resolve review.code`): the user's own reviewer agent outranks ECC's, which
outranks a generic subagent, and in ask mode the user chooses. Do **not** hand it your findings; anchoring is the whole thing you are trying
to avoid. Ask it to return findings in the same format you use.

Then vote. A finding both reviewers surfaced, or one that either can back with a command
and output, goes in the report. A finding only one of you raised and nobody can verify
gets downgraded to a question or dropped. This voting step is what keeps false positives
out, and false positives are what make authors stop reading reviews.

## Step 5: Filter ruthlessly, then report

Priority one is detecting real bugs. Priority two is cutting review cycles. Everything
else is noise, and noise is more expensive than it looks: a human dismisses a nit in a
second, but when the author is an agent, a nit becomes another commit, another CI run,
and another review round. Two agents once cycled fifty times overnight on one PR.

So:

- **Do not report** style, formatting, naming preferences, or cleanups unless the user
  asked for them or `REVIEW.md` demands them. Linters own that.
- **Label every finding** `Important` (real bug or real risk, must be fixed or resolved
  with a reason), `Nit` (worth a line, never blocks), or `Pre-existing` (a bug you found
  that this diff did not introduce; report it so it gets fixed, but do not blame the
  author for it). Roughly 59% of what an unconstrained reviewer flags is pre-existing
  code, so this label will be busy.
- **Name the bug class**, not just the instance ("every incremental model in
  `marts/finance/` uses a 1-day lookback; the source lands up to 3 days late"), so the
  author fixes all of them in one pass rather than one per review round.
- **Anchor each finding** to `path:line`. Guessed filenames are a credibility killer.
- **Give a concrete failure scenario**: the input or state, and the wrong output or
  crash it produces. "Could be a problem" is not a finding.
- **Say how to verify** the finding and, where it is obvious, how to fix it.
- **Do not re-report** issues from earlier rounds. On round two and later, review only
  the new diff. After three rounds on the same PR, stop finding and start asking the
  author to rethink the approach.

### Report template

```
## Review: <PR / branch / path>  —  Tier: <Low|Medium|High> (<one-line reason>)

**Verdict:** <Approve | Approve with fixes | Request changes | Needs human review>
**Findings:** <n> Important, <n> Nit, <n> Pre-existing   (or: **No issues found.**)

### What I verified
- `<command>` → <one-line result>
- ...
- Could not verify: <what, and why it matters>

### Important
1. `path/to/file.sql:42` — <one-sentence defect>
   Scenario: <input/state → wrong output>
   Verify: <command or query>
   Fix: <suggestion>

### Nit
...

### Pre-existing
...

### Needs a human
<Only for High tier or when a check is missing: what a person must look at and why.>
```

Always include the explicit finding count and, when clean, an explicit "No issues
found." A review with no summary line reads as unfinished.

## Where a human stays in the loop

Say so plainly when the change falls into one of these, because no amount of agent
review substitutes for a named person answering for it:

- Deciding whether to build it at all (taste, product direction).
- Destructive or hard-to-reverse operations: dropping tables or columns, deleting
  partitions, backfills over production, retention changes.
- Billing, auth, IAM, secrets, CI/CD workflow files, release and deploy scripts.
- Architecture choices that set conventions others will copy.
- Verifying the proofs: if you cannot describe what your checks would miss, the PR
  needs a real human review, not a thumbs-up.

A person answers for every change that ships, whoever typed it. The report's job is to
make that person's job easy, not to replace them.

## Closing the loop when something slips through

When a bug ships that review should have caught, do not add a shouted rule. Ask what was
missing from the reviewer's context, then encode it: a line in `REVIEW.md`, a new entry in
`references/de-failure-modes.md`, a dbt test, a CI check. Incidents and reverts are the
eval set for this skill. Keep the ones you hit and rerun the review against them when you
change these instructions.

## Setting up a project for this skill

Drop [`templates/REVIEW.md`](templates/REVIEW.md) at the repo root and tune it for a
few weeks: what counts as failure here, which paths to ignore, how nitpicky to be. Add
[`templates/PULL_REQUEST_TEMPLATE.md`](templates/PULL_REQUEST_TEMPLATE.md) so every PR
states how it was tested, what the risk is, and how to revert it. Those two files are
pulled into every review and do more for signal-to-noise than any instruction here.
