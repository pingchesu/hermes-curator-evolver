# Phase 1 Plan — v0.1 Read-only Evidence Plugin

## Objective

Build and verify a first usable Hermes plugin release for `hermes-curator-evolver`.

## Scope

1. Create Python package and plugin manifest.
2. Write tests first for storage, reporting, plugin registration, and safety guardrails.
3. Implement SQLite-backed evidence storage.
4. Implement hook callbacks for `post_tool_call`, `post_llm_call`, and `on_session_end`.
5. Implement CLI commands:
   - `hermes curator-evolver status`
   - `hermes curator-evolver report --days N [--format markdown|json]`
   - `hermes curator-evolver analyze --skill NAME --days N`
6. Implement one tool `curator_evidence_report` returning JSON strings.
7. Register slash command `/curator-evolver` for quick status/report access.
8. Bundle namespaced skill `curator-evolver:curator-evolution`.
9. Write README with install/enable/usage and limitations.
10. Verify with pytest and plugin discovery smoke tests.

## Acceptance Criteria

- [ ] Tests fail before implementation and pass after implementation.
- [ ] Package imports cleanly on Python 3.11.
- [ ] Plugin registration works with a fake Hermes plugin context.
- [ ] Storage writes and aggregates evidence without external services.
- [ ] CLI report produces useful Markdown/JSON.
- [ ] No code path mutates `~/.hermes/skills` or calls `skill_manage`.
- [ ] Repo is committed and pushed to GitHub under `pingchesu/hermes-curator-evolver`.

## Verification Commands

```bash
python -m pytest -q
python -m pip install -e .
python -m pytest -q
```

## Risks

- Hermes plugin CLI entry point behavior can differ between directory plugins and pip entry points. Mitigation: support both `plugin.yaml` and `hermes_agent.plugins` entry point.
- Hook signatures may evolve. Mitigation: callbacks accept `**kwargs` and use narrow defaults.
- Evidence can grow unbounded. Mitigation: v0.1 stores compact previews only.
