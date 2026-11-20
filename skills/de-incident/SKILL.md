---
name: de-incident
description: Triage a failed, late, or silently wrong data pipeline from symptom to root cause, contain it, decide fix versus backfill, and draft the incident writeup. Use whenever the user says a run failed, a DAG is red, a dashboard is stale or empty, the numbers look wrong, a table stopped updating, a dbt build or test failed, data is late, they are on-call, or they need a postmortem or incident report for a data problem, even if they never say "incident".
---

# DE Incident

## Why this skill exists

A data incident is rarely found where it happened. The symptom is a stakeholder saying a
dashboard looks wrong; the cause is three layers upstream, two days earlier. Triage that
starts at the symptom and guesses wastes the first hour. Triage that walks the layers in
order, collecting one piece of evidence per layer, finds the cause in minutes and leaves a
trail the writeup can cite. The incident then becomes an eval case: the question that
matters most is not who broke it but which layer should have caught it (see
`skills/de-code-review/references/sources.md`, from the Claude Code team's review article).

Two rules throughout:

- **Evidence before hypothesis.** Every layer below has a command. Run it, quote the output,
  then reason. A triage note with no command output is a guess.
- **The system is reviewed, not the person.** Write "the freshness check did not exist", never
  "X forgot the freshness check".

## Step 0: Pin the symptom

Write one line before touching anything: *what is wrong, since when, who noticed, which
table or dashboard.* "Revenue dashboard shows zero for 2026-11-18, noticed 09:10 by finance,
reads `marts.fct_revenue_daily`." If you cannot write that line, ask for the missing piece.
It fixes the blast radius and the partition you will reproduce on.

If the lifecycle-router has picked a provider such as ECC's `silent-failure-hunter` agent
for swallowed-error hunting, use it for the code-reading part of Step 2 and 3 and keep the
evidence collection here.

## Step 1: Walk the layers, stop at the first that explains the symptom

Go in this order, from source to consumer. At each layer, run the command, record the
result, and ask: *does this alone explain the symptom?* If yes, stop walking and go to
Step 2. If no, note "clean" and move on. Walking past the first explaining layer collects
noise, not insight.

| Layer | Question | Evidence command |
|---|---|---|
| 1. Source | Did the data arrive, and when? | `SELECT MAX(loaded_at), COUNT(*) FROM raw.<source> WHERE dt = '<day>'` and the source's landing SLA. dbt: `dbt source freshness`. |
| 2. Orchestration | Did the run start, finish, retry, or hang? | Airflow: `airflow dags list-runs -d <dag> --start-date <day>` then `airflow tasks states-for-dag-run <dag> <run_id>`; task log for the failed task. Dagster: `dagster run list --limit 20` and `dagster run logs <run_id>`. Prefect: `prefect flow-run ls --limit 20`, `prefect flow-run logs <id>`. |
| 3. Transformation | Which model or test failed, with what message? | `python3 -I <this skill>/scripts/run_results_summary.py target/run_results.json`; `grep -n "Database Error\|Compilation Error\|FAIL" logs/dbt.log \| tail -40`. Spark: driver log tail and the failed stage. |
| 4. Load / write | Did the right rows land, once? | `SELECT dt, COUNT(*) FROM <table> GROUP BY 1 ORDER BY 1 DESC LIMIT 10` (missing or doubled partitions); `SELECT <grain keys>, COUNT(*) FROM <table> WHERE dt='<day>' GROUP BY <grain keys> HAVING COUNT(*)>1 LIMIT 5` (duplicates). |
| 5. Consumer | Who reads it, and are they reading the right thing? | dbt: `dbt ls --select <model>+ --resource-type exposure`; BI tool lineage; the dashboard's query, filter, and cache age. |

Cheap heuristics that save time: a *schedule* firing before the *source* lands shows up at
layer 1 with a clean layer 2. Zero rows with a green run is layer 4 (filtered to nothing)
or layer 1 (nothing arrived). Doubled numbers are layer 4 (rerun without overwrite). A
stale dashboard with fresh tables is layer 5 (cache or filter).

## Step 2: Confirm by reproducing on one partition

A layer that explains the symptom is a hypothesis until it reproduces. Rerun the smallest
unit that exercises it, on the affected day only, into a dev target:

```
dbt build --select <model> --vars '{"run_date": "<day>"}' --target dev
# or: airflow tasks test <dag> <task> <day>
```

Then run the layer-4 counts against the dev output. If the symptom reappears, you have the
root cause. If it does not, the hypothesis is wrong; go back to the layer after the one you
stopped at. Say which happened.

## Step 3: Contain before you fix

Containment buys time and stops the blast radius growing. Pick the least invasive option
that works and name it in the writeup:

- **Flag off** the consumer feature if one exists, so the wrong number stops being shown.
- **Pause the DAG** (`airflow dags pause <dag>`) so a bad upstream does not get propagated
  further by the next scheduled run.
- **Point consumers at the last good partition** or snapshot while the fix lands.
- **Annotate the dashboard** with the impact window if nothing else is possible.

Do not "fix forward" in production before containing. A hurried fix on a live table is
the second incident.

## Step 4: Decide fix versus backfill, then verify

Answer two questions and write them down:

1. **Code fix, data fix, or both?** A bad join needs a code fix and a recompute. A late
   source needs no code change, only a rerun once it lands. A one-off bad upstream file
   needs a data fix and possibly a vendor ticket.
2. **Which partitions are wrong?** Bound them with the layer-4 counts. Everything in that
   window gets recomputed; nothing outside it does.

Hand the recompute to `de-backfill` (bounded, idempotent, partition-aware) and the proof
to `de-verify` (before/after counts and measure sums on the affected window against a
known-good reference). Until `de-verify` reports, the incident is not resolved, only
contained.

## Step 5: Write it up

Use `templates/incident.md`. Keep it under a page. The sections that earn their place:

- **Root cause with the evidence** you collected in Step 1 and the reproduction in Step 2.
  Paste command output, not paraphrase.
- **Which layer should have caught this, and what check gets added so it does.** This is
  the sentence the whole exercise exists to produce. A freshness test, a uniqueness test
  on the grain, a schedule dependency, an alert on zero rows, a review rule in
  `REVIEW.md`. One concrete check, with an owner.
- **Follow-ups, each with an owner and a check.** A follow-up with no check attached is a
  wish.
- **What we are not fixing and why.** Scope discipline, stated, so the next reader does not
  reopen it.

Then add the incident to the project's review eval set: the PR or run that caused it, the
fix, and the check. When `de-code-review` or the review rules change, rerun against it.

## Honest limits

- Commands above assume Airflow, Dagster, Prefect, dbt, or Spark. For other stacks, keep the
  layer order and swap the command; the order is the method.
- `run_results_summary.py` reads dbt's `run_results.json`, whose schema changes between dbt
  versions; it reads only `results[].status`, `unique_id`, `message`, and timing.
- Reproduction on one partition can miss causes that only appear at full volume (skew,
  memory). If one partition reproduces nothing and the failure was an OOM or timeout, say
  so and reproduce at the failing size in a dev cluster instead.
