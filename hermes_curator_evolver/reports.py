"""Evidence report generation."""

from __future__ import annotations

import json
from typing import Any

from .storage import EvidenceStore


def build_report(store: EvidenceStore, *, days: int, skill: str | None = None) -> dict[str, Any]:
    """Build a read-only evidence report from the local store."""
    return {
        "title": "Hermes Curator Evolver evidence report",
        "read_only": True,
        "db_path": str(store.db_path),
        "filters": {"days": days, "skill": skill},
        "summary": store.summary(days=days, skill=skill),
        "skill_evidence": store.recent_tool_events(days=days, skill=skill, limit=20),
        "recent_turns": store.recent_turns(days=days, limit=10),
        "recommendation_policy": {
            "v0_1": "report_only",
            "mutation": "not_supported",
            "next_steps": [
                "Use repeated tool errors as candidates for targeted skill improvements.",
                "Use skill event counts to identify active skills worth reviewing.",
                "Use semantic candidate generation only in a later explicit opt-in phase.",
            ],
        },
    }


def build_default_report(*, days: int, skill: str | None = None) -> dict[str, Any]:
    return build_report(EvidenceStore(), days=days, skill=skill)


def format_json_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def format_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    filters = report["filters"]
    skill = filters.get("skill")
    title = "# Hermes Curator Evolver — Read-only evidence report"
    lines = [
        title,
        "",
        f"- Window: last {filters['days']} day(s)",
        f"- Skill filter: `{skill}`" if skill else "- Skill filter: all skills",
        f"- DB: `{report['db_path']}`",
        "- Safety: No skill mutations were performed.",
        "",
        "## Summary",
        "",
        f"- Tool events: {summary['tool_events']}",
        f"- Skill-related events: {summary['skill_events']}",
        f"- Error-like tool events: {summary['error_events']}",
        f"- Turn events: {summary['turn_events']}",
        f"- Session-end events: {summary['session_events']}",
        "",
    ]
    lines.extend(["## Top skills", ""])
    if summary["skills"]:
        for item in summary["skills"]:
            lines.append(
                f"- `{item['skill_name']}` — {item['event_count']} event(s), "
                f"{item['errors']} error-like"
            )
    else:
        lines.append("- No skill-related events recorded in this window.")
    lines.extend(["", "## Top tools", ""])
    if summary["tools"]:
        for item in summary["tools"]:
            lines.append(
                f"- `{item['tool_name']}` — {item['event_count']} event(s), "
                f"{item['errors']} error-like"
            )
    else:
        lines.append("- No tool events recorded in this window.")
    lines.extend(["", "## Recent skill/tool evidence", ""])
    evidence = report["skill_evidence"]
    if evidence:
        for item in evidence[:10]:
            skill_label = item.get("skill_name") or "—"
            marker = "⚠️" if item.get("is_error") else "✓"
            lines.append(
                f"- {marker} `{item['created_at']}` tool=`{item['tool_name']}` "
                f"skill=`{skill_label}` session=`{item.get('session_id') or '—'}`"
            )
    else:
        lines.append("- No recent evidence rows matched the filters.")
    lines.extend(
        [
            "",
            "## Interpretation policy",
            "",
            "This report is evidence only. Repeated errors or repeated skill reads are candidates for human review, not proof that a skill should be changed.",
            "",
            "No skill mutations were performed by Hermes Curator Evolver v0.1.",
        ]
    )
    return "\n".join(lines)
