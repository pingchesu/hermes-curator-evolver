"""Dry-run proposal generation for skill evolution."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable


def _summary(report: dict[str, Any]) -> dict[str, int]:
    raw = report.get("summary") or {}
    return {
        "tool_events": int(raw.get("tool_events") or 0),
        "skill_events": int(raw.get("skill_events") or 0),
        "error_events": int(raw.get("error_events") or 0),
        "turn_events": int(raw.get("turn_events") or 0),
        "session_events": int(raw.get("session_events") or 0),
    }


def _actions_from_evidence(summary: dict[str, int], skill_text: str) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if summary["error_events"]:
        actions.append(
            {
                "kind": "patch-troubleshooting",
                "description": "Add or refine troubleshooting guidance for repeated error-like tool evidence.",
                "evidence": f"{summary['error_events']} error-like event(s) in the selected window.",
            }
        )
    if summary["skill_events"]:
        actions.append(
            {
                "kind": "refresh-active-skill",
                "description": "Review active skill usage and add missing caveats or examples where evidence supports it.",
                "evidence": f"{summary['skill_events']} skill-related event(s) in the selected window.",
            }
        )
    if not skill_text.strip():
        actions.append(
            {
                "kind": "inspect-missing-skill-text",
                "description": "Skill text was unavailable; collect the current skill before drafting edits.",
                "evidence": "No skill text was provided to the dry-run proposal builder.",
            }
        )
    if not actions:
        actions.append(
            {
                "kind": "no-change",
                "description": "No change recommended from the current evidence window.",
                "evidence": "No matching evidence rows were available.",
            }
        )
    return actions


def build_skill_proposal(
    report: dict[str, Any], *, skill_name: str, skill_text: str = ""
) -> dict[str, Any]:
    """Build a dry-run skill improvement proposal from evidence.

    The base proposal is deterministic. Optional model drafting is handled by
    `build_model_drafted_proposal()` so the default path never calls a model or
    writes skill files by itself.
    """

    evidence_summary = _summary(report)
    evidence_rows = report.get("skill_evidence") or []
    grounding_event_count = len(evidence_rows)
    if grounding_event_count == 0:
        grounding_event_count = evidence_summary["skill_events"] + evidence_summary["error_events"]

    return {
        "schema_version": "0.2",
        "skill_name": skill_name,
        "dry_run": True,
        "requires_human_approval": True,
        "mutation_allowed": False,
        "evidence_summary": evidence_summary,
        "grounding_event_count": int(grounding_event_count),
        "proposed_actions": _actions_from_evidence(evidence_summary, skill_text),
        "model_plan": {
            "proposal_model": "Hermes configured chat model",
            "verifier_model": "Hermes configured chat model with separate verifier prompt",
            "policy": "Model output may draft proposals only; applying changes requires verifier pass, explicit approval, backup, and rollback.",
        },
        "draft_prompt": _draft_prompt(skill_name, evidence_summary, evidence_rows, skill_text),
    }


def hermes_chat_backend(prompt: str, *, timeout_seconds: int = 180) -> str:
    """Draft through the current Hermes CLI/model configuration.

    This uses Hermes as a read-only drafting subprocess. The prompt explicitly
    asks for proposal text only; applying edits remains a separate guarded step.
    """

    completed = subprocess.run(
        ["hermes", "chat", "-Q", "-q", prompt],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(stderr or f"hermes chat exited {completed.returncode}")
    return completed.stdout.strip()


def build_model_drafted_proposal(
    report: dict[str, Any],
    *,
    skill_name: str,
    skill_text: str = "",
    chat_backend: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Build a dry-run proposal and optionally attach chat-model draft text."""

    proposal = build_skill_proposal(report, skill_name=skill_name, skill_text=skill_text)
    if chat_backend is None:
        proposal["model_draft"] = {
            "executed": False,
            "text": "",
            "note": "No chat backend was provided; deterministic dry-run proposal only.",
        }
        return proposal

    try:
        draft = chat_backend(str(proposal["draft_prompt"]))
    except Exception as exc:
        proposal["model_draft"] = {
            "executed": False,
            "text": "",
            "error": str(exc),
        }
    else:
        proposal["model_draft"] = {
            "executed": True,
            "text": draft,
            "policy": "Draft text only; no files were changed.",
        }
    proposal["dry_run"] = True
    proposal["mutation_allowed"] = False
    proposal["requires_human_approval"] = True
    return proposal


def _draft_prompt(
    skill_name: str,
    evidence_summary: dict[str, int],
    evidence_rows: list[dict[str, Any]],
    skill_text: str,
) -> str:
    rows_preview = json.dumps(evidence_rows[:10], ensure_ascii=False, indent=2, sort_keys=True)
    skill_preview = skill_text[:4000]
    return (
        "Draft a conservative skill improvement proposal. Do not apply edits.\n"
        f"Skill: {skill_name}\n"
        f"Evidence summary: {json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True)}\n"
        f"Evidence rows: {rows_preview}\n"
        f"Current skill text preview:\n{skill_preview}\n"
        "Return proposed changes, risks, and verification steps only."
    )


def format_proposal_markdown(proposal: dict[str, Any]) -> str:
    lines = [
        "# Curator Evolver Proposal",
        "",
        f"- Skill: `{proposal.get('skill_name', '')}`",
        "- Mode: dry-run proposal",
        "- Safety: No files were changed.",
        f"- Grounding events: {proposal.get('grounding_event_count', 0)}",
        "",
        "## Proposed actions",
        "",
    ]
    for action in proposal.get("proposed_actions") or []:
        lines.append(f"- `{action.get('kind', 'unknown')}` — {action.get('description', '')}")
        if action.get("evidence"):
            lines.append(f"  - Evidence: {action['evidence']}")
    lines.extend(
        [
            "",
            "## Model plan",
            "",
            f"- Proposal: {proposal.get('model_plan', {}).get('proposal_model', '')}",
            f"- Verifier: {proposal.get('model_plan', {}).get('verifier_model', '')}",
            "",
            "## Draft prompt",
            "",
            "```text",
            proposal.get("draft_prompt", ""),
            "```",
        ]
    )
    return "\n".join(lines)


def format_proposal_json(proposal: dict[str, Any]) -> str:
    return json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True)
