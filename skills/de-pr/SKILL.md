---
name: de-pr
description: Open a data-engineering pull request whose description carries proof, not claims: the de-verify reconciliation block or test output under Testing, a risk tier with the downstream blast radius, and exact revert steps including how data is recomputed. Use when the user says open a PR, create a pull request, ship this, write the PR description, or is done with a model, DAG, migration, or backfill and needs it reviewed. Thin wrapper: creation itself goes through the user's own PR tooling or ECC's github-ops when the lifecycle-router picks them.
---

# DE PR

## Why

The Claude Code team's review write-up asks three things of every PR: how was it tested, what
is the risk, how do we revert. For data changes "revert" has a second half most PRs skip: the
code reverts in one commit, the rows it wrote do not. A PR that answers all three up front
merges with one reviewer; one that doesn't collects questions for a day. This skill makes
the template impossible to leave empty.

## Steps

1. **Collect proof before writing a word.** Proof is a file: the de-verify evidence block,
   the `dbt test` output, a dry-run byte count, a DAG run link. If none exists, stop and run
   `de-verify` first; `pr_body.py` refuses to produce a body without proof (exit code 2).
2. **Set the risk tier from the diff, not the author.** Use the table in
   `de-code-review`: Low (docs, tests, dashboards), Medium (transformation logic, new models,
   DAG task changes, additive schema), High (production writes or deletes, backfills,
   merge/incremental logic, destructive migrations, partitioning, PII, IAM, CI, schedules,
   cost levers). Name the downstream consumers that break if this is wrong.
3. **Write the revert as commands.** `git revert <sha>` plus what happens to data: nothing
   (view), rerun the model on `main` (table), restore partitions from the snapshot taken in
   step 1, or re-run the backfill plan from `de-backfill` in reverse. If a revert needs a
   human decision, say so; that alone makes the tier High.
4. **Assemble the body.**
   ```
   python3 -I <this skill>/scripts/pr_body.py \
     --title "feat(finance): net refunds in fct_orders (TICKET-412)" \
     --why "Finance sees gross not net revenue ... goal beyond the ticket: finance trusts the number" \
     --testing-file verification.md --risk High \
     --risk-why "marts/finance; feeds the board revenue dashboard and the Stripe reconciliation export" \
     --revert "git revert <sha>; dbt run --select fct_orders on main recomputes the table (12 min)" \
     --checks "tests added,idempotent,no secrets" > /tmp/pr_body.md
   ```
   It uses the repo's own `.github/PULL_REQUEST_TEMPLATE.md` when present, else the plugin's,
   lists changed files, and ticks checklist items you name.
5. **Create the PR with the provider the router picked** for `ship.pr`: the user's own PR
   skill, ECC `github-ops`, or plainly
   ```
   gh pr create --title "..." --body-file /tmp/pr_body.md --draft
   ```
   Open as draft when the tier is High or any check in step 1 could not be run; say which.
6. **Hand off to review.** Run or request `de-code-review` on the PR number. Do not approve
   your own PR and do not treat an agent's approval as a human one.

## Rules of thumb

- Small PRs merge; split a model change from its backfill from its downstream consumers.
- If the review flags a change of approach, close the PR rather than iterating past three
  rounds; new work is cheap, review cycles are not.
- One PR, one capability of the lifecycle; `de-lead` will have told you which.
