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
from .backfill import backfill_sessions
from .candidates import mine_candidates
from .guarded_apply import apply_guarded_patch, rollback_guarded_patch
from .proposals import (
    build_model_drafted_proposal,
    build_skill_proposal,
    format_proposal_json,
    format_proposal_markdown,
    hermes_chat_backend,
)
from .reports import build_default_report, format_json_report, format_markdown_report
from .restore_drill import (
    format_drill_report,
    run_restore_drill,
)
from .review_queue import ReviewQueue
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

    candidates_mine = subs.add_parser(
        "candidates-mine",
        help="Read-only mine candidates from a redacted JSONL packet into a review queue",
    )
    candidates_mine.add_argument(
        "--input-jsonl", required=True, help="Path to redacted evidence JSONL file"
    )
    candidates_mine.add_argument(
        "--queue-db", required=True, help="SQLite review queue database path"
    )
    candidates_mine.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    candidates_mine.set_defaults(func=handle_cli)

    candidates_list = subs.add_parser(
        "candidates-list",
        help="List candidates from a review queue (read-only)",
    )
    candidates_list.add_argument(
        "--queue-db", required=True, help="SQLite review queue database path"
    )
    candidates_list.add_argument(
        "--status",
        choices=["pending", "accepted", "rejected"],
        help="Filter by status",
    )
    candidates_list.add_argument(
        "--candidate-type",
        choices=[
            "memory",
            "skill_update",
            "skill_new",
            "replay_benchmark",
            "ignore",
        ],
        help="Filter by candidate type",
    )
    candidates_list.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    candidates_list.set_defaults(func=handle_cli)

    apply_cmd = subs.add_parser("apply", help="Apply reviewed content with guardrails")
    apply_cmd.add_argument("--target", required=True, help="Target file to replace")
    apply_cmd.add_argument("--content-file", required=True, help="File containing reviewed new content")
    apply_cmd.add_argument("--expected-sha256", required=True, help="Expected current target SHA256")
    apply_cmd.add_argument("--backup-dir", default=".curator-evolver-backups", help="Backup root")
    apply_cmd.add_argument("--verify-command", help="Optional verification command")
    apply_cmd.add_argument("--verify-cwd", help="Working directory for verification command")
    apply_cmd.add_argument(
        "--pre-verify-command",
        help="Optional cheap pre-check command; implies --staged-verify",
    )
    apply_cmd.add_argument(
        "--staged-verify",
        action="store_true",
        help="Run built-in cheap structural check before any --verify-command",
    )
    apply_cmd.add_argument("--approve", action="store_true", help="Explicitly approve applying")
    apply_cmd.set_defaults(func=handle_cli)

    rollback = subs.add_parser("rollback", help="Rollback from a guarded apply manifest")
    rollback.add_argument("--manifest", required=True, help="Path to manifest.json")
    rollback.add_argument("--force", action="store_true", help="Rollback even if target changed after apply")
    rollback.set_defaults(func=handle_cli)

    restore_drill = subs.add_parser(
        "restore-drill",
        help="Non-destructive restore drill: replay a rollback manifest into a clean dir and report",
    )
    restore_drill.add_argument("--manifest", required=True, help="Path to manifest.json from a prior guarded apply")
    restore_drill.add_argument(
        "--target-dir",
        help="Optional drill destination directory (default: a fresh temp dir)",
    )
    restore_drill.add_argument(
        "--state-file",
        help="Optional path to the restore-drill state JSON (default: <backup_root>/restore-drill-state.json)",
    )
    restore_drill.add_argument(
        "--format", choices=["markdown", "json"], default="json", help="Output format"
    )
    restore_drill.set_defaults(func=handle_cli)

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
    auto_run.add_argument("--apply-low-risk", action="store_true", help="Apply low-risk bounded managed updates")
    auto_run.add_argument(
        "--approve-auto-apply",
        action="store_true",
        help="Required with --apply-low-risk before any file writes occur",
    )
    auto_run.add_argument(
        "--protect-core-skills",
        dest="protect_core_skills",
        action="store_true",
        default=True,
        help="Skip unattended writes to core Hermes/workflow skills (default)",
    )
    auto_run.add_argument(
        "--no-protect-core-skills",
        dest="protect_core_skills",
        action="store_false",
        help="Allow unattended writes to core skills; use only after explicit review",
    )
    auto_run.add_argument(
        "--allow-auto-apply-skill",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern that may auto-apply within the local agent-created source boundary; also explicitly permits matching core skills",
    )
    auto_run.add_argument(
        "--block-auto-apply-skill",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern that must never auto-apply in unattended mode",
    )
    auto_run.add_argument("--verify-command", help="Optional command to validate after each apply")
    auto_run.add_argument("--verify-cwd", help="Working directory for verification command")
    auto_run.add_argument(
        "--pre-verify-command",
        help="Optional cheap pre-check command; runs before --verify-command and implies --staged-verify",
    )
    auto_run.add_argument(
        "--staged-verify",
        action="store_true",
        help="Run built-in cheap structural check before any verify command (auto-on when --pre-verify-command is set)",
    )
    auto_run.add_argument(
        "--variants",
        type=int,
        default=1,
        help="Deterministically generate N bounded variants per skill (1-4) and pick a winner; default 1 preserves prior behavior",
    )
    auto_run.add_argument(
        "--require-restore-drill",
        action="store_true",
        help="Refuse mutating auto-apply if the last guarded apply has no matching successful restore drill (default: warn only)",
    )
    auto_run.add_argument(
        "--restore-drill-state-file",
        help="Override the path to the restore-drill state JSON (default: <backup_root>/restore-drill-state.json)",
    )
    auto_run.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    auto_run.set_defaults(func=handle_cli)

    bootstrap = subs.add_parser(
        "bootstrap",
        help="One-command setup: backfill sessions and install the auto-run scheduler",
    )
    bootstrap.add_argument("--days", type=int, default=30, help="Historical session backfill window")
    bootstrap.add_argument("--sessions-dir", help="Hermes sessions directory (default: ~/.hermes/sessions)")
    bootstrap.add_argument("--skills-dir", help="Skills root for the scheduler command (default: ~/.hermes/skills)")
    bootstrap.add_argument(
        "--schedule",
        default="daily",
        help="Scheduler cadence: hourly/daily/weekly; Linux also accepts systemd OnCalendar values",
    )
    bootstrap.add_argument("--proposal-only", action="store_true", help="Install dry-run scheduler instead of applying low-risk updates")
    bootstrap.add_argument(
        "--semantic",
        action="store_true",
        help="Shortcut for semantic + rerank scheduler candidate ordering (explicit model opt-in)",
    )
    bootstrap.add_argument(
        "--semantic-candidates",
        action="store_true",
        help="Scheduler uses embedding-backed candidate ordering",
    )
    bootstrap.add_argument(
        "--rerank-candidates",
        action="store_true",
        help="Scheduler uses reranker-backed candidate ordering; implies --semantic-candidates",
    )
    bootstrap.add_argument(
        "--enable",
        dest="enable",
        action="store_true",
        default=True,
        help="Enable and start the scheduler now (default)",
    )
    bootstrap.add_argument(
        "--no-enable",
        dest="enable",
        action="store_false",
        help="Write scheduler files without enabling them",
    )
    bootstrap.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    bootstrap.set_defaults(func=handle_cli)

    backfill = subs.add_parser("backfill-sessions", help="Import historical Hermes session transcripts into evidence")
    backfill.add_argument("--sessions-dir", help="Hermes sessions directory (default: ~/.hermes/sessions)")
    backfill.add_argument("--days", type=int, default=30, help="Only import sessions from this many days")
    backfill.add_argument("--limit", type=int, help="Maximum number of newest session files to inspect")
    backfill.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    backfill.set_defaults(func=handle_cli)

    install_auto = subs.add_parser("install-auto", help="Install a user scheduler for auto-run")
    install_auto.add_argument(
        "--schedule",
        default="daily",
        help="Scheduler cadence: hourly/daily/weekly; Linux also accepts systemd OnCalendar values",
    )
    install_auto.add_argument("--skills-dir", help="Skills root for the scheduler command")
    install_auto.add_argument("--proposal-only", action="store_true", help="Scheduler runs dry-run instead of applying low-risk updates")
    install_auto.add_argument(
        "--protect-core-skills",
        dest="protect_core_skills",
        action="store_true",
        default=True,
        help="Scheduler skips unattended writes to core Hermes/workflow skills (default)",
    )
    install_auto.add_argument(
        "--no-protect-core-skills",
        dest="protect_core_skills",
        action="store_false",
        help="Scheduler may write core skills; use only after explicit review",
    )
    install_auto.add_argument(
        "--allow-auto-apply-skill",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Scheduler auto-apply allowlist glob within the local agent-created source boundary; matching core skills are explicitly permitted",
    )
    install_auto.add_argument(
        "--block-auto-apply-skill",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Scheduler auto-apply blocklist glob",
    )
    install_auto.add_argument(
        "--semantic-candidates",
        action="store_true",
        help="Scheduler uses embedding-backed candidate ordering; opt-in because it may load models",
    )
    install_auto.add_argument(
        "--rerank-candidates",
        action="store_true",
        help="Scheduler uses reranker-backed candidate ordering; implies --semantic-candidates",
    )
    install_auto.add_argument(
        "--no-verify-skills",
        dest="verify_skills",
        action="store_false",
        default=True,
        help="Disable the built-in post-apply SKILL.md validator in the scheduler",
    )
    install_auto.add_argument("--verify-command", help="Custom command to validate after each scheduler apply")
    install_auto.add_argument("--verify-cwd", help="Working directory for scheduler verification command")
    install_auto.add_argument("--enable", action="store_true", help="Enable and start the scheduler now")
    install_auto.set_defaults(func=handle_cli)

    uninstall_auto = subs.add_parser("uninstall-auto", help="Remove the user auto-run scheduler")
    uninstall_auto.add_argument("--keep-enabled", action="store_true", help="Do not disable/unload scheduler before removing files")
    uninstall_auto.set_defaults(func=handle_cli)

    subparser.set_defaults(func=handle_cli)


def _bounded_days(value: int | None, default: int = 7) -> int:
    return max(1, min(int(value or default), 3650))


def _emit(text: str, output: str | None = None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text)


def _format_bootstrap_result(result: dict, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)

    backfill = result["backfill"]
    timer = result["auto_timer"]
    lines = [
        "Hermes Curator Evolver bootstrap",
        f"✓ Backfilled {backfill.get('sessions_imported', 0)} session(s), "
        f"{backfill.get('tool_events_imported', 0)} tool event(s)",
        f"✓ Scheduler installed: {timer.get('schedule')} "
        f"({'enabled' if timer.get('enabled') else 'not enabled'})",
        f"✓ Auto-apply policy: {timer.get('auto_apply_policy', 'local-agent-created-skills-only')}",
        "Next:",
    ]
    lines.extend(f"- {item}" for item in result["next_steps"])
    return "\n".join(lines)


def _run_bootstrap(values: dict) -> dict:
    semantic_requested = bool(
        values.get("semantic") or values.get("semantic_candidates") or values.get("rerank_candidates")
    )
    rerank_requested = bool(values.get("semantic") or values.get("rerank_candidates"))
    backfill_result = backfill_sessions(
        sessions_dir=values.get("sessions_dir"),
        days=_bounded_days(values.get("days"), 30),
        limit=None,
    )
    timer_result = install_auto_timer(
        schedule=values.get("schedule") or "daily",
        skills_dir=values.get("skills_dir"),
        apply_low_risk=not bool(values.get("proposal_only")),
        enable=bool(values.get("enable")),
        semantic_candidates=semantic_requested or rerank_requested,
        rerank_candidates=rerank_requested,
        protect_core_skills=True,
        auto_apply_allowlist=(),
        auto_apply_blocklist=(),
        verify_skills=True,
    )
    return {
        "schema_version": "0.10",
        "mode": "bootstrap",
        "backfill": backfill_result,
        "auto_timer": timer_result,
        "semantic_requested": semantic_requested,
        "rerank_requested": rerank_requested,
        "next_steps": [
            "Restart Hermes gateway/CLI if it was already running so plugin hooks are loaded.",
            "Run `hermes-curator-evolver status` to inspect evidence counts.",
            "Run `hermes-curator-evolver auto-run --skills-dir ~/.hermes/skills --format json` for a dry-run preview.",
        ],
    }


def _load_jsonl_records(path: str | Path) -> list[dict]:
    records: list[dict] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _candidate_to_payload(candidate) -> dict:
    return {
        "id": candidate.id,
        "candidate_type": candidate.candidate_type,
        "title": candidate.title,
        "rationale": candidate.rationale,
        "confidence": float(candidate.confidence),
        "evidence_refs": list(candidate.evidence_refs),
        "target_skill": candidate.target_skill,
        "auto_apply_allowed": bool(candidate.auto_apply_allowed),
        "requires_human_review": bool(candidate.requires_human_review),
        "metadata": dict(candidate.metadata or {}),
    }


def _run_candidates_mine(*, input_jsonl: str, queue_db: str) -> dict:
    records = _load_jsonl_records(input_jsonl)
    queue = ReviewQueue(queue_db)
    payloads: list[dict] = []
    inserted = 0
    duplicates = 0
    for candidate in mine_candidates(records):
        payload = _candidate_to_payload(candidate)
        payload["enqueued"] = queue.enqueue(candidate)
        if payload["enqueued"]:
            inserted += 1
        else:
            duplicates += 1
        payloads.append(payload)
    return {
        "schema_version": "0.1",
        "queue_db": str(Path(queue_db).resolve()),
        "input_jsonl": str(Path(input_jsonl).resolve()),
        "count": len(payloads),
        "inserted": inserted,
        "duplicates": duplicates,
        "candidates": payloads,
    }


def _run_candidates_list(
    *,
    queue_db: str,
    status: str | None,
    candidate_type: str | None,
) -> dict:
    queue = ReviewQueue(queue_db, create=False)
    rows = queue.list_candidates(status=status, candidate_type=candidate_type)

    return {
        "schema_version": "0.1",
        "queue_db": str(Path(queue_db).resolve()),
        "status_filter": status,
        "candidate_type_filter": candidate_type,
        "count": len(rows),
        "candidates": rows,
    }


def _format_candidates_payload(result: dict, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    lines = [
        "# Curator Evolver Candidates",
        "",
        "_Read-only review queue. No files were changed and human review is required._",
        "",
        f"- Queue: `{result.get('queue_db')}`",
        f"- Count: {result.get('count', 0)}",
    ]
    if "inserted" in result:
        lines.append(f"- Newly inserted: {result['inserted']}")
        lines.append(f"- Duplicates ignored: {result['duplicates']}")
    if result.get("status_filter"):
        lines.append(f"- Status filter: {result['status_filter']}")
    if result.get("candidate_type_filter"):
        lines.append(f"- Type filter: {result['candidate_type_filter']}")
    lines.append("")
    for item in result.get("candidates", []) or []:
        lines.append(f"## {item.get('title') or item.get('id')}")
        lines.append(f"- type: `{item.get('candidate_type')}`")
        if "status" in item:
            lines.append(f"- status: `{item.get('status')}`")
        lines.append(
            f"- requires human review: {bool(item.get('requires_human_review', True))}"
        )
        lines.append(
            f"- auto-apply allowed: {bool(item.get('auto_apply_allowed', False))}"
        )
        if item.get("target_skill"):
            lines.append(f"- target skill: `{item['target_skill']}`")
        lines.append(f"- confidence: {float(item.get('confidence', 0)):.2f}")
        rationale = (item.get("rationale") or "").strip()
        if rationale:
            lines.append(f"- rationale: {rationale}")
        evidence = item.get("evidence_refs") or []
        if evidence:
            lines.append(f"- evidence: {', '.join(str(e) for e in evidence)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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

    if command == "candidates-mine":
        result = _run_candidates_mine(
            input_jsonl=values["input_jsonl"],
            queue_db=values["queue_db"],
        )
        print(_format_candidates_payload(result, output_format=values.get("format") or "json"))
        return

    if command == "candidates-list":
        result = _run_candidates_list(
            queue_db=values["queue_db"],
            status=values.get("status"),
            candidate_type=values.get("candidate_type"),
        )
        print(_format_candidates_payload(result, output_format=values.get("format") or "json"))
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
            pre_verify_command=values.get("pre_verify_command"),
            staged_verify=bool(values.get("staged_verify") or values.get("pre_verify_command")),
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
                pre_verify_command=values.get("pre_verify_command"),
                staged_verify=bool(values.get("staged_verify") or values.get("pre_verify_command")),
                protect_core_skills=bool(values.get("protect_core_skills")),
                auto_apply_allowlist=tuple(values.get("allow_auto_apply_skill") or ()),
                auto_apply_blocklist=tuple(values.get("block_auto_apply_skill") or ()),
                variants=int(values.get("variants") or 1),
                require_restore_drill=bool(values.get("require_restore_drill")),
                restore_drill_state_path=values.get("restore_drill_state_file"),
            )
        )
        print(format_auto_evolve_result(result, output_format=values.get("format") or "markdown"))
        return

    if command == "restore-drill":
        report = run_restore_drill(
            values["manifest"],
            target_dir=values.get("target_dir"),
            state_path=values.get("state_file"),
        )
        print(format_drill_report(report, output_format=values.get("format") or "json"))
        return

    if command == "bootstrap":
        result = _run_bootstrap(values)
        print(_format_bootstrap_result(result, output_format=values.get("format") or "text"))
        return

    if command == "backfill-sessions":
        result = backfill_sessions(
            sessions_dir=values.get("sessions_dir"),
            days=_bounded_days(values.get("days"), 30),
            limit=values.get("limit"),
        )
        if values.get("format") == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("Hermes Curator Evolver session backfill")
            print(f"Sessions dir: {result['sessions_dir']}")
            print(f"DB: {result['db_path']}")
            print(f"Sessions seen: {result['sessions_seen']}")
            print(f"Sessions imported: {result['sessions_imported']}")
            print(f"Skipped old sessions: {result['sessions_skipped_old']}")
            print(f"Failed files: {result['files_failed']}")
            print(f"Tool events imported: {result['tool_events_imported']}")
            print(f"Turn events imported: {result['turn_events_imported']}")
            print(f"Session events imported: {result['session_events_imported']}")
        return

    if command == "install-auto":
        result = install_auto_timer(
            schedule=values.get("schedule") or "daily",
            skills_dir=values.get("skills_dir"),
            apply_low_risk=not bool(values.get("proposal_only")),
            enable=bool(values.get("enable")),
            semantic_candidates=bool(values.get("semantic_candidates") or values.get("rerank_candidates")),
            rerank_candidates=bool(values.get("rerank_candidates")),
            protect_core_skills=bool(values.get("protect_core_skills")),
            auto_apply_allowlist=tuple(values.get("allow_auto_apply_skill") or ()),
            auto_apply_blocklist=tuple(values.get("block_auto_apply_skill") or ()),
            verify_command=values.get("verify_command"),
            verify_cwd=values.get("verify_cwd"),
            verify_skills=bool(values.get("verify_skills")),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if command == "uninstall-auto":
        result = uninstall_auto_timer(disable=not bool(values.get("keep_enabled")))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
