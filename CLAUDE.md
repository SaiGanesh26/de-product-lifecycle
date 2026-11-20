# de-product-lifecycle

A Claude Code plugin of data-engineering skills and agents. Everything in this repo is read by
an AI agent at run time, so write for that reader: explain why, keep instructions imperative,
end every step in something runnable.

## Layout

- `.claude-plugin/plugin.json`, `marketplace.json`: plugin identity and version. Bump both
  together on every change that ships (semver: skills added = minor, fixes = patch).
- `lifecycle.json`: the capability contract (stage, keywords, known providers, fallback).
  Add a capability when a new stage flow appears; a fallback that is not built yet carries
  `"planned": true` and the resolver reports it honestly.
- `skills/<name>/SKILL.md` plus optional `scripts/`, `templates/`, `references/`.
- `agents/<name>.md`: decision flows with their own context; preload skills via `skills:`.
- `hooks/hooks.json`: plugin hooks. Keep them fast, silent, and opt-in.
- `commands/`, `workflows/`, `.mcp.json`: slash commands, multi-agent loops, and MCP servers
  when a flow needs them. Any component kind is welcome; each joins the lifecycle by being
  declared as a provider or fallback in `lifecycle.json`, and each gets a row in the README.

## Conventions for skills

- Frontmatter `description` is the trigger. Say what it does and list the phrasings a user
  would actually type, including ones that never name the skill.
- Under ~200 lines. Push detail into `references/`.
- Scripts are python3 stdlib only, argparse, a module docstring, and must run under
  `python3 -I <script> --help`. Never execute anything destructive from a script.
- No em dashes. Plain ASCII punctuation.
- The user's own tools outrank ECC's, which outrank this plugin's flows. Say so where a skill
  is a fallback, and point at the `lifecycle-router`.
- Reuse before building: check `~/.claude/plugins/marketplaces/ecc/skills/` for an existing
  provider and wrap or reference it instead of duplicating.

## Workflow (applies to every change, including ones Claude makes)

1. Never commit to `main`. Branch from `main` with a prefix that says what the change is:
   `feat-<topic>`, `fix-<topic>`, `chore-<topic>`.
2. Update `README.md` in the same change: the skills table, the roadmap, and the install or
   usage lines if they moved. A PR that adds or changes a skill without touching the README
   is incomplete.
3. Test every script you touched (`--help` under `python3 -I` plus one real run on synthetic
   data) and run `claude plugin validate .` before committing.
4. Commit with a conventional message (`feat: ...`, `fix: ...`, `chore: ...`), push the
   branch, and open a PR against `main` with `gh pr create`. Do not merge; the owner merges.
   The PR body carries what was tested and how to revert, same standard this plugin asks of
   data PRs.
5. The installed plugin updates from `main`, so a change is live only after merge and
   `claude plugin update de-product-lifecycle`. Say this in the PR when it matters.

## Local testing of the plugin

`claude plugin validate .` checks manifests. Run a skill's script directly from the checkout
to test it; `claude plugin details de-product-lifecycle` shows the installed inventory and
token cost after an update.
