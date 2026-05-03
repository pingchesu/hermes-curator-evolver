"""CLI integration for `hermes curator-evolver`."""

from __future__ import annotations

import argparse

from .reports import build_default_report, format_json_report, format_markdown_report
from .storage import EvidenceStore


def setup_cli(subparser: argparse.ArgumentParser) -> None:
    """Build argparse tree for Hermes plugin CLI registration."""
    subs = subparser.add_subparsers(dest="curator_evolver_command")

    status = subs.add_parser("status", help="Show evidence store status")
    status.set_defaults(func=handle_cli)

    report = subs.add_parser("report", help="Show aggregate read-only evidence report")
    report.add_argument("--days", type=int, default=7, help="Lookback window in days")
    report.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    report.set_defaults(func=handle_cli)

    analyze = subs.add_parser("analyze", help="Show per-skill read-only evidence")
    analyze.add_argument("--skill", required=True, help="Exact skill name to analyze")
    analyze.add_argument("--days", type=int, default=30, help="Lookback window in days")
    analyze.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    analyze.set_defaults(func=handle_cli)

    subparser.set_defaults(func=handle_cli)


def handle_cli(args: argparse.Namespace) -> None:
    """Dispatch CLI commands."""
    values = vars(args)
    command = values.get("curator_evolver_command") or "status"
    if command == "status":
        store = EvidenceStore()
        summary = store.summary(days=3650)
        print("Hermes Curator Evolver")
        print(f"DB: {store.db_path}")
        print(f"Tool events: {summary['tool_events']}")
        print(f"Skill events: {summary['skill_events']}")
        print(f"Error-like events: {summary['error_events']}")
        print("Mode: read-only evidence collection")
        return

    days = int(values.get("days") or 7)
    days = max(1, min(days, 3650))
    skill = values.get("skill") if command == "analyze" else None
    report = build_default_report(days=days, skill=skill)
    if values.get("format") == "json":
        print(format_json_report(report))
    else:
        print(format_markdown_report(report))
