# Hermes Curator Evolver

Read-only evidence-driven skill governance plugin for Hermes Agent curator workflows.

This project complements the official `hermes curator` instead of replacing it. v0.1 observes Hermes sessions and skill-related tool usage, stores compact local evidence in SQLite, and produces reports that help decide whether a skill should be improved, retitled, split, consolidated, or left alone.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the component diagram, data-flow sequence, repository/module map, and v0.1 safety boundary.

## v0.1 Safety Model

- Read-only evidence/reporting only.
- No automatic skill mutation.
- No calls to `skill_manage`.
- No writes into `~/.hermes/skills`.
- No embedding/rerank downloads by default.

## Install from source

```bash
git clone https://github.com/pingchesu/hermes-curator-evolver.git
cd hermes-curator-evolver
python -m pip install -e .
hermes plugins enable curator-evolver
```

Restart Hermes after enabling plugins.

## Directory-plugin install

You can also copy or symlink this repository into `~/.hermes/plugins/curator-evolver/`, then enable it:

```bash
mkdir -p ~/.hermes/plugins
ln -s /path/to/hermes-curator-evolver ~/.hermes/plugins/curator-evolver
hermes plugins enable curator-evolver
```

## CLI

Current Hermes versions list and enable general plugins, but the top-level `hermes <plugin>` CLI wiring is still only active for memory-provider plugin conventions. This plugin still registers `curator-evolver` through `ctx.register_cli_command()` for forward compatibility, and ships a standalone CLI for v0.1:

```bash
hermes-curator-evolver status
hermes-curator-evolver report --days 7
hermes-curator-evolver report --days 7 --format json
hermes-curator-evolver analyze --skill hermes-agent --days 30
```

If your Hermes build wires general plugin CLI commands, the intended command shape is equivalent:

```bash
hermes curator-evolver status
```

## Agent tool

When enabled, Hermes can call `curator_evidence_report` to retrieve a JSON evidence report.

## Data Location

By default, data is stored at:

```text
~/.hermes/plugins/curator-evolver/data/evidence.sqlite
```

Set `HERMES_CURATOR_EVOLVER_DB=/custom/path.sqlite` to override.

## Roadmap

- v0.1: read-only evidence/report plugin.
- v0.2: proposal generation + verifier gate.
- v0.3: optional semantic candidate generation with embeddings/rerankers.
- v0.4: guarded apply with explicit approval, backup, and audit history.
