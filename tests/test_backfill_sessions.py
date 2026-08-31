import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from hermes_curator_evolver.backfill import (
    backfill_sessions,
    default_sessions_dir,
    default_state_db_path,
)
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

    result = backfill_sessions(sessions_dir=sessions_dir, store=store, days=365)

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

    first = backfill_sessions(sessions_dir=sessions_dir, store=store, days=365)
    second = backfill_sessions(sessions_dir=sessions_dir, store=store, days=365)

    assert first["tool_events_imported"] == 1
    assert second["tool_events_imported"] == 0
    summary = store.summary(days=365)
    assert summary["tool_events"] == 1
    assert summary["turn_events"] == 1
    assert summary["session_events"] == 1


def test_default_session_sources_follow_active_hermes_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / "AppData" / "Local" / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert default_sessions_dir() == hermes_home / "sessions"
    assert default_state_db_path() == hermes_home / "state.db"


def test_backfill_sessions_reads_current_hermes_state_db_read_only(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    state_db.touch()
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    now = datetime.now(timezone.utc).timestamp()
    closed = []

    class FakeSessionDB:
        def __init__(self, db_path, read_only=False):
            assert Path(db_path) == state_db
            assert read_only is True

        def search_sessions(self, source=None, limit=20, offset=0):
            if offset:
                return []
            return [
                {
                    "id": "state-session-test",
                    "started_at": now - 60,
                    "ended_at": now,
                    "last_active": now,
                    "model": "gpt-5.6",
                    "source": "desktop",
                }
            ]

        def get_messages(self, session_id, *, include_compacted=False):
            assert session_id == "state-session-test"
            assert include_compacted is True
            return [
                {"role": "user", "content": "Use the github PR skill"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-state-1",
                            "type": "function",
                            "function": {
                                "name": "skill_view",
                                "arguments": json.dumps({"name": "github-operations"}),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-state-1",
                    "content": json.dumps({"success": True, "name": "github-operations"}),
                },
                {"role": "assistant", "content": "Loaded the GitHub workflow."},
            ]

        def close(self):
            closed.append(True)

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=FakeSessionDB))

    result = backfill_sessions(state_db=state_db, store=store, days=30)
    repeated = backfill_sessions(state_db=state_db, store=store, days=30)

    assert result["source_type"] == "state_db"
    assert result["source_path"] == str(state_db)
    assert result["sessions_seen"] == 1
    assert result["sessions_imported"] == 1
    assert result["tool_events_imported"] == 1
    assert result["turn_events_imported"] == 1
    assert result["session_events_imported"] == 1
    assert repeated["tool_events_imported"] == 0
    assert repeated["turn_events_imported"] == 0
    assert repeated["session_events_imported"] == 0
    assert closed == [True, True]
    summary = store.summary(days=30)
    assert summary["skills"][0]["skill_name"] == "github-operations"


def test_backfill_sessions_prefers_default_state_db_over_legacy_dumps(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    sessions_dir = hermes_home / "sessions"
    sessions_dir.mkdir(parents=True)
    _write_session(sessions_dir / "session_legacy.json")
    state_db = hermes_home / "state.db"
    state_db.touch()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    class EmptySessionDB:
        def __init__(self, db_path, read_only=False):
            assert Path(db_path) == state_db
            assert read_only is True

        def search_sessions(self, source=None, limit=20, offset=0):
            return []

        def get_messages(self, session_id):
            raise AssertionError("no sessions should be loaded")

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=EmptySessionDB))

    result = backfill_sessions(store=EvidenceStore(tmp_path / "evidence.sqlite"), days=30)

    assert result["source_type"] == "state_db"
    assert result["sessions_seen"] == 0


def test_backfill_sessions_does_not_mark_live_state_session_complete(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    state_db.touch()
    now = datetime.now(timezone.utc).timestamp()

    class LiveSessionDB:
        def __init__(self, db_path, read_only=False):
            assert Path(db_path) == state_db
            assert read_only is True

        def search_sessions(self, source=None, limit=20, offset=0):
            if offset:
                return []
            return [
                {
                    "id": "live-session",
                    "started_at": now - 60,
                    "ended_at": None,
                    "last_active": now,
                    "model": "gpt-5.6",
                    "source": "desktop",
                }
            ]

        # Hermes versions before August 2026 do not expose include_compacted.
        # Backfill must retain this compatibility path.
        def get_messages(self, session_id):
            return [
                {"role": "user", "content": "Still running", "timestamp": now - 1},
                {"role": "assistant", "content": "Yes", "timestamp": now},
            ]

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=LiveSessionDB))
    store = EvidenceStore(tmp_path / "evidence.sqlite")

    result = backfill_sessions(state_db=state_db, store=store, days=30)

    assert result["turn_events_imported"] == 1
    assert result["session_events_imported"] == 0
    assert store.summary(days=30)["session_events"] == 0


def test_backfill_sessions_explicit_legacy_dir_remains_supported(tmp_path):
    sessions_dir = tmp_path / "legacy-sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir / "session_legacy.json")

    result = backfill_sessions(
        sessions_dir=sessions_dir,
        store=EvidenceStore(tmp_path / "evidence.sqlite"),
        days=365,
    )

    assert result["source_type"] == "legacy_json"
    assert result["source_path"] == str(sessions_dir)
    assert result["sessions_seen"] == 1
