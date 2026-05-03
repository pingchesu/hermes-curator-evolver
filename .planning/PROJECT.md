# Hermes Curator Evolver

## What This Is

Hermes Curator Evolver is a standalone Hermes Agent plugin that adds read-only, evidence-driven skill governance around the official `hermes curator`. It observes Hermes sessions, tool usage, and skill interactions to produce actionable curator evidence reports without monkeypatching or replacing the official curator.

## Core Value

Give Hermes users grounded evidence for improving skills before any automated skill mutation is allowed.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Build a v0.1 Hermes plugin that can be installed and enabled without modifying Hermes core.
- [ ] Capture session/tool/skill evidence through safe observer hooks.
- [ ] Provide CLI/tool/slash-command reports that are read-only by default.
- [ ] Preserve official curator safety boundaries: no delete, no auto-apply, no mutation in v0.1.

### Out of Scope

- Automatic skill mutation — v0.1 is evidence/report only to avoid unsafe edits.
- Embedding/rerank model downloads — defer to later semantic candidate-generation phase.
- Official Hermes core PR — plugin-first path is intentional to avoid waiting on upstream approval.

## Context

- User wants to develop this with `/gsd` style and publish under `pingchesu/hermes-curator-evolver`.
- Prior research found current official curator is mostly lifecycle + LLM umbrella cleanup, not evidence-driven session evolution.
- SkillClaw provides useful ideas: session evidence, action taxonomy, verifier gates, versioned registry, and semantic candidate generation as advisory signal.
- Hermes plugins are opt-in and can register hooks, tools, CLI commands, slash commands, and namespaced skills.

## Constraints

- **Safety**: v0.1 must be read-only and must not call `skill_manage` or write into `~/.hermes/skills`.
- **Compatibility**: Use Python stdlib where practical; avoid model dependencies in the first version.
- **Hermes Integration**: Plugin should work as a user directory plugin and as a pip entry-point plugin.
- **Evidence Quality**: Reports must distinguish observed evidence from proposed future actions.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Plugin-first instead of upstream curator patch | Avoid upstream review delay and core monkeypatch risk | — Pending |
| v0.1 is read-only evidence/report | Safe first release and easy to validate live | — Pending |
| SQLite storage under Hermes plugin data dir | Lightweight, local, inspectable, no vector DB required | — Pending |
| CLI name `hermes curator-evolver` | Avoid collision with official `hermes curator` | — Pending |

---
*Last updated: 2026-05-03 after project initialization*
