# After install: autorun, health checks, and supported models

This page is the short operator guide for users who installed `hermes-curator-evolver` through the README quick start and want to know what happens next.

## What should be true after quick start

The open-box quick start installs three things:

```bash
hermes plugins install pingchesu/hermes-curator-evolver --enable
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e ~/.hermes/plugins/curator-evolver
hermes-curator-evolver bootstrap
```

`bootstrap` combines the two noisy setup steps that used to be separate: it backfills recent sessions and installs/enables the daily timer. Use `bootstrap --semantic` only when you explicitly want embedding + rerank candidate ordering.

After that:

| Component | Expected state |
| --- | --- |
| Plugin clone | `~/.hermes/plugins/curator-evolver` exists. |
| CLI entrypoint | `hermes-curator-evolver` is available in the Hermes Python environment. |
| Evidence DB | `~/.hermes/plugins/curator-evolver/data/evidence.sqlite` exists and includes recent backfilled session evidence. |
| User timer | `hermes-curator-evolver-auto.timer` runs daily. |
| Hermes core | Unmodified. The plugin is removable without patching Hermes Agent source code. |

## What autorun actually does

Daily autorun is intentionally narrow. It learns from observed Hermes usage and only applies low-risk managed notes to local agent-created skills. Official/bundled skills, hub-installed skills, plugin-provided skills, and skills loaded from `skills.external_dirs` are analyzed and can appear in dry-run output, but unattended writes skip them. By default it is deterministic and model-free. If the user explicitly chooses `--semantic-candidates` / `--rerank-candidates`, autorun uses embedding/rerank only to reorder skills that already passed the evidence threshold. For the exact algorithm, see [core-algorithm.md](core-algorithm.md).

```text
Hermes sessions / tool calls / skill usage / optional historical backfill
  → curator-evolver evidence.sqlite
  → evidence-eligible candidate set
  → optional semantic/rerank ordering if explicitly selected
  → local-agent-created provenance policy gate
  → bounded managed SKILL.md evidence note
  → optional references/ spillover for bulky evidence
  → backup + rollback manifest
  → post-apply SKILL.md validation
```

The timer runs the equivalent of:

```bash
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json \
  --apply-low-risk \
  --approve-auto-apply \
  --protect-core-skills \
  --verify-command "python -m hermes_curator_evolver.skill_validate" \
  --verify-cwd ~/.hermes/skills
```

The semantic/rerank timer adds:

```bash
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json \
  --semantic-candidates \
  --rerank-candidates \
  --apply-low-risk \
  --approve-auto-apply \
  --protect-core-skills
```

Autorun does **not** rewrite whole skills, delete existing content, change Hermes Agent core, mutate pinned skills, or auto-apply to official/bundled, hub-installed, plugin-provided, `external_dirs`, unknown-source, or already-over-hard-cap skills. The installed timer also runs the built-in `skill_validate` check after each successful write; if validation fails, guarded apply rolls the skill back and records the failed verification in the manifest. `--allow-auto-apply-skill` can relax the extra core-name guard only inside the local agent-created boundary; it does not override provenance. If semantic/rerank model execution fails locally, autorun records the error and falls back to deterministic evidence ordering instead of crashing.

## Historical session backfill

Plugin hooks collect evidence after the plugin is enabled. If the user already has existing Hermes transcripts, import them once:

```bash
hermes-curator-evolver backfill-sessions --sessions-dir ~/.hermes/sessions --days 30 --format json
```

For a low-cost check, inspect only the newest files:

```bash
hermes-curator-evolver backfill-sessions --sessions-dir ~/.hermes/sessions --days 7 --limit 50 --format json
```

Backfill records parseable tool calls, user/assistant turns, and session completion markers into the same local SQLite evidence DB. It is duplicate-safe for repeated runs against the same session files, and it does not mutate skills by itself. Run `auto-run --format json` afterward to preview newly eligible skills.

## Health checks

Check plugin registration:

```bash
hermes plugins list
```

Check the CLI:

```bash
hermes-curator-evolver status
```

Preview what the next autorun would do without changing files:

```bash
hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --format json
hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --semantic-candidates --rerank-candidates --format json
```

Check the user timer:

```bash
systemctl --user status hermes-curator-evolver-auto.timer
systemctl --user list-timers hermes-curator-evolver-auto.timer
```

Run the timer job immediately for a one-off smoke test:

```bash
systemctl --user start hermes-curator-evolver-auto.service
journalctl --user -u hermes-curator-evolver-auto.service -n 100 --no-pager
```

## Supported models

The plugin is designed so the default autorun path does **not** require a model. Models are optional helpers for review and candidate discovery.

| Feature | Model support | Default |
| --- | --- | --- |
| Evidence collection | None. Local SQLite aggregation only. | Always on when plugin hooks run. |
| Daily autorun | Model-free by default; optional `--semantic-candidates --rerank-candidates` uses the same embedding/reranker models only to reorder evidence-eligible candidates. | No model download unless semantic/rerank autorun is explicitly selected. |
| Proposal drafting | The active Hermes configured chat model/provider. The plugin does not hardcode OpenAI, Anthropic, or a local model. | Off unless `--draft-with-model` is passed. |
| Verifier | Deterministic verifier today; future verifier prompt should use Hermes configured chat model. | Deterministic, no model required. |
| Candidate embedding search | `Qwen/Qwen3-Embedding-0.6B` through `sentence-transformers`. | Off unless `--execute-semantic` is passed. |
| Candidate reranking | `BAAI/bge-reranker-v2-m3` through `sentence-transformers` `CrossEncoder`. | Off unless `--rerank` is passed. |

Install optional semantic dependencies only if you want embedding/reranker candidate search:

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e "$HOME/.hermes/plugins/curator-evolver[semantic]"
# Optional runtime tuning:
# HERMES_CURATOR_EVOLVER_SEMANTIC_DEVICE=cpu|cuda|auto
# HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT=512
```

Then run semantic candidate search explicitly:

```bash
hermes-curator-evolver candidates \
  --query "gateway plugin restart" \
  --skills-dir ~/.hermes/skills \
  --execute-semantic \
  --rerank \
  --format json
```

Or opt the automatic timer into semantic/rerank candidate ordering:

```bash
hermes-curator-evolver install-auto --schedule daily --enable --semantic-candidates --rerank-candidates
```

Important model boundaries:

- Models help find or draft candidate improvements; they do not get unilateral write access.
- `auto-run` low-risk writes are deterministic, bounded, and local-agent-created-only by default.
- Bulky autorun evidence spills into `references/` to keep `SKILL.md` under the 100k tool cap; already-over-hard-cap skills are skipped.
- In semantic/rerank autorun, model scores only reorder candidates that already passed the evidence threshold.
- Semantic models are never downloaded unless the user explicitly asks for semantic execution.
- Semantic ranking truncates SKILL.md text to `HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT` characters, default `512`, and uses `batch_size=1` to avoid local GPU/CPU memory spikes.
- Semantic runtime device is configurable with `HERMES_CURATOR_EVOLVER_SEMANTIC_DEVICE` (`auto`, `cpu`, or `cuda`; default `auto`).
- The chat model path follows the user's Hermes configuration instead of plugin-specific credentials.

## Stop or uninstall

Stop and remove the autorun timer:

```bash
hermes-curator-evolver uninstall-auto
```

Remove the plugin:

```bash
hermes plugins disable curator-evolver
hermes plugins uninstall curator-evolver
```

Remove local evidence/backups only if you want a clean slate:

```bash
rm -rf ~/.hermes/plugins/curator-evolver/data ~/.hermes/plugins/curator-evolver/backups
```
