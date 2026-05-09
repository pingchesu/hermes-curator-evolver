# Reddit and community launch notes

This project should be shared as a technical discussion about agent skill governance, not as a generic repo drop.

The target subreddit list below intentionally uses the URLs from the launch plan. `r/ArtificialInteligence` is spelled that way because it is the community URL being targeted; do not silently "fix" it to a different subreddit without checking the intended audience.

## Launch cadence

1. Post first to `r/hermesagent` because the project is directly Hermes-specific.
2. Wait 2-4 days, respond to comments, and fold useful feedback into docs/issues.
3. Post to `r/ArtificialInteligence` with a broader "agent skills need safe maintenance" framing.
4. Post to `r/MachineLearning` only after adding an evaluation note, technical report, or comparison against prior work such as SkillClaw.

Avoid posting identical copy across communities. Each post should be rewritten for that community's norms.

## r/hermesagent draft

**Title**

```text
I built a local-first Hermes plugin that evolves skills from session evidence, with dry-runs and rollback
```

**Body**

```markdown
Hi everyone — I’m the author of this open-source Hermes Agent plugin:

https://github.com/pingchesu/hermes-curator-evolver

The goal is to help Hermes skills improve from actual usage without blindly rewriting your skill library.

What it does:

- collects local Hermes session/tool-call evidence
- backfills existing `session_*.json` history
- ranks candidate skills for improvement
- generates dry-run proposals and evidence reports
- applies only guarded, append-only updates in the low-risk path
- skips official, hub-installed, plugin-provided, external, pinned, and unknown-source skills
- creates backups and rollback manifests
- supports optional semantic search/rerank, but only when explicitly enabled

Why I built it: I use Hermes skills heavily, and noticed they can become stale unless they are manually curated. I wanted something closer to evidence-driven maintenance than "an LLM randomly edits my skill files."

The default path is local-first and model-free. Semantic search is explicit opt-in.

I’d love feedback from Hermes users on:

1. Is the safety model strict enough?
2. Should proposals be more PR-like diffs instead of append-only notes?
3. What evidence signals should count?
4. What would make you trust automated skill maintenance?

Repo:
https://github.com/pingchesu/hermes-curator-evolver
```

## r/ArtificialInteligence draft

**Title**

```text
I built a local-first system for evidence-driven skill evolution in AI agents
```

**Body**

```markdown
I’m the author of an open-source project called Hermes Curator Evolver:

https://github.com/pingchesu/hermes-curator-evolver

It started from a practical problem I ran into with AI agents: once an agent has reusable "skills" or procedural memory, those skills can become stale. But letting an LLM freely rewrite its own skills is also risky.

So I built a local-first plugin for Hermes Agent that treats skill updates more like a guarded maintenance workflow:

- collect session/tool-call evidence locally
- rank which skills might need improvement
- generate reviewable proposals
- apply only low-risk append-only notes by default
- skip official, external, plugin-provided, pinned, or unknown-source skills
- create backups and rollback manifests
- keep semantic search/reranking explicit opt-in

The design goal is not "fully autonomous self-improvement." It is closer to evidence-driven curation with hard safety boundaries.

The project is inspired by SkillClaw, but adapted to Hermes Agent’s local plugin/skill system.

I’m curious how others think about this problem:

- Should agent skills be allowed to evolve automatically at all?
- What evidence should count as a valid signal?
- Is append-only safer than direct rewrite?
- What rollback or audit trail would make this trustworthy?
```

## r/MachineLearning draft, only after more evaluation

**Title**

```text
[D] Evidence-driven skill evolution for AI agents: how should procedural memory update safely?
```

**Body direction**

Use this community for a discussion or project post only after adding at least one of:

- a small evaluation of skill-update quality (see the feedback question in the README for possible evaluation criteria),
- a comparison with SkillClaw or related agent-memory work,
- a failure taxonomy,
- an ablation of lexical vs semantic/reranked candidate selection,
- a technical report explaining what would count as success.

Then frame the post around evaluation and safety questions, not promotion.

## Anti-spam checklist

- Disclose author affiliation in the first paragraph.
- Do not ask for stars, upvotes, subscribers, or waitlist signups.
- Include enough technical detail that the post stands on its own if the link is ignored.
- Ask for specific feedback, not generic "thoughts?".
- Do not cross-post the same text on the same day.
