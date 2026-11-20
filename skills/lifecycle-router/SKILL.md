---
name: lifecycle-router
description: Decide which installed skill or agent should handle a step of a data-engineering task, preferring the user's own tools over ECC's over this plugin's fallbacks, and either ask the user to pick from the ranked options (default) or decide automatically. Use at the start of any data-engineering task, before delegating a review, verification, impact analysis, migration, PR, backfill, or incident step, when the user asks "which skill should I use", "what are my options", "how should we approach this", or when they ask to switch the lifecycle to auto mode or back to asking.
---

# Lifecycle Router

## Why

The user has skills and agents from three places: their own, ECC's, and this plugin's. Claude
Code has no precedence between them. This skill supplies one, with a bias the user asked for:
**their own tools first, then ECC, then this plugin's flows as the last resort**. And unless
they have chosen auto mode, they decide, from a list of what is actually installed. Guessing
on their behalf costs a review cycle when the guess is wrong; a five-line list costs nothing.

## How to route one step

1. Name the capability. Run `capabilities` once if you are unsure which fits:
   ```
   python3 -I <this skill>/scripts/resolve.py capabilities
   ```
2. Resolve it with the task text, so keyword matches can use it:
   ```
   python3 -I <this skill>/scripts/resolve.py resolve review.code --task "<one line about the task>"
   ```
3. Read the last line of the output.
   - **ASK mode:** show the user the numbered options in one compact list (one line each:
     provider, where it comes from, why it fits). Include `L.` library options only if they
     clearly fit better than what is loaded, and the `F.` fallback always. Use
     `AskUserQuestion` when available; otherwise ask in prose and wait. Then record the pick:
     `resolve.py choose review.code agent:code-reviewer`. The record is what later lets the
     router suggest an override when the user keeps picking the same thing.
   - **AUTO mode:** use the named pick and say, in one line, what you chose and why
     ("using your `code-reviewer` agent for review.code; your own tools outrank ECC's").
     Never silently fall through to this plugin's flow when something higher ranked exists.
4. Run the chosen provider: a skill via the `Skill` tool, an agent via the `Agent` tool.
   For an ECC library item the user picked, first run the `harness_trim.py add <name> --pin`
   command the output prints, then read its `SKILL.md` directly from the library path for
   this session (a new link is only visible to new sessions).
5. If the pick is a fallback marked **not built yet**, say so and do the step by hand with the
   most relevant installed skill as reference. Do not pretend the fallback exists.

Resolve **one capability per step**, and pick **one provider**. Two reviewers on one diff means
two review cycles, which is the cost this whole plugin exists to avoid.

## Modes and overrides

- `resolve.py mode` shows the current mode; `mode auto` or `mode ask` sets it for the user;
  add `--project` to set it for the current repo only (project wins over user).
- `resolve.py override review.code agent:code-reviewer` pins a provider for one capability
  so it is never asked again; `--remove` undoes; `--project` scopes it to the repo.
- `resolve.py status` shows mode, overrides, and the decisions recorded so far. When the user
  has picked the same provider three times for a capability, it suggests the override.
  Pass that suggestion on; it is how ask mode converges toward auto without the user
  having to think about it.

## Where things come from

| Tier | Source | Notes |
|---|---|---|
| 0 | explicit override | project config, then user config |
| 1 | project `.claude/skills`, `.claude/agents` | the repo's own |
| 2 | user `~/.claude/skills`, `~/.claude/agents` | their own files |
| 3 | user links into the ECC library | the daily set `harness-trim` maintains |
| 4 | other enabled plugins | anything but this one |
| 5 | Claude Code built-ins named in `lifecycle.json` | assumed present; cannot be scanned |
| 6 | ECC library, not loaded | option only; needs `harness_trim.py add` |
| 7 | this plugin's fallback flows | last resort, by design |

The capability contract lives in [`lifecycle.json`](../../lifecycle.json) at the plugin root.
Add a capability there when a new stage flow appears; add a `known_providers` entry when you
learn a good external provider's name; mark fallbacks `planned` until they are built.
