---
name: curator-evolution
description: Use when interpreting Hermes Curator Evolver evidence reports, historical session backfill, proposals, verifier results, candidate search, auto-run output, timer installs, or guarded apply manifests.
version: 0.11.0
author: pingchesu
license: MIT
---

# Curator Evolution

Hermes Curator Evolver starts from evidence and keeps mutation guarded. Reports and proposals are review artifacts. `auto-run` can make skills actually improve, but only through low-risk bounded managed blocks, reference spillover for bulky evidence, and guarded apply.

## Interpretation Checklist

1. Separate evidence from conclusions.
2. Repeated tool errors suggest a possible missing pitfall or verification step in a skill.
3. Repeated skill reads suggest the skill is active and worth keeping discoverable.
4. A single failure is not enough evidence to rewrite a skill.
5. If the skill was correct but the agent ignored it, improve triggers/descriptions only when evidence repeats.
6. Candidate search is advisory; embedding/reranker models only find candidates and do not decide edits.
7. `backfill-sessions` can import existing Hermes `session_*.json` transcripts into evidence; it is model-free and does not mutate skills.
8. `auto-run --semantic-candidates` and `--rerank-candidates` are explicit opt-ins that only reorder evidence-eligible candidates.
9. Guarded apply requires approval, backup, verifier/validation pass, and rollback.
10. `auto-run` mutates only when both `--apply-low-risk` and `--approve-auto-apply` are set.
11. Even with write flags, unattended auto-apply writes only local agent-created skills. Official/bundled skills (`.bundled_manifest`), hub-installed skills (`.hub/lock.json`), plugin-provided skills, `skills.external_dirs`, pinned skills, and unknown sources are skipped.
12. Core-name allowlists only operate inside that local agent-created source boundary; they do not override provenance.
13. Size guardrails target a 90k `SKILL.md` soft cap, spill bulky autorun evidence into `references/`, and skip unattended writes when the target skill is already over the 100k hard cap.
14. `install-auto --enable` creates a user systemd timer; remove it with `uninstall-auto` before plugin uninstall.

## Safe Next Actions

- Run `hermes-curator-evolver bootstrap` for the default one-command setup: backfill recent sessions and enable the daily safe autorun timer.
- Run `hermes-curator-evolver bootstrap --semantic` only when the user explicitly wants model-assisted timer candidate ordering.
- Run `hermes-curator-evolver report --days 7` for evidence.
- Run `hermes-curator-evolver backfill-sessions --sessions-dir ~/.hermes/sessions --days 30 --format json` once when existing Hermes sessions should seed evidence.
- Run `hermes-curator-evolver propose --skill <name> --format json` for a dry-run proposal.
- Run `hermes-curator-evolver verify --proposal-file <proposal.json>` before considering apply.
- Use `hermes-curator-evolver candidates --query <text> --skills-dir <dir>` for dependency-free lexical candidate search.
- Use `hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --format json` to preview automatic improvements.
- Use `hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --semantic-candidates --rerank-candidates --format json` to preview model-assisted candidate ordering.
- Use `hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --apply-low-risk --approve-auto-apply` for actual low-risk bounded improvement; only local agent-created skills are writable, bulky evidence can spill to `references/`, and already-over-hard-cap skills are skipped.
- Use `hermes-curator-evolver install-auto --schedule daily --enable` for plug-in daily automation without Hermes core changes.
- Use `hermes-curator-evolver install-auto --schedule daily --enable --semantic-candidates --rerank-candidates` only when the user explicitly wants model-assisted timer candidate ordering.
- Use `hermes-curator-evolver uninstall-auto` to remove the optional timer.
- Use guarded apply only with an exact SHA256 and a reviewed content file.
