import json

from hermes_curator_evolver.reports import build_report, format_markdown_report
from hermes_curator_evolver.storage import EvidenceStore


def test_build_report_for_specific_skill_includes_skill_events(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.record_tool_call(
        tool_name="skill_manage",
        args={"name": "angi-platform-knowledge-base", "action": "patch"},
        result='{"success": true}',
        session_id="s1",
        task_id="t1",
        duration_ms=30,
    )

    report = build_report(store, days=30, skill="angi-platform-knowledge-base")

    assert report["filters"]["skill"] == "angi-platform-knowledge-base"
    assert report["summary"]["tool_events"] == 1
    assert report["skill_evidence"][0]["skill_name"] == "angi-platform-knowledge-base"


def test_markdown_report_contains_safety_disclaimer(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    report = build_report(store, days=7)

    markdown = format_markdown_report(report)

    assert "Read-only evidence report" in markdown
    assert "No skill mutations were performed" in markdown
