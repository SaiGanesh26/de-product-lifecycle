## What and why

<!-- One paragraph. Link the ticket. State the goal beyond the ticket if it differs. -->

## Testing

<!-- Runnable proof, not a claim. Paste the command and the relevant output.
     For transformations: row counts and key measures before vs after on a sample.
     For DAGs: the dev run link or the partition you ran. -->

```
```

## Risk

<!-- Tier (Low / Medium / High) and why. What breaks downstream if this is wrong?
     Which tables, dashboards, or consumers depend on what this changes? -->

## How to revert

<!-- The exact steps or command. If data was written, how it is restored or recomputed. -->

## Checklist

- [ ] Tests added or updated for new logic (uniqueness on grain, not-null on keys, freshness)
- [ ] Incremental and full-refresh paths produce the same result
- [ ] Reruns and backfills are idempotent
- [ ] No secrets, PII, or prod targets introduced in code or config
- [ ] Downstream consumers of changed columns or schedules checked
