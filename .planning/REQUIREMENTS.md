# Requirements: Hermes Curator Evolver

**Defined:** 2026-05-03
**Core Value:** Give Hermes users grounded evidence for improving skills before any automated skill mutation is allowed.

## v1 Requirements

### Plugin Integration

- [ ] **PLUG-01**: Plugin has a valid `plugin.yaml` manifest for directory installation.
- [ ] **PLUG-02**: Plugin exposes a Python package entry point under `hermes_agent.plugins` for pip installation.
- [ ] **PLUG-03**: Plugin registers observer hooks without breaking Hermes if storage writes fail.
- [ ] **PLUG-04**: Plugin registers a CLI command named `curator-evolver`.
- [ ] **PLUG-05**: Plugin registers at least one tool for agent-accessible evidence reporting.

### Evidence Capture

- [ ] **EVID-01**: Plugin records post-tool-call evidence including tool name, task/session identifiers when present, duration, error flag, and compact previews.
- [ ] **EVID-02**: Plugin identifies skill interactions from `skill_view`, `skill_manage`, and skill-related tool arguments.
- [ ] **EVID-03**: Plugin records post-LLM turn summaries without storing full unbounded conversation history.
- [ ] **EVID-04**: Plugin stores evidence in SQLite under a Hermes-scoped local data directory.

### Reporting

- [ ] **REPT-01**: CLI `status` shows DB path and aggregate counts.
- [ ] **REPT-02**: CLI `report --days N` produces Markdown or JSON evidence summaries.
- [ ] **REPT-03**: CLI `analyze --skill NAME` produces a per-skill read-only evidence report.
- [ ] **REPT-04**: Tool handler returns JSON strings and never raw Python dicts.

### Safety and Verification

- [ ] **SAFE-01**: v0.1 contains no automatic skill mutation path.
- [ ] **SAFE-02**: Hook failures are swallowed/logged and must not interrupt Hermes sessions.
- [ ] **SAFE-03**: Tests cover storage, reports, plugin registration, and safety guardrails.
- [ ] **SAFE-04**: README documents installation, enabling, usage, and v0.1 limitations.

## v2 Requirements

### Semantic Candidate Generation

- **SEM-01**: Add optional embedding cache keyed by skill/evidence content hash.
- **SEM-02**: Add optional reranker for `same_umbrella` / `sibling_but_separate` / `narrow_reference_under_existing` / `unrelated` labels.
- **SEM-03**: Keep semantic signals advisory and require verifier gates before apply.

### Guarded Apply

- **APPL-01**: Propose targeted skill patches with evidence references.
- **APPL-02**: Verify candidate changes before apply.
- **APPL-03**: Apply only with explicit user approval, backup, and rollback metadata.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auto-delete skills | Too risky and contrary to conservative governance goals |
| Monkeypatch official curator | Fragile and hard to maintain across Hermes upgrades |
| Default model downloads | Bad first-run UX; semantic mode should be explicit opt-in |
| Shared central skill registry | Requires separate governance design |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLUG-01 | Phase 1 | Pending |
| PLUG-02 | Phase 1 | Pending |
| PLUG-03 | Phase 1 | Pending |
| PLUG-04 | Phase 1 | Pending |
| PLUG-05 | Phase 1 | Pending |
| EVID-01 | Phase 1 | Pending |
| EVID-02 | Phase 1 | Pending |
| EVID-03 | Phase 1 | Pending |
| EVID-04 | Phase 1 | Pending |
| REPT-01 | Phase 1 | Pending |
| REPT-02 | Phase 1 | Pending |
| REPT-03 | Phase 1 | Pending |
| REPT-04 | Phase 1 | Pending |
| SAFE-01 | Phase 1 | Pending |
| SAFE-02 | Phase 1 | Pending |
| SAFE-03 | Phase 1 | Pending |
| SAFE-04 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-05-03*
*Last updated: 2026-05-03 after project initialization*
