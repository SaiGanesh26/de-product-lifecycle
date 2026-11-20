# Sources

Condensed notes from the two pieces this skill was built on, kept so the reasoning behind
the instructions stays inspectable. Both were read in full on 2026-11-09.

## "How the Claude Code team does code review", Addy Osmani (via x.com, 2026-10-26)

Post: https://x.com/addyosmani/status/2114604912520921136
Article: https://x.com/i/article/2114435487905808384
Original it rewrites: https://claude.dev/blog/solving-code-review-at-anthropic/

Context: Claude writes about 90% of Claude Code's code. Merged PRs more than doubled over
a quarter while the revert rate fell by more than 40%. Review was not dropped; the reading
was automated and the human part was retuned to save human time.

Ideas carried into the skill:

- Review's two purposes: catch bugs before they ship, and build shared understanding.
  The right question is "what could go wrong, and which check catches it", not "did
  someone read it".
- Human time is a two-sided cost: reviewing, and fixing what bad code introduced.
  Reverts and incidents are the guardrail metrics.
- Layered checks: pre-PR verification by the author's agent (runnable proof, not a
  claim), AI review on every PR against the whole codebase and the stated intent, a
  security review that can block, automated blocking checks, human approval scaled by
  risk, merge queue plus flags plus staged rollout, fast rollback.
- Findings are vetted by parallel agents plus a voting step that drops false positives.
  Style, diagnostics, and cleanup findings are filtered out. Labels: Important, Nit,
  Pre-existing. Every finding is fixed or resolved with a reason.
- Risk tier comes from the change, not the author. Sensitive paths (billing, auth, CI
  workflows, installers) always need a human. Agent approvals never count as human
  approvals. An approval covers one commit.
- Nits are costlier with agent authors: each one is a commit and a review cycle. Two
  agents once cycled 50+ times overnight. Fixes: cap cycles at three then rethink,
  re-review only the new diff after the first round, name the bug class, never
  re-report.
- About 59% of what the reviewer flagged was pre-existing code, hence the label.
- Incidents are the eval set. Rescore the reviewer whenever prompts, tools, or model
  change. Measure noise by how humans respond to comments.
- Humans stay essential for: whether to build it, dangerous code, architecture,
  verifying proofs, and taking responsibility. "You land it, you own it."
- Project setup: a short CLAUDE.md (stack, conventions, goals, non-goals), a REVIEW.md
  (define failure, limit nitpicking, ignore paths, require file:line references, require
  a summary with a finding count and an explicit "no issues"), a PR template with
  Testing / Risk / How to revert.
- When the reviewer misses something, ask what was missing from its context and encode
  it as a CLAUDE.md line, a skill, or a check.

## "How to be more ambitious: a tutorial for humans with models", Felix Rieseberg (2026-10-13)

https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/

Not about code review; about getting more from models along four axes: Speed, Altitude,
Depth, Range. The parts that shaped this skill:

- **Do not let the model judge itself.** Insist on an outside judge, ideally a tool the
  model can run for immediate feedback. This became Step 2 (verification ladder) and
  Step 4 (fresh-context second reviewer, no shared findings).
- **Depth over size:** "a deeper version of this task, not a bigger one". Use the
  instruments a top practitioner would use (run the query, read the plan, diff the
  output), not a markdown table of impressions. Name what a top professional would do
  that nobody asked for; name the rawest starting material; name what, other than the
  model or the user, would show the result is right.
- **Challenge what you know.** Give the model raw data and have it adversarially check
  assumptions. This became Step 3 and the rule to open upstream models rather than trust
  the PR description.
- **Altitude: the goal beyond the goal.** Ask what should happen next and what outcome
  the task serves. This became the "goal beyond the goal" check in Step 1.
- **Do, don't role-play.** "Do what a short seller does", not "write like one". Hence
  the skill asks for actions (run, diff, trace) rather than a persona.
- **Durable workflows.** Give the model the access it needs (crash reports, commit
  mapping, machines to reproduce on) so it can independently reproduce and verify, then
  ask for the standing outcome. Translated to data work: a reviewer that can run dbt,
  query the warehouse, and trigger a dev DAG is worth far more than one that reads SQL.
- **Unreasonable goals framed as reasonable.** Specific hard goals outperform "do your
  best" (Locke and Latham). The skill's standard is "every Important finding has a
  command behind it", not "be thorough".
