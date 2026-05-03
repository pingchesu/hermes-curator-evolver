---
name: curator-evolution
description: Use when interpreting Hermes Curator Evolver evidence reports, proposals, verifier results, candidate search, or guarded apply manifests.
version: 0.5.0
author: pingchesu
license: MIT
---

# Curator Evolution

Hermes Curator Evolver starts from evidence and keeps mutation guarded. Treat reports and proposals as review artifacts until the verifier passes and a human explicitly approves apply.

## Interpretation Checklist

1. Separate evidence from conclusions.
2. Repeated tool errors suggest a possible missing pitfall or verification step in a skill.
3. Repeated skill reads suggest the skill is active and worth keeping discoverable.
4. A single failure is not enough evidence to rewrite a skill.
5. If the skill was correct but the agent ignored it, improve triggers/descriptions only when evidence repeats.
6. Candidate search is advisory; embedding/reranker models only find candidates and do not decide edits.
7. Guarded apply requires approval, backup, verifier/validation pass, and rollback.

## Safe Next Actions

- Run `hermes-curator-evolver report --days 7` for evidence.
- Run `hermes-curator-evolver propose --skill <name> --format json` for a dry-run proposal.
- Run `hermes-curator-evolver verify --proposal-file <proposal.json>` before considering apply.
- Use `hermes-curator-evolver candidates --query <text> --skills-dir <dir>` for dependency-free lexical candidate search.
- Use guarded apply only with an exact SHA256 and a reviewed content file.
