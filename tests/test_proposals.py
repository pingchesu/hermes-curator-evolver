import json

from hermes_curator_evolver.proposals import build_skill_proposal, format_proposal_markdown
from hermes_curator_evolver.reports import build_report
from hermes_curator_evolver.storage import EvidenceStore
from hermes_curator_evolver.verifier import verify_proposal


def test_build_skill_proposal_is_dry_run_and_grounded_in_evidence(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.record_tool_call(
        tool_name="terminal",
        args={"skills": ["hermes-agent"], "command": "hermes doctor"},
        result="Traceback: missing gateway state",
        session_id="s1",
        task_id="t1",
        duration_ms=20,
    )
    report = build_report(store, days=30, skill="hermes-agent")

    proposal = build_skill_proposal(
        report,
        skill_name="hermes-agent",
        skill_text="# Hermes Agent\n\nExisting troubleshooting guide.",
    )

    assert proposal["dry_run"] is True
    assert proposal["skill_name"] == "hermes-agent"
    assert proposal["evidence_summary"]["error_events"] == 1
    assert proposal["proposed_actions"]
    assert proposal["requires_human_approval"] is True
    assert "Hermes configured chat model" in proposal["model_plan"]["proposal_model"]


def test_format_proposal_markdown_includes_no_mutation_disclaimer(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    report = build_report(store, days=7, skill="empty-skill")
    proposal = build_skill_proposal(report, skill_name="empty-skill", skill_text="")

    markdown = format_proposal_markdown(proposal)

    assert "# Curator Evolver Proposal" in markdown
    assert "No files were changed" in markdown
    assert "empty-skill" in markdown


def test_verifier_accepts_grounded_dry_run_proposal(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result='{"success": true}',
        session_id="s1",
        task_id="t1",
    )
    report = build_report(store, days=30, skill="hermes-agent")
    proposal = build_skill_proposal(report, skill_name="hermes-agent", skill_text="content")

    verdict = verify_proposal(proposal, report)

    assert verdict["passed"] is True
    assert verdict["checks"]["dry_run"] is True
    assert verdict["checks"]["grounded_in_evidence"] is True


def test_verifier_rejects_ungrounded_or_mutating_proposal(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    report = build_report(store, days=7, skill="hermes-agent")
    proposal = {
        "skill_name": "other-skill",
        "dry_run": False,
        "grounding_event_count": 0,
        "proposed_actions": [{"kind": "delete", "description": "remove skill"}],
    }

    verdict = verify_proposal(proposal, report)

    assert verdict["passed"] is False
    assert verdict["checks"]["dry_run"] is False
    assert verdict["checks"]["grounded_in_evidence"] is False
    assert verdict["checks"]["non_destructive"] is False


def test_verifier_cross_checks_grounding_against_report_evidence(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    report = build_report(store, days=7, skill="hermes-agent")
    forged = {
        "skill_name": "hermes-agent",
        "dry_run": True,
        "requires_human_approval": True,
        "mutation_allowed": False,
        "grounding_event_count": 99,
        "proposed_actions": [{"kind": "refresh-active-skill", "description": "looks grounded"}],
    }

    verdict = verify_proposal(forged, report)

    assert verdict["passed"] is False
    assert verdict["checks"]["grounded_in_evidence"] is False


def test_verifier_rejects_destructive_action_variants(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result='{"success": true}',
        session_id="s1",
        task_id="t1",
    )
    report = build_report(store, days=7, skill="hermes-agent")
    proposal = build_skill_proposal(report, skill_name="hermes-agent", skill_text="content")
    proposal["proposed_actions"] = [
        {"kind": "delete-skill", "description": "delete the whole skill"}
    ]

    verdict = verify_proposal(proposal, report)

    assert verdict["passed"] is False
    assert verdict["checks"]["non_destructive"] is False
