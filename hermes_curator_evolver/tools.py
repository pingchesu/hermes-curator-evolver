"""Hermes tool handlers."""

from __future__ import annotations

import json
from typing import Any

from .reports import build_default_report, format_json_report, format_markdown_report

CURATOR_EVIDENCE_REPORT_SCHEMA = {
    "name": "curator_evidence_report",
    "description": (
        "Return a read-only Hermes skill-curator evidence report from the local "
        "curator-evolver SQLite store. Does not mutate skills."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Lookback window in days.",
                "default": 7,
                "minimum": 1,
                "maximum": 365,
            },
            "skill": {
                "type": "string",
                "description": "Optional exact skill name filter.",
            },
            "format": {
                "type": "string",
                "enum": ["json", "markdown"],
                "default": "json",
            },
        },
    },
}


def curator_evidence_report(params: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Return a JSON string for Hermes tool calls."""
    payload = params or {}
    days = int(payload.get("days") or 7)
    days = max(1, min(days, 365))
    skill = payload.get("skill") or None
    output_format = payload.get("format") or "json"
    report = build_default_report(days=days, skill=skill)
    if output_format == "markdown":
        return json.dumps(
            {"success": True, "format": "markdown", "report": format_markdown_report(report)},
            ensure_ascii=False,
        )
    return json.dumps(
        {"success": True, "format": "json", "report": json.loads(format_json_report(report))},
        ensure_ascii=False,
    )
