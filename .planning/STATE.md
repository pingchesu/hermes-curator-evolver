# GSD State: Hermes Curator Evolver

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-03)

**Core value:** Give Hermes users grounded evidence for improving skills before any automated skill mutation is allowed.
**Current focus:** Phase 1 — v0.1 Read-only Evidence Plugin

## Current Phase

- Phase: 1
- Status: In Progress
- Execution mode: Sequential inline (Hermes runtime fallback)
- TDD: Required

## Notes

- User requested `/gsd` style development.
- Keep v0.1 read-only.
- Publish target: `pingchesu/hermes-curator-evolver`.
- Runtime finding: current Hermes top-level parser only wires memory-provider plugin CLI conventions, so v0.1 includes standalone `hermes-curator-evolver` CLI while still registering `ctx.register_cli_command("curator-evolver", ...)` for forward compatibility.
