# de-product-lifecycle

Skills I build or adopt as a data engineer, covering the lifecycle of a data product:
design, build, review, ship, operate. Each skill is a folder with a `SKILL.md` that an
AI coding agent (Claude Code, or anything that reads the Agent Skills format) loads when
the task matches its description.

## Skills

Stage by stage. Each skill ends in something runnable and says when the user's own tools or
ECC's should be used instead.

| Stage | Skill | What it does |
|---|---|---|
| design | [`de-impact`](skills/de-impact/SKILL.md) | Blast radius of a model or column change from the dbt manifest and BI layer, as a contract-break table. Extends ECC `change-impact`. `scripts/dbt_impact.py`. |
| design | [`de-model`](skills/de-model/SKILL.md) | Decision checklist (grain, materialization, lookback, partition, SCD) then scaffolds a dbt model with schema tests and runs it. `scripts/scaffold_model.py`. |
| verify | [`de-verify`](skills/de-verify/SKILL.md) | Before/after reconciliation of a changed table: counts, grain uniqueness, nulls, sums, bounds, one-sided keys. Flags what moved; exit 1 gates a PR. `scripts/reconcile.py`. |
| review | [`de-code-review`](skills/de-code-review/SKILL.md) | Reviews data-engineering changes the way the Claude Code team reviews its own PRs: verify with tools, scale rigor to blast radius, report only real bugs with `file:line` and an `Important` / `Nit` / `Pre-existing` label. |
| ship | [`de-pr`](skills/de-pr/SKILL.md) | PR description built from proof: de-verify block under Testing, risk tier with downstream consumers, revert steps including data. `scripts/pr_body.py`. |
| ship | [`de-backfill`](skills/de-backfill/SKILL.md) | Bounded, idempotent, partition-aware backfill plan with per-batch verify and stop conditions. `scripts/backfill_plan.py` never executes. |
| operate | [`de-incident`](skills/de-incident/SKILL.md) | Layer-by-layer triage from symptom to root cause, containment, and a no-blame writeup that asks which check should have caught it. `scripts/run_results_summary.py`. |
| all | [`lifecycle-router`](skills/lifecycle-router/SKILL.md) | Decides who handles each step: your own skills and agents first, then ECC's, then this plugin's fallbacks. `ask` mode (default) shows ranked options; `auto` decides. |
| learn | [`harness-trim`](skills/harness-trim/SKILL.md) | Keeps ECC installed but disabled as a library and symlinks a daily set chosen from a DE baseline plus your transcript usage. Weekly `SessionEnd` re-evaluation. |

Agent: [`de-lead`](agents/de-lead.md) classifies a task into capabilities, resolves each through
the router, and returns a plan. It never implements.

## How it fits together

```
task ──▶ de-lead agent ──▶ lifecycle-router ──▶ resolve.py ranks what is installed
                                                   │
             ask mode: you pick ◀──────────────────┤   project > user > ECC daily > plugins
             auto mode: top pick, said in one line ◀┘   > built-ins > ECC library > fallback
                                                   │
                            runs the chosen skill/agent; this plugin's own flow only if nothing
                            else fits. harness-trim keeps the ECC daily set matched to usage.
```

Agents live in [`agents/`](agents/): `de-lead` holds the decision flow and returns a plan,
never implements. Capabilities and their fallbacks are declared in
[`lifecycle.json`](lifecycle.json); fallbacks marked `planned` are on the roadmap below.

## Install

This repo is a Claude Code plugin. One line installs every skill in it:

```
/plugin install de-product-lifecycle --marketplace SaiGanesh26/de-product-lifecycle
```

Or from a terminal:

```bash
claude plugin marketplace add SaiGanesh26/de-product-lifecycle
```

```bash
claude plugin install de-product-lifecycle@de-product-lifecycle
```

Skills then show up as `/de-product-lifecycle:de-code-review` (or just ask for a review of a
diff, PR, model, or DAG). Update with `claude plugin update de-product-lifecycle`.

If you also run ECC, trim it to what you use:

```bash
python3 -I ~/.claude/plugins/cache/de-product-lifecycle/de-product-lifecycle/*/skills/harness-trim/scripts/harness_trim.py report
```

Then `apply` instead of `report` to switch to the lean daily set, `library` to get all of ECC back.

Lifecycle mode (ask is the default; `--project` scopes it to one repo):

```bash
python3 -I ~/.claude/plugins/cache/de-product-lifecycle/de-product-lifecycle/*/skills/lifecycle-router/scripts/resolve.py mode auto
```

## Roadmap

All fallbacks declared in `lifecycle.json` are built. Next: evals under `skills/*/evals/` so
each skill is scored against a real diff, model, or incident; a `de-contract` skill for data
contracts and freshness SLAs; and promoting any skill ECC lacks upstream once it has earned
its keep here.

## Contributing

Every change, including ones Claude makes, goes on a `feat-`, `fix-`, or `chore-` branch,
updates this README, passes `claude plugin validate .`, and lands as a PR against `main`
that the owner merges. [`CLAUDE.md`](CLAUDE.md) holds the full conventions.

## Adding a skill

```
.claude-plugin/
├── plugin.json       # plugin name, version, metadata
└── marketplace.json  # lets `/plugin install` find it from the GitHub repo
hooks/hooks.json      # plugin hooks (currently: weekly harness-trim re-evaluation)
lifecycle.json        # capability contract: stage, keywords, known providers, fallback
agents/<name>.md      # agents: decision flows with their own context; preload skills via `skills:`
skills/<skill-name>/
├── SKILL.md          # frontmatter (name, description) + instructions; keep under ~300 lines
├── references/       # longer material the skill points to, loaded only when needed
├── templates/        # files the skill drops into a project (PR templates, config)
└── evals/            # optional test prompts (claude plugin eval layout)
```

Rules of thumb, learned the hard way:

- The `description` is the trigger. Say what the skill does and when to use it, including phrasings that don't name it.
- Explain why each instruction exists. Agents follow reasoning better than shouted rules.
- Prefer verification the agent can run over verification it can assert.
- Keep `SKILL.md` lean; push detail into `references/`.
