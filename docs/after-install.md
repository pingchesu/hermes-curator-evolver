# After install: autorun, health checks, and supported models

This page is the short operator guide for users who installed `hermes-curator-evolver` through the README quick start and want to know what happens next.

## What should be true after quick start

The open-box quick start installs three things:

```bash
hermes plugins install pingchesu/hermes-curator-evolver --enable
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e ~/.hermes/plugins/curator-evolver
hermes-curator-evolver install-auto --schedule daily --enable
hermes gateway restart
```

After that:

| Component | Expected state |
| --- | --- |
| Plugin clone | `~/.hermes/plugins/curator-evolver` exists. |
| CLI entrypoint | `hermes-curator-evolver` is available in the Hermes Python environment. |
| Evidence DB | `~/.hermes/plugins/curator-evolver/data/evidence.sqlite` is created as Hermes records evidence. |
| User timer | `hermes-curator-evolver-auto.timer` runs daily. |
| Hermes core | Unmodified. The plugin is removable without patching Hermes Agent source code. |

## What autorun actually does

Daily autorun is intentionally narrow. It learns from observed Hermes usage and only applies low-risk managed notes to skills. **In v0.6, autorun does not use embedding or reranking; those are available only in the separate advisory `candidates` command.** For the exact algorithm, see [core-algorithm.md](core-algorithm.md).

```text
Hermes sessions / tool calls / skill usage
  → curator-evolver evidence.sqlite
  → candidate selection for active skills
  → append-only managed SKILL.md evidence note
  → backup + rollback manifest
```

The timer runs the equivalent of:

```bash
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json \
  --apply-low-risk \
  --approve-auto-apply
```

Autorun does **not** rewrite whole skills, delete existing content, change Hermes Agent core, or mutate pinned skills.

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
| Daily autorun | **No embedding/rerank in v0.6.** Uses deterministic evidence thresholds and append-only patch policy. | No model download or inference. |
| Proposal drafting | The active Hermes configured chat model/provider. The plugin does not hardcode OpenAI, Anthropic, or a local model. | Off unless `--draft-with-model` is passed. |
| Verifier | Deterministic verifier today; future verifier prompt should use Hermes configured chat model. | Deterministic, no model required. |
| Candidate embedding search | `Qwen/Qwen3-Embedding-0.6B` through `sentence-transformers`. | Off unless `--execute-semantic` is passed. |
| Candidate reranking | `BAAI/bge-reranker-v2-m3` through `sentence-transformers` `CrossEncoder`. | Off unless `--rerank` is passed. |

Install optional semantic dependencies only if you want embedding/reranker candidate search:

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e '~/.hermes/plugins/curator-evolver[semantic]'
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

Important model boundaries:

- Models help find or draft candidate improvements; they do not get unilateral write access.
- `auto-run` low-risk writes are deterministic and append-only by default.
- Semantic models are never downloaded unless the user explicitly asks for semantic execution.
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
