# Reddit launch kit

This is a practical launch kit for sharing Hermes Curator Evolver without overselling it. Adapt the wording to your own voice and each subreddit's rules before posting.

## Positioning

**One-line description**

> Hermes Curator Evolver is a local-first Hermes Agent plugin that turns real session history into evidence-backed skill maintenance, with dry-run proposals, backups, rollback, and provenance-safe append-only autorun.

**What makes it different**

- It is built around real agent usage evidence: skill loads, tool calls, session endings, and optional historical `session_*.json` backfill.
- It is conservative by default: reports/proposals are dry-run, model execution is opt-in, and unattended writes are limited to managed append-only blocks.
- It protects shared or upstream-owned skills: bundled, hub-installed, plugin-provided, external-dir, pinned, and unknown-source skills are skipped for unattended writes.
- It treats embeddings/rerankers as ranking aids, not as edit authority. Default autorun remains deterministic and model-free.

**What not to claim**

- Do not call it general self-improving AI.
- Do not imply it rewrites arbitrary skills autonomously.
- Do not imply it replaces Hermes Agent's official curator.
- Do not claim benchmark wins unless you add reproducible numbers later.

## Suggested titles

### r/hermesagent

- I built a local-first Hermes plugin that lets skills improve from real session evidence
- Hermes Curator Evolver: session evidence, safe skill notes, rollback, and optional semantic ranking
- Looking for feedback: evidence-driven skill maintenance for Hermes Agent

### r/ArtificialInteligence

Note: this heading intentionally matches the target subreddit URL supplied for launch (`reddit.com/r/ArtificialInteligence/`). If you decide to target a differently spelled AI subreddit, update this kit before posting.

- I built a conservative feedback loop for agent skills using session evidence
- Local-first skill evolution for AI agents: evidence in, guarded updates out
- Experiment: making agent instructions maintain themselves without letting them rewrite everything

### r/MachineLearning

- Project: evidence-driven maintenance for agent skills, inspired by SkillClaw but local-first for Hermes
- A practical plugin for session-trajectory-based skill maintenance in Hermes Agent
- From agent trajectories to guarded skill updates: a small Hermes Agent plugin

## Post draft: r/hermesagent

Hi everyone — I built **Hermes Curator Evolver**, a local-first plugin for Hermes Agent that helps skills improve from actual usage evidence.

Repo: https://github.com/pingchesu/hermes-curator-evolver

The problem I wanted to solve: Hermes skills become operational memory, but maintenance is still manual. After a few weeks, you get stale commands, missing caveats, duplicated workflows, and useful lessons trapped in session logs.

What the plugin does:

- records compact local evidence from Hermes sessions/tool calls/skill usage;
- can backfill old `session_*.json` transcripts;
- produces reports and dry-run proposals before edits;
- optionally uses Qwen embeddings + bge reranking for mixed-language candidate ordering;
- supports guarded apply with SHA checks, backups, validation, and rollback;
- can run daily low-risk autorun, but only writes managed append-only notes to local agent-created skills.

The safety boundary is the part I care most about: official/bundled, hub-installed, plugin-provided, `skills.external_dirs`, pinned, and unknown-source skills are skipped for unattended writes. Semantic mode is explicit opt-in and only reorders evidence-eligible candidates.

Quick start:

```bash
hermes plugins install pingchesu/hermes-curator-evolver --enable
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e ~/.hermes/plugins/curator-evolver
hermes-curator-evolver bootstrap
```

I'd love feedback on the workflow and especially the guardrails. Is this the right safety boundary for skill evolution in Hermes?

## Post draft: r/ArtificialInteligence

_Target subreddit spelling intentionally follows the supplied launch URL._

I built a small open-source plugin around a problem I keep hitting with coding/ops agents: they can follow reusable instructions, but the instructions decay unless someone manually reviews old sessions and patches the right files.

**Hermes Curator Evolver** turns Hermes Agent session history into evidence-backed skill maintenance.

Repo: https://github.com/pingchesu/hermes-curator-evolver

The design is intentionally conservative:

- local SQLite evidence store;
- reports and proposals are dry-run by default;
- model use is optional, not required;
- embeddings/rerankers can help order candidate skills, but do not decide edits;
- apply requires approval/hash/backup/rollback gates;
- daily autorun is limited to append-only managed notes on local agent-created skills.

This is not an attempt to make an agent freely rewrite its own system prompt. It is closer to a maintenance loop: session evidence in, reviewable skill updates out.

I'm curious how others think about safe "self-improvement" boundaries for agents. Should this kind of system be allowed to edit prompts/skills at all, or should it only produce PR-style proposals?

## Post draft: r/MachineLearning

Project: **Hermes Curator Evolver** — evidence-driven skill maintenance for Hermes Agent, inspired by SkillClaw's idea of learning from session trajectories.

Repo: https://github.com/pingchesu/hermes-curator-evolver

The current implementation is pragmatic rather than benchmark-driven. It collects local session/tool/skill evidence, can backfill historical Hermes transcripts, ranks candidate skills lexically by default, and optionally uses `Qwen/Qwen3-Embedding-0.6B` plus `BAAI/bge-reranker-v2-m3` for candidate ordering.

Important boundary: model output does not directly mutate skills. The default path is model-free; semantic/rerank is explicit opt-in and only reorders already evidence-eligible skills. Writes go through dry-run proposals, verifier gates, expected-SHA checks, backups, validation commands, and rollback. Unattended autorun is restricted to managed append-only notes on local agent-created skills.

I would especially appreciate feedback on:

1. whether session-trajectory evidence is enough signal for maintaining agent skills;
2. how to evaluate improvements without encouraging prompt overfitting;
3. where the right safety boundary should be between proposal generation and automatic edits.

## Comment follow-ups

Use these when someone asks for detail.

### Why not just let an LLM rewrite the skill?

Because the failure mode is too broad. This plugin separates evidence collection, candidate ranking, proposal drafting, verification, and apply. The default unattended path can only update a managed append-only block, and only for local agent-created skills.

### What is stored?

A local SQLite database with compact evidence about sessions, tool calls, skill usage, and session completions. It can also import old Hermes `session_*.json` files. It does not require a remote service.

### Does it download models?

No by default. Semantic candidate ranking is explicit opt-in. Default report/proposal/autorun paths are model-free unless you choose the model-assisted flags.

### Does it replace Hermes curator?

No. It is a plugin layer around evidence and guarded skill maintenance. It does not patch Hermes core.

## Disclosure checklist

Before posting:

- Mention that you are the author/maintainer.
- Keep the title descriptive, not clickbait.
- Link to the repo once in the body, not repeatedly.
- Ask for specific feedback rather than only asking for stars.
- Read subreddit self-promotion rules and wait between posts instead of blasting all communities at once.
