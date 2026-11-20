---
name: harness-trim
description: Keep Claude Code sessions lean by loading only the ECC skills and agents the user actually uses. ECC (ecc@ecc) injects ~35k tokens of skill descriptions into every session; this skill keeps the plugin installed but disabled as a library and symlinks a small daily set chosen from a data-engineering baseline plus the user's own transcript history. Use when the user complains sessions are slow, context fills up, there are too many skills, they want to trim or prune ECC or any large plugin, want to see which skills they really use, want a specific ECC skill back for a task, or want the full ECC library for one session.
---

# Harness Trim

## Why

Claude Code loads every installed skill's description into every session and has no way
to hide individual skills from a plugin. ECC's 400+ skills cost about 35k tokens before
the user types a word, and most of them are for stacks a data engineer never touches.
The fix is to treat ECC as a library on disk and load only a daily set, chosen by evidence:
a baseline for the user's role plus whatever their transcripts show they invoke.

## The script

Everything runs through `scripts/harness_trim.py` next to this file. Run it with
`python3 -I <path>/scripts/harness_trim.py <command>`. Commands:

| Command | What it does |
|---|---|
| `report` | Shows ECC usage counts from local transcripts (last 30 days), the daily set that `apply` would produce, and the token estimate vs. the full plugin. Read-only. Start here. |
| `apply` | Links the daily set into `~/.claude/skills` and `~/.claude/agents`, removes links no longer earned, disables `ecc@ecc`. Needs a new session to take effect. |
| `library` | Reverse: removes the links and re-enables the full plugin. For the odd session where the user wants everything. |
| `add <name>...` | Links one library skill or agent immediately, without re-enabling the plugin. `--pin` keeps it across future applies. |
| `pin` / `ban <name>...` | Per-machine overrides stored in `~/.claude/harness-trim/config.json`. `--remove` undoes. |

The daily set is: `baseline.json` skills and agents, plus pins, plus any ECC skill or agent
invoked at least `min_uses_to_add` times in the last `usage_window_days` (both in
`baseline.json`), minus bans, minus names that collide with Claude Code built-ins or with
this plugin's own skills. Only symlinks that resolve inside
`~/.claude/plugins/marketplaces/ecc` are ever created or removed; a user's own skill with the
same name is never overwritten.

## Automatic re-trim

This plugin ships a `SessionEnd` hook that runs `apply --if-stale 7 --quiet`. It does
nothing until the user has run `apply` once (opt-in), does nothing while they are in
library mode, and otherwise re-evaluates usage once a week so skills they start using get
promoted and ones they stop using get dropped. It never disables or enables the plugin on
its own; only an explicit `apply` or `library` does that.

## Using a library skill without loading it

When a task needs an ECC skill that is not in the daily set, you do not need to re-enable
the plugin. Read it straight from the library and follow it:

```
~/.claude/plugins/marketplaces/ecc/skills/<name>/SKILL.md
~/.claude/plugins/marketplaces/ecc/agents/<name>.md
```

If the user will want it again, run `add <name> --pin`. The `ecc-guide` and `skill-scout`
skills are in the baseline precisely so the library stays discoverable.

## Keeping the library fresh

`claude plugin marketplace update ecc` refreshes the clone the symlinks point at, so daily
skills update with ECC without reinstalling. If ECC renames or removes a skill, the next
`apply` drops the dangling link and says so.

## Honest limits

- Usage counting parses local transcripts, whose format is internal to Claude Code and may
  change. If `report` shows no usage you know happened, check the regexes in the script.
- Disabling the plugin also disables ECC's hooks and its `chrome-devtools` MCP server. Say
  so when applying; `library` brings them back.
- Token numbers are estimates from description length, same basis as `claude plugin details`.
