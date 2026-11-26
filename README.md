# DE product lifecycle

`de-product-lifecycle` on the marketplace.

A Claude Code plugin that runs the lifecycle of a data product the way a careful data
engineer would: design, build, verify, review, ship, operate, learn. It ships the decision
flow, not just the checklists. An orchestrator agent classifies a task into capabilities, a
router resolves each one to the best tool already installed (yours first, then a generic
harness such as [ECC](https://github.com/affaan-m/ECC), then this plugin's own flows as the
last resort), and every flow ends in something runnable: a reconciliation query, a backfill
plan, a PR body built from proof.

Built from two sources: the Claude Code team's account of how they review code written mostly
by agents, and Felix Rieseberg's argument that a model should never be its own judge. Both are
summarised in [`skills/de-code-review/references/sources.md`](skills/de-code-review/references/sources.md).

## What is in the plugin

| Part | Where | Role |
|---|---|---|
| Capability contract | [`lifecycle.json`](lifecycle.json) | Thirteen capabilities across the stages, each with keywords, known external providers, and this plugin's fallback. |
| Orchestrator agent | [`agents/de-lead.md`](agents/de-lead.md) | Reads the task, picks the capabilities, resolves each through the router, returns a plan. Never implements. |
| Router | [`skills/lifecycle-router`](skills/lifecycle-router/SKILL.md) | Ranks what is installed on the machine by location and lets the user pick (`ask`, default) or decides (`auto`). |
| Stage skills | [`skills/de-*`](skills/) | The fallback flows, one per capability, each with a stdlib Python script that does the deterministic part. |
| Harness trim | [`skills/harness-trim`](skills/harness-trim/SKILL.md) | Keeps a large generic plugin like ECC as a disabled library and loads only the daily set your usage earns. |
| Hook | [`hooks/hooks.json`](hooks/hooks.json) | One `SessionEnd` hook that re-evaluates the daily set weekly. Opt-in, silent. |

## How a task flows

```
task ──▶ de-lead agent ──▶ lifecycle-router ──▶ resolve.py ranks what is installed
                                                   │
             ask mode: you pick ◀──────────────────┤   project > user > ECC daily > plugins
             auto mode: top pick, said in one line ◀┘   > built-ins > ECC library > fallback
                                                   │
                            runs the chosen skill or agent; this plugin's own flow only if
                            nothing else fits. harness-trim keeps the ECC daily set honest.
```

Precedence is by location, so your own skills and agents outrank everything else with no
configuration. Each pick is recorded; after three identical picks for a capability the router
suggests pinning it, so `ask` converges toward `auto` on its own.

## Stage skills

Each skill ends in something runnable and says when the user's own tools or ECC's should be
used instead.

| Stage | Skill | What it does |
|---|---|---|
| design | [`de-impact`](skills/de-impact/SKILL.md) | Blast radius of a model or column change from the dbt manifest and BI layer, as a contract-break table. Extends ECC `change-impact`. `scripts/dbt_impact.py`. |
| design | [`de-model`](skills/de-model/SKILL.md) | Decision checklist (grain, materialization, lookback, partition, SCD) then scaffolds a dbt model with schema tests and runs it. `scripts/scaffold_model.py`. |
| verify | [`de-verify`](skills/de-verify/SKILL.md) | Before/after reconciliation of a changed table: counts, grain uniqueness, nulls, sums, bounds, one-sided keys. Flags what moved; exit 1 gates a PR. `scripts/reconcile.py`. |
| review | [`de-code-review`](skills/de-code-review/SKILL.md) | Reviews data-engineering changes the way the Claude Code team reviews its own PRs: verify with tools, scale rigor to blast radius, report only real bugs as three-sentence comments with `file:line`. Blocking findings are prefixed `Needs fix`, `Needs change`, or `Needs human`; non-blocking ones `Question`, `Suggestion`, `Nit`, or `Pre-existing`. |
| ship | [`de-pr`](skills/de-pr/SKILL.md) | PR description built from proof: de-verify block under Testing, risk tier with downstream consumers, revert steps including data. `scripts/pr_body.py`. |
| ship | [`de-backfill`](skills/de-backfill/SKILL.md) | Bounded, idempotent, partition-aware backfill plan with per-batch verify and stop conditions. `scripts/backfill_plan.py` never executes. |
| operate | [`de-incident`](skills/de-incident/SKILL.md) | Layer-by-layer triage from symptom to root cause, containment, and a no-blame writeup that asks which check should have caught it. `scripts/run_results_summary.py`. |
| all | [`lifecycle-router`](skills/lifecycle-router/SKILL.md) | Decides who handles each step: your own skills and agents first, then ECC's, then this plugin's fallbacks. |
| learn | [`harness-trim`](skills/harness-trim/SKILL.md) | ECC as a disabled library plus a daily set chosen from a DE baseline and your transcript usage. |

## Install

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

Skills appear as `/de-product-lifecycle:<name>`; the agent as `de-product-lifecycle:de-lead`.
Most of the time you just describe the task and the descriptions do the matching. Update with
`claude plugin update de-product-lifecycle`.

## Configure

Scripts live under the installed copy; `<plugin>` below is
`~/.claude/plugins/cache/de-product-lifecycle/de-product-lifecycle/<version>`.

Lifecycle mode (`ask` is the default; `--project` scopes it to one repo):

```bash
python3 -I <plugin>/skills/lifecycle-router/scripts/resolve.py mode auto
```

Pin a provider for one capability, or see what has been decided so far:

```bash
python3 -I <plugin>/skills/lifecycle-router/scripts/resolve.py override review.code agent:code-reviewer
```

```bash
python3 -I <plugin>/skills/lifecycle-router/scripts/resolve.py status
```

## Working beside ECC

ECC is the generic harness layer: planning, TDD, verification loops, security scans, memory.
This plugin adds only what is specific to pipelines, warehouses, dbt, Spark, and
orchestration, and it never duplicates an ECC skill it can reference. Because ECC's 400+ skill
descriptions cost about 35k tokens per session, the recommended setup is ECC installed but
disabled, with `harness-trim` linking a daily set:

```bash
python3 -I <plugin>/skills/harness-trim/scripts/harness_trim.py report
```

Then `apply` to switch to the daily set, `library` to get all of ECC back for a session,
`add <name> --pin` to keep one more. ECC skills that are not loaded still appear in the
router's options, with the command to load them.

## Roadmap

All fallbacks declared in `lifecycle.json` are built. Next: evals under `skills/*/evals/` so
each skill is scored against a real diff, model, or incident; a `de-contract` skill for data
contracts and freshness SLAs; and promoting any skill ECC lacks upstream once it has earned
its keep here.

## Contributing

Every change, including ones Claude makes, goes on a `feat-`, `fix-`, or `chore-` branch,
updates this README, passes `claude plugin validate .`, and lands as a PR against `main`
that the owner merges. [`CLAUDE.md`](CLAUDE.md) holds the full conventions.

## Repository layout and extending it

The plugin is not limited to skills. Anything Claude Code can load from a plugin has a home
here, and each kind joins the lifecycle the same way: declare the capability it serves in
`lifecycle.json`, build the component, keep the README table current.

```
.claude-plugin/
├── plugin.json       # plugin identity and version (bump with marketplace.json)
└── marketplace.json  # lets `/plugin install` find it from the GitHub repo
lifecycle.json        # capability contract: stage, keywords, known providers, fallback
agents/<name>.md      # decision flows with their own context window; preload skills via `skills:`
skills/<name>/        # instructions + scripts/ templates/ references/ evals/
hooks/hooks.json      # lifecycle hooks (SessionStart/End, Pre/PostToolUse, Stop); fast, silent, opt-in
commands/<name>.md    # slash-command entry points when a flow needs explicit invocation
workflows/<name>.js   # multi-agent loops (plan -> build -> verify -> review) for the Workflow tool
.mcp.json             # MCP servers the plugin needs (warehouse, orchestrator, lineage APIs)
```

| Kind | Use it for | Joins the lifecycle by |
|---|---|---|
| Skill | A flow the user steers in the main context; the deterministic part in `scripts/`. | Named as a `fallback` or `known_provider` in `lifecycle.json`. |
| Agent | A decision flow or review that benefits from a fresh context and its own tool list. | Same; `de-lead` is the orchestrator, stage agents are providers. |
| Hook | Something that must happen on every session or tool call without being asked. | Declared in `hooks/hooks.json`; must be a no-op until the user opts in. |
| Loop or workflow | A bounded multi-agent cycle, e.g. author/reviewer convergence with a cap on rounds. | Declared in `lifecycle.json` as a provider for the capability it automates. |
| Command | A named entry point when description matching is not enough. | Thin wrapper that invokes the skill or agent. |
| MCP server | Live access to a warehouse, orchestrator, or lineage tool the flows should query. | Referenced by the skills that need it; never required for install. |

To add a capability: declare it in `lifecycle.json` (with `"planned": true` on the fallback
until it exists), then build the component and drop the flag. The router reports planned
fallbacks honestly in the meantime.

Rules of thumb, learned the hard way:

- The `description` is the trigger. Say what the component does and when to use it, including phrasings that don't name it.
- Explain why each instruction exists. Agents follow reasoning better than shouted rules.
- Prefer verification the agent can run over verification it can assert.
- Keep instructions lean; push detail into `references/` and the deterministic part into `scripts/`.
- Reuse before building: if ECC or the user already has it, reference it as a provider.
