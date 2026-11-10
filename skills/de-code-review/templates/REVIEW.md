# REVIEW.md

Project-specific tuning for automated and agent code review. Keep this short; it is
loaded into every review. Edit the bracketed parts, then delete this paragraph.

## What failure means here

- [Numbers in `marts/finance/*` must tie out to the ledger. Any change there is High tier.]
- [Documentation and column descriptions must not lie about what a column contains.]
- [A DAG that silently produces stale data is worse than one that fails loudly.]
- [Config must not route dev runs at prod targets.]

## Always High tier

- `[dags/**]` schedule or dependency changes
- `[models/marts/finance/**]`
- Any migration that drops, renames, or retypes a column
- `.github/workflows/**`, `[terraform/**]`

## Ignore

- `[docs/**]`, `[notebooks/scratch/**]`, generated files `[target/**, dbt_packages/**]`
- Formatting and naming: owned by `[sqlfluff / ruff]`, do not comment on them.

## Reporting rules

- Every finding anchors to `path:line`. No guessed filenames.
- Label each finding `Important`, `Nit`, or `Pre-existing`.
- Give a concrete failure scenario and a way to verify it.
- Open with a summary: finding counts, or an explicit "No issues found."
- Do not re-report findings from earlier rounds. After three rounds, recommend rethinking
  the approach instead of adding findings.

## Known noisy areas (do not flag)

- [`legacy/**` has known null handling issues tracked in TICKET-123; report as
  Pre-existing only if the diff touches them.]
