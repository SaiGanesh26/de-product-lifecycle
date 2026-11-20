# Incident: <one line: what was wrong, where>

**Status:** <contained | resolved | monitoring>
**Impact window:** <first bad partition or timestamp> to <last bad partition or timestamp>
**Blast radius:** <tables, dashboards, exports, downstream teams affected; rough user count if known>
**Detected by:** <alert name, or person and channel> at <time>
**Owner:** <person answering for the fix>

## Timeline

| Time | Event |
|---|---|
| <time> | <first bad data landed / run failed> |
| <time> | <detected> |
| <time> | <contained: what was done> |
| <time> | <root cause confirmed> |
| <time> | <fix merged> |
| <time> | <backfill complete / verified> |

## Symptom

<What was observed, in the words of whoever noticed it. One or two sentences.>

## Root cause

<One sentence naming the layer and the mechanism.>

Evidence:

```
<command>
<output>
```

Reproduction on one partition:

```
<command>
<output>
```

## Which layer should have caught this, and what check gets added so it does

<Layer name.> <The specific check: freshness test, grain uniqueness test, schedule dependency,
zero-row alert, review rule. Where it lives. Who adds it.>

## Fix

<Code change: PR link. Data change: what was recomputed and how. Containment that was applied
and when it was lifted.>

## Backfill

<done | pending> <partitions recomputed, command used, verification result from de-verify
with before/after counts and measure sums.>

## Follow-ups

| Follow-up | Owner | Check that proves it is done |
|---|---|---|
| <action> | <name> | <test, alert, or query that would now fail/fire> |

## What we are not fixing, and why

<Scope decisions, so the next reader does not reopen them.>
