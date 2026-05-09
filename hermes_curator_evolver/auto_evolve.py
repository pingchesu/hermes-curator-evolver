"""Automatic, low-risk skill evolution loop.

This module is intentionally self-contained so the plugin can improve skills
without patching Hermes core. The safe mutation policy is append-only: generate a
managed evidence-backed section, preserve the existing skill text, then apply via
hash/backup/verification guardrails.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .guarded_apply import apply_guarded_patch, sha256_file
from .reports import build_report
from .semantic import find_skill_candidates
from .skill_sources import (
    SOURCE_LOCAL_AGENT_CREATED,
    build_skill_source_context,
    classify_skill_source,
)
from .storage import EvidenceStore

_START = "<!-- curator-evolver:auto:start -->"
_END = "<!-- curator-evolver:auto:end -->"
_FRONTMATTER_NAME_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*[\"']?(?P<name>[^\"'\n]+)[\"']?\s*$", re.MULTILINE)
_PIN_RE = re.compile(r"^(?:pin|pinned):\s*(?:true|yes|1)\s*$", re.IGNORECASE | re.MULTILINE)

# Skills in these families steer Hermes itself, coding workflow, skill loading,
# or repo/PR operations. They may still be analyzed and proposed, but unattended
# auto-apply skips them unless an operator explicitly allowlists a skill/pattern.
_DEFAULT_CORE_AUTO_APPLY_PROTECTED_PATTERNS: tuple[str, ...] = (
    "hermes-agent",
    "hermes-*",
    "gsd-*",
    "github-*",
    "mcp-*",
    "native-mcp",
    "claude-code",
    "codex",
    "opencode",
    "subagent-*",
    "systematic-debugging",
    "test-driven-development",
    "debugging-hermes-*",
    "requesting-code-review",
)


@dataclass(frozen=True)
class AutoEvolveConfig:
    """Configuration for one automatic evolution pass."""

    db_path: str | Path | None = None
    skills_dir: str | Path | None = None
    backup_dir: str | Path | None = None
    days: int = 7
    max_skills: int = 3
    min_evidence: int = 2
    apply_low_risk: bool = False
    approve_auto_apply: bool = False
    verify_command: str | None = None
    verify_cwd: str | Path | None = None
    semantic_candidates: bool = False
    rerank_candidates: bool = False
    embedding_backend: Any | None = None
    reranker_backend: Any | None = None
    protect_core_skills: bool = True
    auto_apply_allowlist: tuple[str, ...] = ()
    auto_apply_blocklist: tuple[str, ...] = ()


def _default_skills_dir() -> Path:
    return Path.home() / ".hermes" / "skills"


def _default_backup_dir() -> Path:
    return Path.home() / ".hermes" / "plugins" / "curator-evolver" / "backups"


def _bounded(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def _skill_name_from_text(text: str, fallback: str) -> str:
    match = _FRONTMATTER_NAME_RE.match(text)
    if match:
        name_match = _NAME_RE.search(match.group("body"))
        if name_match:
            return name_match.group("name").strip()
    return fallback


def _skill_is_pinned(text: str) -> bool:
    match = _FRONTMATTER_NAME_RE.match(text)
    return bool(match and _PIN_RE.search(match.group("body")))


def _normalize_patterns(patterns: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    return tuple(str(pattern).strip() for pattern in (patterns or ()) if str(pattern).strip())


def _systemd_quote(value: str) -> str:
    """Quote one systemd ExecStart argument while keeping the command readable."""

    return '"' + value.replace('\\', '\\\\').replace('"', '\"') + '"'


def _skill_matches_any_pattern(skill_name: str, patterns: tuple[str, ...] | list[str] | None) -> bool:
    normalized_name = skill_name.casefold()
    for pattern in _normalize_patterns(patterns):
        if fnmatch.fnmatchcase(normalized_name, pattern.casefold()):
            return True
    return False


def _auto_apply_skip_reason(*, skill_name: str, cfg: AutoEvolveConfig) -> str | None:
    """Return why unattended apply should not write this skill, if blocked."""

    allowlist = _normalize_patterns(cfg.auto_apply_allowlist)
    blocklist = _normalize_patterns(cfg.auto_apply_blocklist)
    if _skill_matches_any_pattern(skill_name, blocklist):
        return "auto-apply-blocklisted"
    allowlisted = _skill_matches_any_pattern(skill_name, allowlist)
    if allowlist and not allowlisted:
        return "auto-apply-not-allowlisted"
    if (
        cfg.protect_core_skills
        and _skill_matches_any_pattern(skill_name, _DEFAULT_CORE_AUTO_APPLY_PROTECTED_PATTERNS)
        and not allowlisted
    ):
        return "core-skill-auto-apply-protected"
    return None


def protected_core_auto_apply_patterns() -> tuple[str, ...]:
    """Return default core-skill patterns protected from unattended writes."""

    return _DEFAULT_CORE_AUTO_APPLY_PROTECTED_PATTERNS


def discover_skill_files(skills_dir: str | Path) -> dict[str, Path]:
    """Return top-level skill names mapped to their SKILL.md files."""

    root = Path(skills_dir)
    if not root.exists():
        return {}
    discovered: dict[str, Path] = {}
    for skill_file in sorted(root.rglob("SKILL.md")):
        if any(part in {".archive", ".curator_backups", ".hub"} for part in skill_file.parts):
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        name = _skill_name_from_text(text, skill_file.parent.name)
        discovered[name] = skill_file
    return discovered


def _format_evidence_rows(evidence_rows: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for row in evidence_rows[:limit]:
        marker = "error" if row.get("is_error") else "ok"
        preview = str(row.get("result_preview") or "").replace("\n", " ").strip()
        if len(preview) > 220:
            preview = preview[:219] + "…"
        created = row.get("created_at") or "unknown-time"
        tool = row.get("tool_name") or "unknown-tool"
        suffix = f" — {preview}" if preview else ""
        lines.append(f"- {created}: `{tool}` {marker}{suffix}")
    return lines


def _managed_block(
    *,
    skill_name: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    evidence_lines = _format_evidence_rows(evidence_rows)
    if not evidence_lines:
        evidence_lines = ["- No individual evidence rows were available; aggregate counts triggered this pass."]
    return "\n".join(
        [
            _START,
            "## Auto-curated evidence notes",
            "",
            "Low-risk append-only auto-curation generated by `hermes-curator-evolver`.",
            "These notes are evidence summaries for future agents; they do not replace human-authored SOPs.",
            "",
            f"- Skill: `{skill_name}`",
            f"- Generated at: `{generated_at}`",
            f"- Evidence window: last {days} day(s)",
            f"- Tool events: {int(summary.get('tool_events') or 0)}",
            f"- Skill events: {int(summary.get('skill_events') or 0)}",
            f"- Error-like events: {int(summary.get('error_events') or 0)}",
            "",
            "### Recent evidence",
            *evidence_lines,
            "",
            "### Agent guidance",
            "- When this skill is relevant, check these observed signals before choosing a workflow.",
            "- Prefer targeted verification over broad retries when similar errors recur.",
            "- If a repeated issue is understood, replace this evidence note with a concise human-readable SOP update.",
            _END,
            "",
        ]
    )


def build_low_risk_skill_update(
    *,
    skill_name: str,
    skill_text: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> str:
    """Return an append-only managed update that preserves existing skill text."""

    block = _managed_block(
        skill_name=skill_name,
        days=days,
        summary=summary,
        evidence_rows=evidence_rows,
    )
    if _START in skill_text and _END in skill_text:
        pattern = re.compile(re.escape(_START) + r".*?" + re.escape(_END) + r"\n?", re.DOTALL)
        return pattern.sub(block, skill_text, count=1)
    separator = "\n" if skill_text.endswith("\n") else "\n\n"
    return skill_text + separator + block


def _eligible_skill_rows(report: dict[str, Any], *, min_evidence: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in report.get("summary", {}).get("skills", []) or []:
        count = int(row.get("event_count") or 0)
        name = row.get("skill_name")
        if name and count >= min_evidence:
            rows.append(dict(row))
    return rows


def _build_semantic_query(report: dict[str, Any], *, eligible_names: set[str], limit: int = 20) -> str:
    lines: list[str] = []
    for row in report.get("summary", {}).get("skills", []) or []:
        name = str(row.get("skill_name") or "")
        if name in eligible_names:
            lines.append(
                f"skill={name} events={int(row.get('event_count') or 0)} errors={int(row.get('errors') or 0)}"
            )
    for row in (report.get("skill_evidence") or [])[:limit]:
        name = str(row.get("skill_name") or "")
        if name not in eligible_names:
            continue
        preview = str(row.get("result_preview") or "").replace("\n", " ").strip()
        tool = str(row.get("tool_name") or "unknown-tool")
        lines.append(f"skill={name} tool={tool} result={preview}")
    if not lines:
        return " ".join(sorted(eligible_names)) or "Hermes skill evidence"
    return "\n".join(lines)


def _deterministic_selection_metadata(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("skill_name")): {
            "source": "evidence-threshold",
            "score": int(row.get("event_count") or 0),
            "reasons": [
                f"event_count={int(row.get('event_count') or 0)}",
                f"errors={int(row.get('errors') or 0)}",
            ],
        }
        for row in rows
        if row.get("skill_name")
    }


def _select_candidate_skill_names(
    *,
    report: dict[str, Any],
    skills_dir: Path,
    max_skills: int,
    min_evidence: int,
    semantic_candidates: bool,
    rerank_candidates: bool,
    embedding_backend: Any | None,
    reranker_backend: Any | None,
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    eligible_rows = _eligible_skill_rows(report, min_evidence=min_evidence)
    eligible_names = [str(row["skill_name"]) for row in eligible_rows]
    eligible_set = set(eligible_names)
    metadata = _deterministic_selection_metadata(eligible_rows)
    selection: dict[str, Any] = {
        "mode": "deterministic-evidence",
        "semantic_requested": bool(semantic_candidates or rerank_candidates),
        "rerank_requested": bool(rerank_candidates),
        "eligible_skill_count": len(eligible_names),
        "models": {"embedding": "not-used", "reranker": "not-used"},
    }

    if not eligible_names:
        return [], metadata, selection

    if not (semantic_candidates or rerank_candidates):
        return eligible_names[:max_skills], metadata, selection

    skill_file_count = len(discover_skill_files(skills_dir))
    if skill_file_count == 0:
        selection.update({"mode": "semantic-no-skill-files", "fallback": "deterministic-evidence"})
        return eligible_names[:max_skills], metadata, selection

    query = _build_semantic_query(report, eligible_names=eligible_set)
    semantic_result = find_skill_candidates(
        query=query,
        skills_dir=skills_dir,
        semantic=True,
        limit=max(skill_file_count, len(eligible_names), max_skills),
        embedding_backend=embedding_backend,
        reranker_backend=reranker_backend,
        load_models=embedding_backend is None,
        load_reranker=bool(rerank_candidates and reranker_backend is None),
    )
    selection.update(
        {
            "mode": semantic_result.get("mode") or "semantic-unavailable",
            "models": semantic_result.get("models") or selection["models"],
            "model_executed": bool(semantic_result.get("model_executed")),
            "reranker_executed": bool(semantic_result.get("reranker_executed")),
            "query_preview": query[:500],
        }
    )
    if semantic_result.get("error"):
        selection["error"] = semantic_result.get("error")

    ranked_names: list[str] = []
    for item in semantic_result.get("candidates") or []:
        name = str(item.get("skill_name") or "")
        if name not in eligible_set or name in ranked_names:
            continue
        ranked_names.append(name)
        metadata[name] = {
            "source": semantic_result.get("mode") or "semantic",
            "score": float(item.get("score") or 0.0),
            "reasons": list(item.get("reasons") or []),
            "embedding_score": item.get("embedding_score"),
        }
    for name in eligible_names:
        if name not in ranked_names:
            ranked_names.append(name)
    if not semantic_result.get("model_executed"):
        selection["fallback"] = "deterministic-evidence"
    return ranked_names[:max_skills], metadata, selection


def run_auto_evolve(config: AutoEvolveConfig | None = None) -> dict[str, Any]:
    """Run one automatic skill evolution pass.

    By default this is a dry-run. Actual writes require both `apply_low_risk` and
    `approve_auto_apply`; even then, writes are append-only and go through
    guarded apply.
    """

    cfg = config or AutoEvolveConfig()
    days = _bounded(cfg.days, minimum=1, maximum=3650)
    max_skills = _bounded(cfg.max_skills, minimum=1, maximum=25)
    min_evidence = _bounded(cfg.min_evidence, minimum=1, maximum=1000)
    skills_dir = Path(cfg.skills_dir) if cfg.skills_dir is not None else _default_skills_dir()
    backup_dir = Path(cfg.backup_dir) if cfg.backup_dir is not None else _default_backup_dir()
    store = EvidenceStore(cfg.db_path)
    report = build_report(store, days=days)
    skill_files = discover_skill_files(skills_dir)
    source_context = build_skill_source_context(skills_dir)
    names, selection_metadata, selection = _select_candidate_skill_names(
        report=report,
        skills_dir=skills_dir,
        max_skills=max_skills,
        min_evidence=min_evidence,
        semantic_candidates=bool(cfg.semantic_candidates),
        rerank_candidates=bool(cfg.rerank_candidates),
        embedding_backend=cfg.embedding_backend,
        reranker_backend=cfg.reranker_backend,
    )
    mode = "apply-low-risk" if cfg.apply_low_risk else "dry-run"
    candidates: list[dict[str, Any]] = []
    applied = 0

    for name in names:
        skill_file = skill_files.get(name)
        source_info = (
            classify_skill_source(skill_name=name, skill_file=skill_file, context=source_context)
            if skill_file
            else None
        )
        candidate: dict[str, Any] = {
            "skill_name": name,
            "risk": "low",
            "mutation_policy": "append-only-managed-block",
            "selection": selection_metadata.get(name, {"source": "unknown", "reasons": []}),
            "target_path": str(skill_file) if skill_file else None,
            "source": source_info.source if source_info else "missing",
            "source_writable": bool(source_info.writable) if source_info else False,
        }
        if not skill_file:
            candidate["status"] = "skipped"
            candidate["reason"] = "skill-file-not-found"
            candidates.append(candidate)
            continue
        original = skill_file.read_text(encoding="utf-8")
        if _skill_is_pinned(original):
            candidate["status"] = "skipped"
            candidate["reason"] = "pinned-skill"
            candidates.append(candidate)
            continue
        if cfg.apply_low_risk and cfg.approve_auto_apply:
            if source_info and source_info.source != SOURCE_LOCAL_AGENT_CREATED:
                candidate["status"] = "skipped"
                candidate["reason"] = "source-not-agent-created"
                candidates.append(candidate)
                continue
            skip_reason = _auto_apply_skip_reason(skill_name=name, cfg=cfg)
            if skip_reason:
                candidate["status"] = "skipped"
                candidate["reason"] = skip_reason
                candidates.append(candidate)
                continue
        skill_report = build_report(store, days=days, skill=name)
        skill_summary = skill_report.get("summary") or {}
        evidence_rows = skill_report.get("skill_evidence") or []
        updated = build_low_risk_skill_update(
            skill_name=name,
            skill_text=original,
            days=days,
            summary=skill_summary,
            evidence_rows=evidence_rows,
        )
        candidate.update(
            {
                "status": "planned",
                "current_sha256": sha256_file(skill_file),
                "new_content_changed": updated != original,
                "evidence_summary": {
                    "tool_events": int(skill_summary.get("tool_events") or 0),
                    "skill_events": int(skill_summary.get("skill_events") or 0),
                    "error_events": int(skill_summary.get("error_events") or 0),
                },
            }
        )
        if cfg.apply_low_risk:
            if not cfg.approve_auto_apply:
                candidate["apply_result"] = {
                    "applied": False,
                    "reason": "auto-approval-required",
                }
            else:
                apply_result = apply_guarded_patch(
                    target_path=skill_file,
                    new_content=updated,
                    expected_sha256=candidate["current_sha256"],
                    approved=True,
                    backup_root=backup_dir,
                    verify_command=cfg.verify_command,
                    verify_cwd=cfg.verify_cwd or skills_dir,
                )
                candidate["apply_result"] = apply_result
                if apply_result.get("applied"):
                    applied += 1
                    candidate["status"] = "applied"
        candidates.append(candidate)

    return {
        "schema_version": "0.7",
        "mode": mode,
        "safety": {
            "core_modifications": False,
            "writes_require_apply_low_risk": True,
            "writes_require_auto_approval": True,
            "protect_core_skills": bool(cfg.protect_core_skills),
            "auto_apply_policy": "local-agent-created-skills-only",
            "auto_apply_source_policy": "bundled/hub/external/plugin/unknown sources are skipped",
            "protected_core_patterns": list(_DEFAULT_CORE_AUTO_APPLY_PROTECTED_PATTERNS),
            "auto_apply_allowlist": list(_normalize_patterns(cfg.auto_apply_allowlist)),
            "auto_apply_blocklist": list(_normalize_patterns(cfg.auto_apply_blocklist)),
            "mutation_policy": "append-only managed block + guarded apply backup/rollback",
        },
        "config": {
            "db_path": str(store.db_path),
            "skills_dir": str(skills_dir),
            "backup_dir": str(backup_dir),
            "hermes_home": str(source_context.hermes_home),
            "local_skills_dir": str(source_context.local_skills_dir),
            "external_dirs": [str(path) for path in source_context.external_dirs],
            "bundled_skill_count": len(source_context.bundled_names),
            "hub_installed_skill_count": len(source_context.hub_installed_names),
            "days": days,
            "max_skills": max_skills,
            "min_evidence": min_evidence,
            "semantic_candidates": bool(cfg.semantic_candidates),
            "rerank_candidates": bool(cfg.rerank_candidates),
            "protect_core_skills": bool(cfg.protect_core_skills),
            "auto_apply_allowlist": list(_normalize_patterns(cfg.auto_apply_allowlist)),
            "auto_apply_blocklist": list(_normalize_patterns(cfg.auto_apply_blocklist)),
        },
        "selection": selection,
        "summary": {
            "planned": len([c for c in candidates if c.get("status") in {"planned", "applied"}]),
            "applied": applied,
            "skipped": len([c for c in candidates if c.get("status") == "skipped"]),
        },
        "candidates": candidates,
    }


def _systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"


def install_auto_timer(
    *,
    schedule: str = "daily",
    skills_dir: str | Path | None = None,
    apply_low_risk: bool = True,
    enable: bool = False,
    semantic_candidates: bool = False,
    rerank_candidates: bool = False,
    protect_core_skills: bool = True,
    auto_apply_allowlist: tuple[str, ...] = (),
    auto_apply_blocklist: tuple[str, ...] = (),
    verify_command: str | None = None,
    verify_cwd: str | Path | None = None,
    verify_skills: bool = True,
) -> dict[str, Any]:
    """Install a user systemd timer for automatic evolution.

    The timer is disabled unless `enable=True`, so package install can stay
    non-invasive while still providing a one-command plug-in automation path.
    """

    unit_dir = _systemd_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / "hermes-curator-evolver-auto.service"
    timer_path = unit_dir / "hermes-curator-evolver-auto.timer"
    target_skills = Path(skills_dir) if skills_dir is not None else _default_skills_dir()
    on_calendar = {"hourly": "hourly", "daily": "daily", "weekly": "weekly"}.get(schedule, schedule)
    effective_verify_command = verify_command
    effective_verify_cwd = Path(verify_cwd) if verify_cwd is not None else target_skills
    if apply_low_risk and verify_skills and effective_verify_command is None:
        effective_verify_command = f"{sys.executable} -m hermes_curator_evolver.skill_validate"
    args = [
        sys.executable,
        "-m",
        "hermes_curator_evolver",
        "auto-run",
        "--skills-dir",
        str(target_skills),
        "--format",
        "json",
    ]
    if semantic_candidates or rerank_candidates:
        args.append("--semantic-candidates")
    if rerank_candidates:
        args.append("--rerank-candidates")
    if apply_low_risk:
        args.extend(["--apply-low-risk", "--approve-auto-apply"])
        if protect_core_skills:
            args.append("--protect-core-skills")
        else:
            args.append("--no-protect-core-skills")
        for pattern in _normalize_patterns(auto_apply_allowlist):
            args.extend(["--allow-auto-apply-skill", pattern])
        for pattern in _normalize_patterns(auto_apply_blocklist):
            args.extend(["--block-auto-apply-skill", pattern])
    if effective_verify_command:
        args.extend(["--verify-command", _systemd_quote(effective_verify_command)])
        args.extend(["--verify-cwd", str(effective_verify_cwd)])
    command = " ".join(args)
    service_path.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=Hermes Curator Evolver automatic low-risk skill evolution",
                "",
                "[Service]",
                "Type=oneshot",
                "Environment=PYTHONUNBUFFERED=1",
                f"ExecStart={command}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    timer_path.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=Run Hermes Curator Evolver automatic skill evolution",
                "",
                "[Timer]",
                f"OnCalendar={on_calendar}",
                "Persistent=true",
                "",
                "[Install]",
                "WantedBy=timers.target",
                "",
            ]
        ),
        encoding="utf-8",
    )
    result = {
        "installed": True,
        "enabled": False,
        "service_path": str(service_path),
        "timer_path": str(timer_path),
        "schedule": on_calendar,
        "semantic_candidates": bool(semantic_candidates or rerank_candidates),
        "rerank_candidates": bool(rerank_candidates),
        "protect_core_skills": bool(protect_core_skills),
        "auto_apply_policy": "local-agent-created-skills-only" if apply_low_risk else "dry-run-only",
        "auto_apply_allowlist": list(_normalize_patterns(auto_apply_allowlist)),
        "auto_apply_blocklist": list(_normalize_patterns(auto_apply_blocklist)),
        "verify_command": effective_verify_command,
        "verify_cwd": str(effective_verify_cwd) if effective_verify_command else None,
        "command": command,
    }
    if enable:
        import subprocess

        completed = subprocess.run(
            ["systemctl", "--user", "enable", "--now", timer_path.name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        result["enabled"] = completed.returncode == 0
        result["systemctl"] = {"exit_code": completed.returncode, "output": completed.stdout[-2000:]}
    return result


def uninstall_auto_timer(*, disable: bool = True) -> dict[str, Any]:
    """Remove the user systemd timer/service installed by this plugin."""

    unit_dir = _systemd_dir()
    service_path = unit_dir / "hermes-curator-evolver-auto.service"
    timer_path = unit_dir / "hermes-curator-evolver-auto.timer"
    result: dict[str, Any] = {"removed": [], "missing": []}
    if disable:
        import subprocess

        completed = subprocess.run(
            ["systemctl", "--user", "disable", "--now", timer_path.name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        result["systemctl"] = {"exit_code": completed.returncode, "output": completed.stdout[-2000:]}
    for path in (timer_path, service_path):
        if path.exists():
            path.unlink()
            result["removed"].append(str(path))
        else:
            result["missing"].append(str(path))
    return result


def format_auto_evolve_result(result: dict[str, Any], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    lines = [
        "# Hermes Curator Evolver Auto Run",
        "",
        f"- Mode: `{result['mode']}`",
        f"- Planned: {result['summary']['planned']}",
        f"- Applied: {result['summary']['applied']}",
        f"- Skipped: {result['summary']['skipped']}",
        f"- Selection: `{result.get('selection', {}).get('mode', 'unknown')}`",
        "",
        "## Candidates",
        "",
    ]
    for candidate in result.get("candidates") or []:
        reason = candidate.get("reason")
        reason_text = f" reason={reason}" if reason else ""
        lines.append(
            f"- `{candidate.get('skill_name')}` — {candidate.get('status')} ({candidate.get('risk')}){reason_text}"
        )
        if candidate.get("apply_result"):
            lines.append(f"  - apply: {candidate['apply_result'].get('reason')}")
        if candidate.get("selection"):
            lines.append(f"  - selection: {candidate['selection'].get('source')} score={candidate['selection'].get('score')}")
    if not result.get("candidates"):
        lines.append("- No skills met the evidence threshold.")
    return "\n".join(lines)
