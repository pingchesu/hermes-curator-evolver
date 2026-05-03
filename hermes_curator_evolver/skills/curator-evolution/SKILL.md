---
name: curator-evolution
description: Use when interpreting Hermes Curator Evolver evidence reports or deciding whether a skill governance proposal is ready for a later verifier/apply phase.
version: 0.1.0
author: pingchesu
license: MIT
---

# Curator Evolution

Hermes Curator Evolver v0.1 is read-only. Treat all reports as evidence for review, not as instructions to mutate skills.

## Interpretation Checklist

1. Separate evidence from conclusions.
2. Repeated tool errors suggest a possible missing pitfall or verification step in a skill.
3. Repeated `skill_view` usage suggests the skill is active and worth keeping discoverable.
4. A single failure is not enough evidence to rewrite a skill.
5. If the skill was correct but the agent ignored it, prefer improving trigger/description only if repeated.
6. Do not propose delete in v0.1.
7. Do not propose auto-apply without a verifier gate and explicit user approval.

## Safe Next Actions

- Ask for a targeted human review of one skill.
- Draft a proposal with evidence row references.
- Defer embedding/rerank analysis until semantic mode is explicitly enabled in a future release.
