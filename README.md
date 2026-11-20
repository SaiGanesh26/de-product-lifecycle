# de-product-lifecycle

Skills I build or adopt as a data engineer, covering the lifecycle of a data product:
design, build, review, ship, operate. Each skill is a folder with a `SKILL.md` that an
AI coding agent (Claude Code, or anything that reads the Agent Skills format) loads when
the task matches its description.

## Skills

| Skill | What it does |
|---|---|
| [`de-code-review`](skills/de-code-review/SKILL.md) | Reviews data-engineering changes (SQL, dbt, Spark, DAGs, Python ETL, migrations, infra) the way the Claude Code team reviews its own PRs: verify with tools, scale rigor to blast radius, report only real bugs with `file:line` and an `Important` / `Nit` / `Pre-existing` label. |

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

It is meant to sit beside a generic harness such as [ECC](https://github.com/affaan-m/ECC),
which covers planning, TDD, verification loops, security scans, and memory. This plugin
adds only what is specific to data engineering.

## Adding a skill

```
.claude-plugin/
├── plugin.json       # plugin name, version, metadata
└── marketplace.json  # lets `/plugin install` find it from the GitHub repo
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
