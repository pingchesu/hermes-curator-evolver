# HyperAgents design notes

This document records why `hermes-curator-evolver` does **not** depend on or
embed code from
[`facebookresearch/HyperAgents`](https://github.com/facebookresearch/HyperAgents),
and which concepts we adapt clean-room into our existing safety model.

## Status

- HyperAgents is **not** a runtime dependency, build dependency, or vendored
  source of this plugin.
- No code, prompt text, or configuration is copied from the HyperAgents
  repository.
- The implementation here was written independently against
  `hermes-curator-evolver`'s existing modules (`auto_evolve.py`,
  `guarded_apply.py`, `verifier.py`, `skill_validate.py`).
- HyperAgents is referenced **only as conceptual inspiration** in the same way
  the README references SkillClaw for the broader "evolve skills from session
  evidence" idea.

If anything in this repository ever looks like it might overlap with
HyperAgents code or prompts, treat that as a bug and remove it — the trust
model below depends on this boundary holding.

## Why we do not integrate HyperAgents directly

HyperAgents is an interesting research codebase, but pulling it in as a
dependency or copying its agent loop into the plugin would break properties
this project is built around:

1. **Local-first, plugin-safe boundary.** Curator Evolver is a Hermes plugin.
   It must not patch Hermes core, must not require new long-running services,
   and must run end-to-end on a user laptop without remote orchestration.
2. **Default model-free path.** The default `bootstrap` / `auto-run` flow
   intentionally does not load any LLM, embedding model, or reranker.
   HyperAgents' control loops assume a model-in-the-loop agent supervising
   workers. That assumption is incompatible with "open the plugin, get safe
   bounded notes today".
3. **No execution of model-generated code.** Curator Evolver only ever writes
   text into a bounded `<!-- curator-evolver:auto:start -->` block inside a
   `SKILL.md` (plus optional `references/` spill files). It never executes
   model-generated shell, Python, or skill code. Any framework that ships an
   agent loop capable of running model-authored code as a tool call would
   widen the blast radius beyond what the MIT-licensed plugin advertises.
4. **License separation.** Keeping the implementation clean-room avoids any
   ambiguity about derivative-work status of HyperAgents and lets this plugin
   remain straight MIT-licensed under its existing `LICENSE` file.
5. **Backward compatibility.** Existing users rely on `auto-run` defaulting to
   single-candidate, deterministic, model-free behavior. Direct integration
   with HyperAgents-style multi-agent loops would change that default; the
   clean-room adaptation below preserves it.

## Concepts we adapt clean-room

We borrow only the high-level *ideas* below, and only where they map cleanly
onto guards we already enforce.

### 1. Multi-variant candidate evaluation

**HyperAgents idea (paraphrased):** generate several candidate outputs and let
a selector pick a winner rather than committing to the first sample.

**Our adaptation:**

- `auto-run --variants N` (default `N=1`, preserving the existing behavior).
- For each evidence-eligible skill, we deterministically synthesize up to `N`
  variants of the same bounded managed-block update. Variants differ only in
  knobs that are already inside the current bounded mutation policy:
  - `evidence_limit` (how many evidence rows render inline),
  - spillover strategy (`inline` vs. `reference-spillover`),
  - guidance phrasing,
  - whether agent guidance leads with verification or evidence reuse.
- Variants are then scored by a **deterministic, model-free scorer**: prefers
  variants that fit under the soft cap, that have not been forced to spill,
  that have higher signal-to-noise on inline evidence, and that produce a
  smaller diff from the existing block.
- The winner — and only the winner — flows into `apply_guarded_patch`. The
  losers exist only as dry-run summaries in the JSON output.

This is *not* a HyperAgents agent loop. There is no model selecting variants,
no remote orchestrator, and no recursive supervision. It is a finite,
deterministic sweep over already-permitted bounded outputs.

### 2. Staged verifier gate

**HyperAgents idea (paraphrased):** verification should not be a single
expensive pass. Cheap structural checks should run first, and expensive
critic-style checks should only run if the cheap stage already passes.

**Our adaptation:**

- `apply_guarded_patch` now supports a staged verification path.
- Stage 1 ("cheap"): a built-in structural check that runs in-process and
  needs no subprocess. It validates the post-write `SKILL.md` against the
  same guarantees the plugin already enforces (managed-block intact, size
  under hard cap, frontmatter still parseable, etc.). Optionally, a caller
  may pass a `pre_verify_command` for a custom cheap pre-check.
- Stage 2 ("expensive"): the existing `verify_command` (e.g., the bundled
  `skill_validate` validator, or a user-provided shell command). Stage 2 only
  runs if Stage 1 passed.
- If any stage fails after the write happens, the backup is restored and the
  manifest records `rolled_back: true` with the failed stage name.
- Manifests still expose a top-level `verify.passed` / `verify.exit_code` for
  backward compatibility with existing tooling, but also include a
  `verify.stages[]` list with per-stage results when staged verification is
  used.

The expensive verifier is exactly the same `verify_command` callers already
pass; we just gate it behind a cheap stage to avoid burning local CPU on
candidates that would never pass even the trivial structural check.

## Implementation mapping

| Concept | Module | Notes |
| --- | --- | --- |
| Variant generation | `hermes_curator_evolver/auto_evolve.py` (`generate_variants`) | Deterministic; reuses `prepare_low_risk_skill_update`. |
| Variant selection | `hermes_curator_evolver/auto_evolve.py` (`select_winning_variant`) | Pure function over candidate metadata. |
| Cheap structural check | `hermes_curator_evolver/guarded_apply.py` (`_run_builtin_cheap_check`) | In-process; reuses bounded-block + size invariants. |
| Staged verify orchestration | `hermes_curator_evolver/guarded_apply.py` (`_run_staged_verify`) | Calls cheap stage first, then optional `verify_command`. |
| Tests | `tests/test_auto_evolve.py`, `tests/test_guarded_apply.py` | Cover variants, determinism, dry-run shape, and stage-failure rollback. |

## Safety contract we keep

Even with variants and staged verification, **all of these still hold**:

- No Hermes core patches; the plugin only writes into skill files it already
  had permission to touch.
- Auto-apply still requires `--apply-low-risk --approve-auto-apply`, the same
  source-provenance gate, hash match, backup, and rollback path.
- The bounded `<!-- curator-evolver:auto:start --> ... <!-- end -->` block is
  the only region of any `SKILL.md` we mutate.
- No model-generated code is executed. Variants and verifier stages operate
  only on text already produced by the existing deterministic mutation
  policy.
- Default `auto-run` (no `--variants`, no opt-in flags) is byte-identical in
  behavior to the previous release for callers that don't opt in.

If HyperAgents-style features ever require relaxing one of these guarantees,
that's a signal to stop and re-design — not to relax the guard.
