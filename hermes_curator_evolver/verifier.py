"""Verifier gate for dry-run skill evolution proposals."""

from __future__ import annotations

import re
from typing import Any

_DESTRUCTIVE_TERMS = {"delete", "remove", "archive", "rename", "merge", "prune"}


def _skill_matches(proposal: dict[str, Any], report: dict[str, Any]) -> bool:
    report_skill = (report.get("filters") or {}).get("skill")
    if not report_skill:
        return True
    return proposal.get("skill_name") == report_skill


def _report_evidence_count(report: dict[str, Any]) -> int:
    summary = report.get("summary") or {}
    row_count = len(report.get("skill_evidence") or [])
    aggregate_count = int(summary.get("skill_events") or 0) + int(summary.get("error_events") or 0)
    return max(row_count, aggregate_count)


def _grounded_in_report(proposal: dict[str, Any], report: dict[str, Any]) -> bool:
    proposal_count = int(proposal.get("grounding_event_count") or 0)
    return proposal_count > 0 and _report_evidence_count(report) > 0


def _action_tokens(action: dict[str, Any]) -> set[str]:
    raw = f"{action.get('kind', '')} {action.get('description', '')}".lower()
    return {part for part in re.split(r"[^a-z0-9]+", raw) if part}


def _non_destructive(proposal: dict[str, Any]) -> bool:
    for action in proposal.get("proposed_actions") or []:
        if _action_tokens(action) & _DESTRUCTIVE_TERMS:
            return False
    return True


def verify_proposal(proposal: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Verify a proposal before it can move toward guarded apply.

    This is a deterministic verifier gate for v0.2. It can be paired with a
    separate chat-model verifier later, but these checks remain mandatory.
    """

    checks = {
        "dry_run": proposal.get("dry_run") is True,
        "grounded_in_evidence": _grounded_in_report(proposal, report),
        "skill_matches_report": _skill_matches(proposal, report),
        "non_destructive": _non_destructive(proposal),
        "approval_required": proposal.get("requires_human_approval") is True,
        "mutation_blocked_by_default": proposal.get("mutation_allowed") is False,
    }
    passed = all(checks.values())
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "schema_version": "0.2",
        "passed": passed,
        "checks": checks,
        "failures": failures,
        "policy": "A proposal can advance only if grounded, dry-run, non-destructive, and explicitly reviewed.",
    }
