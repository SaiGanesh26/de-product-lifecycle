# de-product-lifecycle

Skills I build or adopt as a data engineer, covering the lifecycle of a data product:
design, build, review, ship, operate. Each skill is a folder with a `SKILL.md` that an
AI coding agent (Claude Code, or anything that reads the Agent Skills format) loads when
the task matches its description.

## Skills

| Skill | What it does |
|---|---|
| [`de-code-review`](skills/de-code-review/SKILL.md) | Reviews data-engineering changes (SQL, dbt, Spark, DAGs, Python ETL, migrations, infra) the way the Claude Code team reviews its own PRs: verify with tools, scale rigor to blast radius, report only real bugs with `file:line` and an `Important` / `Nit` / `Pre-existing` label. |

## Installing a skill

Personal, available in every project:

```bash
ln -s "$(pwd)/skills/de-code-review" ~/.claude/skills/de-code-review
```

Per project, committed with the repo:

```bash
mkdir -p .claude/skills && cp -r /path/to/de-product-lifecycle/skills/de-code-review .claude/skills/
```

Invoke with `/de-code-review`, or just ask for a review of a diff, PR, model, or DAG.

## Adding a skill

```
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
