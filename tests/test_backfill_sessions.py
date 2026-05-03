import json
from pathlib import Path

from hermes_curator_evolver.backfill import backfill_sessions
from hermes_curator_evolver.storage import EvidenceStore


def _write_session(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "session_id": "session-test",
                "session_start": "2026-05-01T10:00:00",
                "last_updated": "2026-05-01T10:02:00",
                "model": "gpt-5.5",
                "platform": "slack",
                "messages": [
                    {"role": "user", "content": "Use the github PR skill"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "skill_view",
                                    "arguments": json.dumps({"name": "github-pr-workflow"}),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "content": json.dumps({"success": True, "name": "github-pr-workflow"}),
                    },
                    {"role": "assistant", "content": "Loaded the PR workflow."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_backfill_sessions_imports_tool_turn_and_session_events(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir / "session_20260501_100000_test.json")
    store = EvidenceStore(tmp_path / "evidence.sqlite")

    result = backfill_sessions(sessions_dir=sessions_dir, store=store, days=30)

    assert result["sessions_seen"] == 1
    assert result["sessions_imported"] == 1
    assert result["tool_events_imported"] == 1
    assert result["turn_events_imported"] == 1
    assert result["session_events_imported"] == 1
    summary = store.summary(days=365)
    assert summary["tool_events"] == 1
    assert summary["turn_events"] == 1
    assert summary["session_events"] == 1
    assert summary["skills"][0]["skill_name"] == "github-pr-workflow"


def test_backfill_sessions_is_idempotent_for_same_session_file(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir / "session_20260501_100000_test.json")
    store = EvidenceStore(tmp_path / "evidence.sqlite")

    first = backfill_sessions(sessions_dir=sessions_dir, store=store, days=30)
    second = backfill_sessions(sessions_dir=sessions_dir, store=store, days=30)

    assert first["tool_events_imported"] == 1
    assert second["tool_events_imported"] == 0
    summary = store.summary(days=365)
    assert summary["tool_events"] == 1
    assert summary["turn_events"] == 1
    assert summary["session_events"] == 1
