# Core algorithm: evidence, candidate selection, and autorun

This document explains the current `hermes-curator-evolver` algorithm in plain terms, including exactly where embedding and reranking are supported.

## Short answer

| Path | Uses embedding? | Uses reranker? | Can write skills? | Purpose |
| --- | --- | --- | --- | --- |
| `auto-run` / `install-auto` default | No | No | Yes, only append-only low-risk blocks when explicitly enabled | Safe automatic skill improvement with deterministic evidence thresholds. |
| `auto-run --semantic-candidates` | Yes: `Qwen/Qwen3-Embedding-0.6B` | No unless `--rerank-candidates` | Yes, but only after the same write flags | Model-assisted ordering of evidence-eligible skills. |
| `auto-run --semantic-candidates --rerank-candidates` | Yes | Yes: `BAAI/bge-reranker-v2-m3` | Yes, but only after the same write flags | Embedding + reranker ordering of evidence-eligible skills. |
| `candidates --execute-semantic` | Yes: `Qwen/Qwen3-Embedding-0.6B` | No unless `--rerank` | No | Manual/review candidate discovery. |
| `candidates --execute-semantic --rerank` | Yes | Yes: `BAAI/bge-reranker-v2-m3` | No | Better manual/review ranking. |
| `propose --draft-with-model` | Uses Hermes configured chat model | No | No | Draft a reviewable proposal artifact. |
| `apply` | No | No | Yes, after explicit approval/hash/backup gates | Apply reviewed content. |

Default autorun remains model-free. Embedding/rerank autorun is now explicit opt-in and can only reorder candidates that already passed the evidence threshold; model output does not generate write content.

Semantic execution is runtime-guarded for local machines: texts are truncated for candidate ranking (`HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT`, default `512` chars), embedding batches run one at a time, and model runtime device is configurable with `HERMES_CURATOR_EVOLVER_SEMANTIC_DEVICE` (default `auto`; set `cpu` or `cuda` explicitly if needed). If local model execution fails, `auto-run` falls back to deterministic evidence ordering instead of crashing.

## Current autorun algorithm

`auto-run` is implemented in `hermes_curator_evolver/auto_evolve.py`.

### Inputs

- Evidence DB: `~/.hermes/plugins/curator-evolver/data/evidence.sqlite`
- Skills root: default `~/.hermes/skills`
- Lookback window: default `--days 7`
- Candidate cap: default `--max-skills 3`
- Minimum evidence threshold: default `--min-evidence 2`
- Optional candidate ordering: `--semantic-candidates`, `--rerank-candidates`

### Steps

```text
1. Build aggregate evidence report for the lookback window.
2. Read report.summary.skills.
3. Build an evidence-eligible candidate set:
   skill.event_count >= min_evidence.
4. If semantic/rerank is not requested:
   order candidates by deterministic evidence summary order.
5. If semantic/rerank is requested:
   a. Build an evidence query from eligible skill counts and recent evidence rows.
   b. Run embedding candidate search over SKILL.md files.
   c. Optionally run reranker on query/skill pairs.
   d. Keep only skills from the evidence-eligible set.
   e. Use model scores only to reorder those eligible skills.
6. Discover matching SKILL.md files under the skills directory.
7. For each selected skill:
   a. Build a per-skill evidence report.
   b. Read the current SKILL.md.
   c. Generate/update a managed curator-evolver:auto block.
   d. Preserve all existing skill text outside that block.
8. If --apply-low-risk is not set:
   return dry-run plan only.
9. If --apply-low-risk is set but --approve-auto-apply is missing:
   refuse to write.
10. If both write flags are set:
   apply through guarded apply with SHA256 check, backup, optional verify command, and rollback manifest.
```

### Pseudocode

```python
report = build_report(store, days=days)
eligible = [
    row.skill_name
    for row in report.summary.skills
    if row.event_count >= min_evidence
]

if semantic_candidates or rerank_candidates:
    query = build_semantic_query(report, eligible)
    ranked = find_skill_candidates(
        query=query,
        skills_dir=skills_dir,
        semantic=True,
        load_models=True,
        load_reranker=rerank_candidates,
    )
    names = [item.skill_name for item in ranked if item.skill_name in eligible][:max_skills]
    names += [name for name in eligible if name not in names]
else:
    names = eligible

for name in names[:max_skills]:
    skill_file = skill_files.get(name)
    skill_report = build_report(store, days=days, skill=name)
    original = read(skill_file)
    updated = build_low_risk_skill_update(
        skill_name=name,
        skill_text=original,
        summary=skill_report.summary,
        evidence_rows=skill_report.skill_evidence,
    )

    if apply_low_risk and approve_auto_apply:
        apply_guarded_patch(
            target_path=skill_file,
            new_content=updated,
            expected_sha256=sha256_file(skill_file),
            backup_root=backup_dir,
            verify_command=verify_command,
        )
```

## What gets written

Autorun only writes a managed block like this:

```md
<!-- curator-evolver:auto:start -->
## Auto-curated evidence notes

Low-risk append-only auto-curation generated by `hermes-curator-evolver`.
These notes are evidence summaries for future agents; they do not replace human-authored SOPs.

- Skill: `example-skill`
- Generated at: `...`
- Evidence window: last 7 day(s)
- Tool events: ...
- Skill events: ...
- Error-like events: ...

### Recent evidence
- ...

### Agent guidance
- When this skill is relevant, check these observed signals before choosing a workflow.
- Prefer targeted verification over broad retries when similar errors recur.
- If a repeated issue is understood, replace this evidence note with a concise human-readable SOP update.
<!-- curator-evolver:auto:end -->
```

If the block already exists, autorun replaces only that managed block. It does not rewrite the rest of the skill.

## Embedding/rerank autorun choice

### Default model-free timer

```bash
hermes-curator-evolver install-auto --schedule daily --enable
```

Equivalent auto-run:

```bash
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json \
  --apply-low-risk \
  --approve-auto-apply
```

### Semantic/rerank timer

Install optional model dependencies first:

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e "$HOME/.hermes/plugins/curator-evolver[semantic]"
```

Then opt in:

```bash
hermes-curator-evolver install-auto \
  --schedule daily \
  --enable \
  --semantic-candidates \
  --rerank-candidates
```

Equivalent auto-run:

```bash
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json \
  --semantic-candidates \
  --rerank-candidates \
  --apply-low-risk \
  --approve-auto-apply
```

## Where embedding and reranking are used

Semantic ranking is implemented in `hermes_curator_evolver/semantic.py` and reused by both:

1. The advisory `candidates` command.
2. The opt-in `auto-run --semantic-candidates` / `--rerank-candidates` path.

### Plan-only semantic mode for review

```bash
hermes-curator-evolver candidates \
  --query "gateway plugin restart" \
  --skills-dir ~/.hermes/skills \
  --semantic
```

This shows the semantic model plan. It does **not** download or run models.

### Embedding execution

```bash
hermes-curator-evolver candidates \
  --query "gateway plugin restart" \
  --skills-dir ~/.hermes/skills \
  --execute-semantic
```

This loads:

```text
Qwen/Qwen3-Embedding-0.6B
```

through `sentence-transformers` and ranks skills by embedding cosine similarity.

### Embedding + reranker execution

```bash
hermes-curator-evolver candidates \
  --query "gateway plugin restart" \
  --skills-dir ~/.hermes/skills \
  --execute-semantic \
  --rerank
```

This loads:

```text
Qwen/Qwen3-Embedding-0.6B
BAAI/bge-reranker-v2-m3
```

The embedding model finds likely candidates first, then the reranker scores query/skill pairs.

## Safety contract for model-assisted autorun

- Default autorun remains deterministic and model-free.
- `--semantic-candidates` and `--rerank-candidates` are explicit opt-ins.
- Model output can only influence candidate ordering, not write content directly.
- Model-ranked skills must already satisfy `min_evidence`.
- Writes still require `--apply-low-risk --approve-auto-apply`.
- Output includes selection mode, model names, scores, and reasons for each candidate.
- Timer install stays model-free unless the user explicitly opts in.

## Mental model

Think of the current system as two lanes that now meet at the candidate-ordering step:

```text
Lane A — safe automation default
Evidence counts → deterministic candidate ordering → append-only notes → guarded apply

Lane B — model-assisted ordering opt-in
Evidence-eligible candidates → embedding/rerank ordering → append-only notes → guarded apply
```

Models can improve which eligible skill is considered first, but they cannot bypass evidence thresholds or guarded apply.
