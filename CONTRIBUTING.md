# Contributing to Hermes Curator Evolver

Thanks for improving Hermes Curator Evolver. This project is intentionally conservative: it helps Hermes skills evolve from evidence without silently rewriting the skill library or patching Hermes Agent core.

## Development setup

```bash
git clone https://github.com/pingchesu/hermes-curator-evolver.git
cd hermes-curator-evolver
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

For semantic/rerank work, install the optional model dependencies explicitly:

```bash
python -m pip install -e '.[dev,semantic]'
```

## Workflow

1. Create a feature branch from `main`.
2. Use test-driven development for behavior changes: write a failing test first, run it, then implement the smallest passing change.
3. Keep `.planning/` and other local agent artifacts out of PRs.
4. Update user-facing docs whenever behavior, commands, safety boundaries, model usage, or install/uninstall paths change.
5. Run the test suite before pushing.

```bash
python -m pytest -q
```

## Pull request checklist

Before opening a PR, verify:

- [ ] Tests cover the new behavior and pass locally.
- [ ] README/docs mention new commands or changed defaults.
- [ ] Safety boundaries remain intact: no Hermes core modifications, no destructive skill edits, guarded writes only.
- [ ] Optional semantic/rerank paths stay explicit opt-ins.
- [ ] CI-relevant files are included when needed.

## Local smoke tests

Useful non-mutating checks:

```bash
hermes-curator-evolver status
hermes-curator-evolver report --days 7 --format json
hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --format json
hermes-curator-evolver backfill-sessions --sessions-dir ~/.hermes/sessions --days 7 --limit 10 --format json
```

For scheduler install tests, use an isolated config/home root unless you intentionally want to mutate your real user scheduler. Linux/systemd tests can isolate `XDG_CONFIG_HOME`; macOS/launchd tests should monkeypatch `HOME` so LaunchAgent files land under a temp `~/Library/LaunchAgents`:

```bash
XDG_CONFIG_HOME=$(mktemp -d) hermes-curator-evolver install-auto --schedule daily --proposal-only
```

## CI

GitHub Actions runs `python -m pytest -q` on pull requests and pushes to `main`. CI intentionally uses the default/dev dependency set and does not download semantic models.
