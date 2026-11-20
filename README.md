# de-product-lifecycle

Skills I build or adopt as a data engineer, covering the lifecycle of a data product:
design, build, review, ship, operate. Each skill is a folder with a `SKILL.md` that an
AI coding agent (Claude Code, or anything that reads the Agent Skills format) loads when
the task matches its description.

## Skills

| Skill | What it does |
|---|---|
| [`de-code-review`](skills/de-code-review/SKILL.md) | Reviews data-engineering changes (SQL, dbt, Spark, DAGs, Python ETL, migrations, infra) the way the Claude Code team reviews its own PRs: verify with tools, scale rigor to blast radius, report only real bugs with `file:line` and an `Important` / `Nit` / `Pre-existing` label. |
| [`harness-trim`](skills/harness-trim/SKILL.md) | Keeps sessions lean next to a big harness like ECC: the plugin stays installed but disabled as a library, and a daily set of its skills and agents is symlinked in, chosen from a DE baseline plus what your own transcripts show you invoke. Re-evaluates weekly via a `SessionEnd` hook. |
| [`lifecycle-router`](skills/lifecycle-router/SKILL.md) | Decides who handles each step: your own skills and agents first, then ECC's, then this plugin's fallbacks. In `ask` mode (default) you pick from the ranked options; `auto` mode decides by precedence. Contract in [`lifecycle.json`](lifecycle.json). |

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

Fallbacks declared in `lifecycle.json` but not built yet, in build order: `de-verify`
(before/after reconciliation), `de-pr`, `de-model`, `de-impact`, `de-backfill`, `de-incident`.
ECC already covers generic impact analysis (`change-impact`) and GitHub operations
(`github-ops`), so `de-impact` and `de-pr` will be thin DE wrappers.

It is meant to sit beside a generic harness such as [ECC](https://github.com/affaan-m/ECC),
which covers planning, TDD, verification loops, security scans, and memory. This plugin
adds only what is specific to data engineering.

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
