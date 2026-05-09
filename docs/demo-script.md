# 60-second demo script

Use this as a terminal walkthrough, GIF script, or asciinema storyboard. The first three commands are read-only; the final apply command is shown as an explicit write path.

## Setup

```bash
hermes plugins install pingchesu/hermes-curator-evolver --enable
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e ~/.hermes/plugins/curator-evolver
hermes-curator-evolver bootstrap
```

## Safe inspection path

```bash
# 1. Confirm the local evidence database and timer state.
hermes-curator-evolver status

# 2. See which skills have real usage evidence.
hermes-curator-evolver report --days 14

# 3. Generate a dry-run proposal for one skill.
# Replace this path with any local skill file you want to inspect.
hermes-curator-evolver propose \
  --skill hermes-agent \
  --skill-file ~/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md \
  --format json \
  --output proposal.json

# 4. Verify the proposal before any write.
hermes-curator-evolver verify \
  --proposal-file proposal.json \
  --skill hermes-agent \
  --format json

# 5. Preview the automatic evolution pass. Still dry-run by default.
hermes-curator-evolver auto-run \
  --skills-dir ~/.hermes/skills \
  --format json
```

## Explicit write path

Only run this after inspecting the proposal and confirming the target hash:

```bash
sha256sum ~/.hermes/skills/local/my-skill/SKILL.md

hermes-curator-evolver apply \
  --target ~/.hermes/skills/local/my-skill/SKILL.md \
  --content-file reviewed-SKILL.md \
  --expected-sha256 <current-sha256> \
  --backup-dir ~/.hermes/plugins/curator-evolver/backups \
  --verify-command "python -m pytest -q" \
  --approve
```

## Narration notes

- "The plugin learns from local Hermes session/tool-call evidence."
- "Proposal and report commands are read-only."
- "Unattended auto-run can only write managed append-only blocks, and only after explicit write flags."
- "Official, hub-installed, plugin-provided, external, pinned, and unknown-source skills are skipped."
- "Every guarded apply records a backup manifest so rollback is concrete, not hand-wavy."
