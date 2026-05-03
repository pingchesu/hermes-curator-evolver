"""CLI integration for `hermes curator-evolver`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .auto_evolve import (
    AutoEvolveConfig,
    format_auto_evolve_result,
    install_auto_timer,
    run_auto_evolve,
    uninstall_auto_timer,
)
from .guarded_apply import apply_guarded_patch, rollback_guarded_patch
from .proposals import (
    build_model_drafted_proposal,
    build_skill_proposal,
    format_proposal_json,
    format_proposal_markdown,
    hermes_chat_backend,
)
from .reports import build_default_report, format_json_report, format_markdown_report
from .semantic import find_skill_candidates
from .storage import EvidenceStore
from .verifier import verify_proposal


def setup_cli(subparser: argparse.ArgumentParser) -> None:
    """Build argparse tree for Hermes plugin CLI registration."""
    subs = subparser.add_subparsers(dest="curator_evolver_command")

    status = subs.add_parser("status", help="Show evidence store status")
    status.set_defaults(func=handle_cli)

    report = subs.add_parser("report", help="Show aggregate evidence report")
    report.add_argument("--days", type=int, default=7, help="Lookback window in days")
    report.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    report.set_defaults(func=handle_cli)

    analyze = subs.add_parser("analyze", help="Show per-skill evidence")
    analyze.add_argument("--skill", required=True, help="Exact skill name to analyze")
    analyze.add_argument("--days", type=int, default=30, help="Lookback window in days")
    analyze.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    analyze.set_defaults(func=handle_cli)

    propose = subs.add_parser("propose", help="Generate a dry-run skill proposal")
    propose.add_argument("--skill", required=True, help="Exact skill name")
    propose.add_argument("--skill-file", help="Path to current SKILL.md text")
    propose.add_argument("--days", type=int, default=30, help="Lookback window in days")
    propose.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    propose.add_argument("--output", help="Optional output file")
    propose.add_argument(
        "--draft-with-model",
        action="store_true",
        help="Call the current Hermes chat model for draft text (still dry-run)",
    )
    propose.add_argument("--model-timeout", type=int, default=180, help="Hermes chat draft timeout seconds")
    propose.set_defaults(func=handle_cli)

    verify = subs.add_parser("verify", help="Verify a dry-run proposal")
    verify.add_argument("--proposal-file", required=True, help="JSON proposal file")
    verify.add_argument("--skill", help="Skill filter for evidence report")
    verify.add_argument("--days", type=int, default=30, help="Lookback window in days")
    verify.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    verify.set_defaults(func=handle_cli)

    candidates = subs.add_parser("candidates", help="Find candidate skills for review")
    candidates.add_argument("--query", required=True, help="Evidence/query text")
    candidates.add_argument("--skills-dir", required=True, help="Directory containing SKILL.md files")
    candidates.add_argument("--semantic", action="store_true", help="Show semantic model plan")
    candidates.add_argument(
        "--execute-semantic",
        action="store_true",
        help="Actually load and execute the embedding model for semantic ranking",
    )
    candidates.add_argument(
        "--rerank",
        action="store_true",
        help="When semantic execution is enabled, also load and execute the reranker",
    )
    candidates.add_argument("--limit", type=int, default=10, help="Max candidates")
    candidates.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    candidates.set_defaults(func=handle_cli)

    apply_cmd = subs.add_parser("apply", help="Apply reviewed content with guardrails")
    apply_cmd.add_argument("--target", required=True, help="Target file to replace")
    apply_cmd.add_argument("--content-file", required=True, help="File containing reviewed new content")
    apply_cmd.add_argument("--expected-sha256", required=True, help="Expected current target SHA256")
    apply_cmd.add_argument("--backup-dir", default=".curator-evolver-backups", help="Backup root")
    apply_cmd.add_argument("--verify-command", help="Optional verification command")
    apply_cmd.add_argument("--verify-cwd", help="Working directory for verification command")
    apply_cmd.add_argument("--approve", action="store_true", help="Explicitly approve applying")
    apply_cmd.set_defaults(func=handle_cli)

    rollback = subs.add_parser("rollback", help="Rollback from a guarded apply manifest")
    rollback.add_argument("--manifest", required=True, help="Path to manifest.json")
    rollback.add_argument("--force", action="store_true", help="Rollback even if target changed after apply")
    rollback.set_defaults(func=handle_cli)

    auto_run = subs.add_parser("auto-run", help="Run one automatic low-risk evolution pass")
    auto_run.add_argument("--days", type=int, default=7, help="Lookback window in days")
    auto_run.add_argument("--skills-dir", help="Skills root (default: ~/.hermes/skills)")
    auto_run.add_argument("--backup-dir", help="Backup root for guarded apply")
    auto_run.add_argument("--max-skills", type=int, default=3, help="Max skills to consider")
    auto_run.add_argument("--min-evidence", type=int, default=2, help="Minimum skill evidence count")
    auto_run.add_argument(
        "--semantic-candidates",
        action="store_true",
        help="Opt into embedding-backed candidate ordering for this auto-run pass",
    )
    auto_run.add_argument(
        "--rerank-candidates",
        action="store_true",
        help="Opt into reranker-backed candidate ordering; implies --semantic-candidates",
    )
    auto_run.add_argument("--apply-low-risk", action="store_true", help="Apply low-risk append-only updates")
    auto_run.add_argument(
        "--approve-auto-apply",
        action="store_true",
        help="Required with --apply-low-risk before any file writes occur",
    )
    auto_run.add_argument("--verify-command", help="Optional command to validate after each apply")
    auto_run.add_argument("--verify-cwd", help="Working directory for verification command")
    auto_run.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    auto_run.set_defaults(func=handle_cli)

    install_auto = subs.add_parser("install-auto", help="Install a user systemd timer for auto-run")
    install_auto.add_argument("--schedule", default="daily", help="systemd OnCalendar value or hourly/daily/weekly")
    install_auto.add_argument("--skills-dir", help="Skills root for the timer command")
    install_auto.add_argument("--proposal-only", action="store_true", help="Timer runs dry-run instead of applying low-risk updates")
    install_auto.add_argument(
        "--semantic-candidates",
        action="store_true",
        help="Timer uses embedding-backed candidate ordering; opt-in because it may load models",
    )
    install_auto.add_argument(
        "--rerank-candidates",
        action="store_true",
        help="Timer uses reranker-backed candidate ordering; implies --semantic-candidates",
    )
    install_auto.add_argument("--enable", action="store_true", help="Enable and start the timer now")
    install_auto.set_defaults(func=handle_cli)

    uninstall_auto = subs.add_parser("uninstall-auto", help="Remove the user systemd auto-run timer")
    uninstall_auto.add_argument("--keep-enabled", action="store_true", help="Do not call systemctl disable --now before removing files")
    uninstall_auto.set_defaults(func=handle_cli)

    subparser.set_defaults(func=handle_cli)


def _bounded_days(value: int | None, default: int = 7) -> int:
    return max(1, min(int(value or default), 3650))


def _emit(text: str, output: str | None = None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text)


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
        print("Mode: evidence collection + automatic low-risk evolution + guarded apply")
        return

    if command in {"report", "analyze"}:
        days = _bounded_days(values.get("days"), 7)
        skill = values.get("skill") if command == "analyze" else None
        report = build_default_report(days=days, skill=skill)
        if values.get("format") == "json":
            print(format_json_report(report))
        else:
            print(format_markdown_report(report))
        return

    if command == "propose":
        days = _bounded_days(values.get("days"), 30)
        skill = str(values["skill"])
        skill_file = values.get("skill_file")
        skill_text = Path(skill_file).read_text(encoding="utf-8") if skill_file else ""
        report = build_default_report(days=days, skill=skill)
        if values.get("draft_with_model"):
            timeout = int(values.get("model_timeout") or 180)
            proposal = build_model_drafted_proposal(
                report,
                skill_name=skill,
                skill_text=skill_text,
                chat_backend=lambda prompt: hermes_chat_backend(prompt, timeout_seconds=timeout),
            )
        else:
            proposal = build_skill_proposal(report, skill_name=skill, skill_text=skill_text)
        text = format_proposal_json(proposal) if values.get("format") == "json" else format_proposal_markdown(proposal)
        _emit(text, values.get("output"))
        return

    if command == "verify":
        proposal = json.loads(Path(values["proposal_file"]).read_text(encoding="utf-8"))
        report = build_default_report(days=_bounded_days(values.get("days"), 30), skill=values.get("skill"))
        verdict = verify_proposal(proposal, report)
        if values.get("format") == "json":
            print(json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            status = "PASSED" if verdict["passed"] else "FAILED"
            print(f"Verifier: {status}")
            if verdict["failures"]:
                print("Failures: " + ", ".join(verdict["failures"]))
        return

    if command == "candidates":
        result = find_skill_candidates(
            query=str(values["query"]),
            skills_dir=values["skills_dir"],
            semantic=bool(values.get("semantic") or values.get("execute_semantic")),
            limit=int(values.get("limit") or 10),
            load_models=bool(values.get("execute_semantic")),
            load_reranker=bool(values.get("rerank")),
        )
        if values.get("format") == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"Mode: {result['mode']}")
            print(f"Models: {result['models']}")
            for item in result["candidates"]:
                print(f"- {item['skill_name']} score={item['score']} reasons={', '.join(item['reasons'])}")
        return

    if command == "apply":
        result = apply_guarded_patch(
            target_path=values["target"],
            new_content=Path(values["content_file"]).read_text(encoding="utf-8"),
            expected_sha256=values["expected_sha256"],
            approved=bool(values.get("approve")),
            backup_root=values.get("backup_dir") or ".curator-evolver-backups",
            verify_command=values.get("verify_command"),
            verify_cwd=values.get("verify_cwd"),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if command == "rollback":
        result = rollback_guarded_patch(values["manifest"], force=bool(values.get("force")))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if command == "auto-run":
        result = run_auto_evolve(
            AutoEvolveConfig(
                skills_dir=values.get("skills_dir"),
                backup_dir=values.get("backup_dir"),
                days=_bounded_days(values.get("days"), 7),
                max_skills=int(values.get("max_skills") or 3),
                min_evidence=int(values.get("min_evidence") or 2),
                apply_low_risk=bool(values.get("apply_low_risk")),
                approve_auto_apply=bool(values.get("approve_auto_apply")),
                semantic_candidates=bool(values.get("semantic_candidates") or values.get("rerank_candidates")),
                rerank_candidates=bool(values.get("rerank_candidates")),
                verify_command=values.get("verify_command"),
                verify_cwd=values.get("verify_cwd"),
            )
        )
        print(format_auto_evolve_result(result, output_format=values.get("format") or "markdown"))
        return

    if command == "install-auto":
        result = install_auto_timer(
            schedule=values.get("schedule") or "daily",
            skills_dir=values.get("skills_dir"),
            apply_low_risk=not bool(values.get("proposal_only")),
            enable=bool(values.get("enable")),
            semantic_candidates=bool(values.get("semantic_candidates") or values.get("rerank_candidates")),
            rerank_candidates=bool(values.get("rerank_candidates")),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if command == "uninstall-auto":
        result = uninstall_auto_timer(disable=not bool(values.get("keep_enabled")))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
