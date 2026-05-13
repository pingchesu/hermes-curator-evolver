# Core algorithm: evidence, candidate selection, and autorun

This document explains the current `hermes-curator-evolver` algorithm in plain terms, including exactly where embedding and reranking are supported.

For the clean-room rationale on **why HyperAgents is not a runtime dependency**, and the precise scope of the multi-variant candidate evaluation and staged verifier gate documented below, see [hyperagents-design-notes.md](hyperagents-design-notes.md).

## Short answer

| Path | Uses embedding? | Uses reranker? | Can write skills? | Purpose |
| --- | --- | --- | --- | --- |
| `bootstrap` | No by default; yes with `--semantic` | No by default; yes with `--semantic` | Installs the timer; the timer can write only low-risk local-agent-created skill notes | One-command setup: backfill sessions + install/enable autorun. |
| `backfill-sessions` | No | No | No | Import existing Hermes `session_*.json` transcripts into evidence.sqlite so prior history can inform reports/autorun. |
| `auto-run` / `install-auto` default | No | No | Yes, only bounded low-risk blocks for local agent-created skills when explicitly enabled | Safe automatic skill improvement with deterministic evidence thresholds, provenance write protection, and size guardrails. |
| `auto-run --semantic-candidates` | Yes: `Qwen/Qwen3-Embedding-0.6B` | No unless `--rerank-candidates` | Yes, but only after the same write flags and local-agent-created source gate | Model-assisted ordering of evidence-eligible skills. |
| `auto-run --semantic-candidates --rerank-candidates` | Yes | Yes: `BAAI/bge-reranker-v2-m3` | Yes, but only after the same write flags and local-agent-created source gate | Embedding + reranker ordering of evidence-eligible skills. |
| `candidates --execute-semantic` | Yes: `Qwen/Qwen3-Embedding-0.6B` | No unless `--rerank` | No | Manual/review candidate discovery. |
| `candidates --execute-semantic --rerank` | Yes | Yes: `BAAI/bge-reranker-v2-m3` | No | Better manual/review ranking. |
| `propose --draft-with-model` | Uses Hermes configured chat model | No | No | Draft a reviewable proposal artifact. |
| `apply` | No | No | Yes, after explicit approval/hash/backup gates | Apply reviewed content. |

Default autorun remains model-free. Embedding/rerank autorun is explicit opt-in and can only reorder candidates that already passed the evidence threshold; model output does not generate write content. Unattended apply is provenance-safe by default: only local agent-created skills are writable. Official/bundled, hub-installed, plugin-provided, `skills.external_dirs`, pinned, unknown sources, and already-over-hard-cap skills may be proposed in dry-run output, but are skipped before write.

Semantic execution is runtime-guarded for local machines: texts are truncated for candidate ranking (`HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT`, default `512` chars), embedding batches run one at a time, and model runtime device is configurable with `HERMES_CURATOR_EVOLVER_SEMANTIC_DEVICE` (default `auto`; set `cpu` or `cuda` explicitly if needed). If local model execution fails, `auto-run` falls back to deterministic evidence ordering instead of crashing.

## Historical session backfill algorithm

`backfill-sessions` is implemented in `hermes_curator_evolver/backfill.py` and fills the same evidence store used by reports and autorun.

```text
1. Read newest `session_*.json` files from `--sessions-dir`.
2. Keep files inside the `--days` lookback window; optionally stop at `--limit` newest files.
3. For each session:
   a. Use `session_id`, `session_start`, `model`, and `platform` from the transcript.
   b. Import assistant `tool_calls` with matching `tool` responses when available.
   c. Import user → assistant text turns for compact context evidence.
   d. Import one session completion marker.
4. Skip duplicate tool/turn/session signatures so repeated backfill runs are safe.
5. Return counts; no skills are changed.
```

Backfill is intentionally model-free. It does not infer missing tool calls from prose; it only records evidence that is present in the Hermes session JSON structure. After backfill, `report` and `auto-run` see the imported historical evidence through normal SQLite queries.

## Current autorun algorithm

`auto-run` is implemented in `hermes_curator_evolver/auto_evolve.py`.

### Inputs

- Evidence DB: `~/.hermes/plugins/curator-evolver/data/evidence.sqlite`
- Optional historical source: `~/.hermes/sessions/session_*.json` imported with `backfill-sessions`
- Skills root: default `~/.hermes/skills`
- Lookback window: default `--days 7`
- Optional bootstrap wrapper: `bootstrap`, `bootstrap --semantic`
- Candidate cap: default `--max-skills 3`
- Minimum evidence threshold: default `--min-evidence 2`
- Size guardrails: target a 90k `SKILL.md` soft cap; skip unattended updates when the target `SKILL.md` already exceeds the 100k hard cap
- Optional candidate ordering: `--semantic-candidates`, `--rerank-candidates`
- Auto-apply policy: provenance gate writes only local agent-created skills; `--protect-core-skills` default on adds an extra name-based guard; `--allow-auto-apply-skill <glob>` and `--block-auto-apply-skill <glob>` operate inside that provenance boundary

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
6. Discover matching SKILL.md files under the skills directory and classify source provenance.
7. For each selected skill:
   a. Read the current SKILL.md.
   b. Skip pinned skills.
   c. In dry-run, still plan protected sources for review visibility.
   d. In approved auto-apply mode, skip any source other than `local-agent-created`: bundled/official, hub-installed, plugin-provided, `skills.external_dirs`, and unknown sources.
   e. Apply the extra core/workflow name guard and explicit blocklist/allowlist patterns inside that provenance boundary.
   f. Build a per-skill evidence report.
   g. Prepare a bounded managed curator-evolver:auto block.
   h. If the updated SKILL.md would exceed the 90k soft cap, reduce inline evidence and spill bulky details into references/.
   i. If the existing SKILL.md already exceeds the 100k hard cap, skip unattended update with reason skill-content-hard-cap.
   j. Preserve all existing skill text outside that block.
8. If --apply-low-risk is not set:
   return dry-run plan only.
9. If --apply-low-risk is set but --approve-auto-apply is missing:
   refuse to write.
10. If both write flags are set and the policy gate permits the skill:
   apply through guarded apply with SHA256 check, backup, post-apply verification, and rollback manifest. Timers installed by `bootstrap`/`install-auto` use the built-in `skill_validate` verifier by default; direct `auto-run` can still provide a custom `--verify-command`.
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
    original = read(skill_file)
    if pinned(original):
        skip("pinned-skill")
    source = classify_skill_source(skill_file, name)
    if apply_low_risk and approve_auto_apply and source != "local-agent-created":
        skip("source-not-agent-created")
    if apply_low_risk and approve_auto_apply and auto_apply_blocked(name):
        skip("core-skill-auto-apply-protected")

    skill_report = build_report(store, days=days, skill=name)
    prepared = prepare_low_risk_skill_update(
        skill_name=name,
        skill_text=original,
        days=days,
        summary=skill_report.summary,
        evidence_rows=skill_report.skill_evidence,
    )
    if prepared.skipped_reason:
        skip(prepared.skipped_reason)

    if apply_low_risk and approve_auto_apply:
        apply_guarded_patch(
            target_path=skill_file,
            new_content=prepared.content,
            expected_sha256=sha256_file(skill_file),
            backup_root=backup_dir,
            verify_command=verify_command,
        )
        write_support_files(prepared.support_files)
```

## What gets written

Autorun only writes a managed block like this:

```md
<!-- curator-evolver:auto:start -->
## Auto-curated evidence notes

Low-risk bounded auto-curation generated by `hermes-curator-evolver`.
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

If the block already exists, autorun replaces only that managed block. It does not rewrite the rest of the skill. When the block would make `SKILL.md` too large, autorun keeps a compact pointer in the block and writes bulky evidence to a `references/curator-evolver-auto-*.md` support file. If the starting `SKILL.md` is already above the 100k hard cap, unattended update is skipped instead of making the file larger.

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

## Optional: multi-variant candidate evaluation (`--variants N`)

`auto-run --variants N` (default `N=1`) deterministically generates up to four bounded variants per evidence-eligible skill and picks one winner before any guarded apply.

- Variants only vary knobs that are already inside the bounded mutation policy: number of inline evidence rows, whether evidence spills into `references/`, and which "agent guidance" phrasing leads the managed block.
- Variant 0 is always the prior default, so `--variants 1` is byte-identical to the pre-variants behavior.
- The scorer is deterministic and model-free: it prefers inline strategy over spillover, more hard-cap slack, and smaller diff from the existing skill. Ties break on variant index, so the same input always picks the same winner.
- Dry-run output exposes `candidate.variants[]` summaries (name, spec, size strategy, content chars, score, selected flag) and a `candidate.selected_variant` block for review.
- Auto-apply still goes through the existing source/approval/hash/backup/verification gates and writes only the winner.

This adapts the multi-candidate evaluation idea clean-room — there is no agent loop, no model selecting variants, and no execution of model-generated content. See [hyperagents-design-notes.md](hyperagents-design-notes.md) for the full rationale.

## Optional: staged verifier gate

`apply_guarded_patch` (and `auto-run` via `--staged-verify` or `--pre-verify-command`) supports a cheap-then-expensive verifier chain after the write happens.

- **Stage 1 — `builtin-structural`**: in-process check; the post-write file must stay under the 100k hard cap, keep the managed-block markers balanced, and keep parseable frontmatter. No subprocess.
- **Stage 2 (optional) — `pre-verify-command`**: a caller-supplied cheap pre-check shell command. Useful for a fast lint or schema validation.
- **Stage 3 — `verify-command`**: the same expensive verifier callers were passing before (e.g., the bundled `skill_validate` validator or `python -m pytest -q`).

The expensive stage is skipped entirely if any earlier stage fails, and any stage failure triggers the existing rollback path. Backward compatibility: when no `--staged-verify` / `--pre-verify-command` is requested, the verifier shape and behavior are unchanged. When staged verification is in use, the result keeps top-level `verify.passed` / `verify.exit_code` / `verify.output` so existing tooling continues to work, and adds a `verify.stages[]` list with per-stage results plus `verify.failed_stage` on failure.

## Mental model

Think of the current system as two lanes that now meet at the candidate-ordering step:

```text
Lane A — safe automation default
Evidence counts → deterministic candidate ordering → bounded managed notes + optional reference spillover → guarded apply

Lane B — model-assisted ordering opt-in
Evidence-eligible candidates → embedding/rerank ordering → bounded managed notes + optional reference spillover → guarded apply
```

Models can improve which eligible skill is considered first, but they cannot bypass evidence thresholds or guarded apply.
