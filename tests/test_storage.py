import json
from pathlib import Path

from hermes_curator_evolver.storage import EvidenceStore


def test_store_records_tool_call_and_detects_skill_reference(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)

    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result='{"success": true}',
        task_id="task-1",
        session_id="session-1",
        duration_ms=12,
    )

    summary = store.summary(days=7)

    assert summary["tool_events"] == 1
    assert summary["skill_events"] == 1
    assert summary["skills"][0]["skill_name"] == "hermes-agent"
    assert summary["skills"][0]["event_count"] == 1


def test_store_flags_errors_without_throwing_on_plain_text_result(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")

    store.record_tool_call(
        tool_name="terminal",
        args={"command": "false"},
        result="Traceback: boom",
        task_id="task-1",
        session_id="session-1",
        duration_ms=5,
    )

    summary = store.summary(days=7)

    assert summary["tool_events"] == 1
    assert summary["error_events"] == 1


def test_successful_json_with_error_word_in_field_name_is_not_error(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")

    store.record_tool_call(
        tool_name="curator_evidence_report",
        args={"days": 1},
        result='{"success": true, "report": {"summary": {"error_events": 0}}}',
        task_id="task-1",
        session_id="session-1",
        duration_ms=5,
    )

    summary = store.summary(days=7)

    assert summary["tool_events"] == 1
    assert summary["error_events"] == 0


def test_store_compacts_long_payloads(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite", preview_chars=20)

    store.record_turn(
        session_id="s",
        user_message="u" * 100,
        assistant_response="a" * 100,
        model="m",
        platform="cli",
    )

    rows = store.recent_turns(days=1, limit=1)

    assert len(rows) == 1
    assert len(rows[0]["user_preview"]) <= 21
    assert len(rows[0]["assistant_preview"]) <= 21
