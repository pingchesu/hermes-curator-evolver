"""Automatic, low-risk skill evolution loop.

This module is intentionally self-contained so the plugin can improve skills
without patching Hermes core. The safe mutation policy is bounded: generate a
managed evidence-backed section, preserve the existing skill text, spill bulky
evidence into references/ when needed, then apply via hash/backup/verification
guardrails.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field
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
_MAX_SKILL_CONTENT_CHARS = 100_000
_SOFT_SKILL_CONTENT_CHARS = 90_000

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
class PreparedSkillUpdate:
    """A bounded SKILL.md update plus optional support files."""

    content: str
    size_strategy: str = "inline"
    support_files: dict[str, str] = field(default_factory=dict)
    skipped_reason: str | None = None


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
    pre_verify_command: str | None = None
    staged_verify: bool = False
    semantic_candidates: bool = False
    rerank_candidates: bool = False
    embedding_backend: Any | None = None
    reranker_backend: Any | None = None
    protect_core_skills: bool = True
    auto_apply_allowlist: tuple[str, ...] = ()
    auto_apply_blocklist: tuple[str, ...] = ()
    variants: int = 1


@dataclass(frozen=True)
class _VariantSpec:
    """Deterministic recipe for one bounded managed-block candidate."""

    name: str
    evidence_limit: int
    guidance_style: str
    force_spillover: bool = False


# Deterministic ordering: variant 0 is the prior default so single-variant
# runs remain byte-identical to the pre-variants behavior.
_VARIANT_SPECS: tuple[_VariantSpec, ...] = (
    _VariantSpec(name="default-verify-first", evidence_limit=5, guidance_style="verify-first"),
    _VariantSpec(name="compact-evidence-first", evidence_limit=3, guidance_style="evidence-first"),
    _VariantSpec(name="wide-errors-first", evidence_limit=8, guidance_style="errors-first"),
    _VariantSpec(name="spillover-minimal-inline", evidence_limit=2, guidance_style="verify-first", force_spillover=True),
)


_GUIDANCE_BULLETS: dict[str, tuple[str, ...]] = {
    "verify-first": (
        "When this skill is relevant, check these observed signals before choosing a workflow.",
        "Prefer targeted verification over broad retries when similar errors recur.",
        "If a repeated issue is understood, replace this evidence note with a concise human-readable SOP update.",
    ),
    "evidence-first": (
        "Reuse the matching evidence row above before re-running the same tool from scratch.",
        "When this skill is relevant, check these observed signals before choosing a workflow.",
        "If a repeated issue is understood, replace this evidence note with a concise human-readable SOP update.",
    ),
    "errors-first": (
        "Replay the most recent error-marked evidence rows first; they are the strongest signal that something changed.",
        "Prefer targeted verification over broad retries when similar errors recur.",
        "If a repeated issue is understood, replace this evidence note with a concise human-readable SOP update.",
    ),
}


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
    generated_at: str | None = None,
    evidence_limit: int = 5,
    detail_reference_path: str | None = None,
    guidance_style: str = "verify-first",
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    evidence_lines = _format_evidence_rows(evidence_rows, limit=evidence_limit)
    if not evidence_lines:
        evidence_lines = ["- No individual evidence rows were available; aggregate counts triggered this pass."]
    if detail_reference_path:
        evidence_lines = [
            f"- Detailed evidence moved to `{detail_reference_path}` to keep this SKILL.md below the write limit.",
            *evidence_lines[:1],
        ]
    guidance = _GUIDANCE_BULLETS.get(guidance_style, _GUIDANCE_BULLETS["verify-first"])
    return "\n".join(
        [
            _START,
            "## Auto-curated evidence notes",
            "",
            "Low-risk bounded auto-curation generated by `hermes-curator-evolver`.",
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
            *(f"- {line}" for line in guidance),
            _END,
            "",
        ]
    )


def _apply_managed_block(skill_text: str, block: str) -> str:
    if _START in skill_text and _END in skill_text:
        pattern = re.compile(re.escape(_START) + r".*?" + re.escape(_END) + r"\n?", re.DOTALL)
        return pattern.sub(block, skill_text, count=1)
    separator = "\n" if skill_text.endswith("\n") else "\n\n"
    return skill_text + separator + block


def _safe_skill_slug(skill_name: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", skill_name.casefold()).strip(".-_")
    return slug or "skill"


def _evidence_reference_path(*, skill_name: str, generated_at: str) -> str:
    stamp = generated_at.split("+", 1)[0].replace(":", "").replace("-", "")
    stamp = stamp.replace("T", "-")[:15]
    return f"references/curator-evolver-auto-{_safe_skill_slug(skill_name)}-{stamp}.md"


def _format_evidence_reference(
    *,
    skill_name: str,
    generated_at: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Curator Evolver evidence for `{skill_name}`",
        "",
        f"Generated at: `{generated_at}`",
        f"Evidence window: last {days} day(s)",
        "",
        "## Summary",
        "",
        f"- Tool events: {int(summary.get('tool_events') or 0)}",
        f"- Skill events: {int(summary.get('skill_events') or 0)}",
        f"- Error-like events: {int(summary.get('error_events') or 0)}",
        "",
        "## Evidence rows",
        "",
    ]
    if not evidence_rows:
        lines.append("- No individual evidence rows were available; aggregate counts triggered this pass.")
    for row in evidence_rows:
        created = row.get("created_at") or "unknown-time"
        tool = row.get("tool_name") or "unknown-tool"
        marker = "error" if row.get("is_error") else "ok"
        preview = str(row.get("result_preview") or "").replace("\x00", "").strip()
        lines.extend([f"### {created} — `{tool}` {marker}", "", "```text", preview, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _prepare_variant(
    *,
    skill_name: str,
    skill_text: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    variant: _VariantSpec,
    generated_at: str,
    max_content_chars: int,
    soft_content_chars: int,
) -> PreparedSkillUpdate:
    """Produce a single bounded update for one variant spec."""

    if len(skill_text) > max_content_chars:
        return PreparedSkillUpdate(
            content=skill_text,
            size_strategy="skip-hard-cap",
            skipped_reason="skill-content-hard-cap",
        )

    if not variant.force_spillover:
        inline_block = _managed_block(
            skill_name=skill_name,
            days=days,
            summary=summary,
            evidence_rows=evidence_rows,
            generated_at=generated_at,
            evidence_limit=variant.evidence_limit,
            guidance_style=variant.guidance_style,
        )
        inline = _apply_managed_block(skill_text, inline_block)
        if len(inline) <= soft_content_chars:
            return PreparedSkillUpdate(content=inline, size_strategy="inline")

    reference_path = _evidence_reference_path(skill_name=skill_name, generated_at=generated_at)
    compact_block = _managed_block(
        skill_name=skill_name,
        days=days,
        summary=summary,
        evidence_rows=evidence_rows,
        generated_at=generated_at,
        evidence_limit=1 if variant.force_spillover else min(variant.evidence_limit, 1),
        detail_reference_path=reference_path,
        guidance_style=variant.guidance_style,
    )
    compact = _apply_managed_block(skill_text, compact_block)
    if len(compact) > max_content_chars:
        return PreparedSkillUpdate(
            content=skill_text,
            size_strategy="skip-hard-cap",
            skipped_reason="skill-content-hard-cap",
        )
    return PreparedSkillUpdate(
        content=compact,
        size_strategy="reference-spillover",
        support_files={
            reference_path: _format_evidence_reference(
                skill_name=skill_name,
                generated_at=generated_at,
                days=days,
                summary=summary,
                evidence_rows=evidence_rows,
            )
        },
    )


def prepare_low_risk_skill_update(
    *,
    skill_name: str,
    skill_text: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_content_chars: int = _MAX_SKILL_CONTENT_CHARS,
    soft_content_chars: int = _SOFT_SKILL_CONTENT_CHARS,
) -> PreparedSkillUpdate:
    """Prepare a bounded auto-curation update for a skill.

    The main SKILL.md stays below Hermes' 100k write limit.  If a skill is
    already large or the inline managed block would push it beyond the soft cap,
    detailed evidence is spilled into a references/ support file and the main
    block keeps only a pointer plus compact summary.

    This is the default single-variant path; multi-variant generation lives in
    `generate_variants` and only kicks in when the caller asks for it.
    """

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return _prepare_variant(
        skill_name=skill_name,
        skill_text=skill_text,
        days=days,
        summary=summary,
        evidence_rows=evidence_rows,
        variant=_VARIANT_SPECS[0],
        generated_at=generated_at,
        max_content_chars=max_content_chars,
        soft_content_chars=soft_content_chars,
    )


def _score_variant(
    *,
    prepared: PreparedSkillUpdate,
    original: str,
    soft_cap: int,
    hard_cap: int,
) -> dict[str, Any]:
    """Return a deterministic score breakdown for a prepared variant.

    Higher score wins. Skipped variants (hard cap) score very low so they are
    never selected unless every variant skips.
    """

    score = 0
    breakdown: list[str] = []
    if prepared.skipped_reason:
        return {"score": -1_000_000, "breakdown": [f"skipped:{prepared.skipped_reason}"]}
    if prepared.size_strategy == "inline":
        score += 100
        breakdown.append("inline:+100")
    else:
        breakdown.append("spillover:+0")
    overflow_soft = max(0, len(prepared.content) - soft_cap)
    if overflow_soft:
        penalty = overflow_soft // 100
        score -= penalty
        breakdown.append(f"over-soft-cap:-{penalty}")
    slack = max(0, hard_cap - len(prepared.content))
    slack_bonus = min(slack // 1000, 10)
    score += slack_bonus
    breakdown.append(f"hard-cap-slack:+{slack_bonus}")
    diff = abs(len(prepared.content) - len(original))
    diff_penalty = min(diff // 1000, 20)
    score -= diff_penalty
    breakdown.append(f"diff-from-original:-{diff_penalty}")
    return {"score": score, "breakdown": breakdown}


def generate_variants(
    *,
    skill_name: str,
    skill_text: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    count: int,
    generated_at: str | None = None,
    max_content_chars: int = _MAX_SKILL_CONTENT_CHARS,
    soft_content_chars: int = _SOFT_SKILL_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    """Deterministically produce up to `count` bounded-update candidates.

    Variant 0 is always the prior default behavior, so `count=1` is
    byte-identical to the pre-variants single-variant path. Variants are
    described by `_VARIANT_SPECS` and only vary knobs already inside the
    bounded mutation policy (evidence row count, spillover strategy, guidance
    phrasing).
    """

    count = max(1, min(int(count), len(_VARIANT_SPECS)))
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []
    for index, spec in enumerate(_VARIANT_SPECS[:count]):
        prepared = _prepare_variant(
            skill_name=skill_name,
            skill_text=skill_text,
            days=days,
            summary=summary,
            evidence_rows=evidence_rows,
            variant=spec,
            generated_at=generated_at,
            max_content_chars=max_content_chars,
            soft_content_chars=soft_content_chars,
        )
        score = _score_variant(
            prepared=prepared,
            original=skill_text,
            soft_cap=soft_content_chars,
            hard_cap=max_content_chars,
        )
        results.append(
            {
                "index": index,
                "name": spec.name,
                "spec": {
                    "evidence_limit": spec.evidence_limit,
                    "guidance_style": spec.guidance_style,
                    "force_spillover": spec.force_spillover,
                },
                "prepared": prepared,
                "size_strategy": prepared.size_strategy,
                "skipped_reason": prepared.skipped_reason,
                "content_chars": len(prepared.content),
                "support_files": sorted(prepared.support_files),
                "score": score["score"],
                "score_breakdown": score["breakdown"],
            }
        )
    return results


def select_winning_variant(variants: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the deterministic winning variant.

    Ties are broken by variant index so the result is reproducible across
    runs given identical inputs.
    """

    if not variants:
        raise ValueError("select_winning_variant requires at least one variant")
    return max(variants, key=lambda v: (v["score"], -v["index"]))


def build_low_risk_skill_update(
    *,
    skill_name: str,
    skill_text: str,
    days: int,
    summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> str:
    """Return a bounded managed update that preserves existing skill text."""

    return prepare_low_risk_skill_update(
        skill_name=skill_name,
        skill_text=skill_text,
        days=days,
        summary=summary,
        evidence_rows=evidence_rows,
    ).content


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
    `approve_auto_apply`; even then, writes are bounded managed-block updates
    with optional reference spillover, and they go through guarded apply.
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
            "mutation_policy": "bounded-managed-block-with-reference-spillover",
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
        variants_requested = _bounded(cfg.variants or 1, minimum=1, maximum=len(_VARIANT_SPECS))
        variant_results = generate_variants(
            skill_name=name,
            skill_text=original,
            days=days,
            summary=skill_summary,
            evidence_rows=evidence_rows,
            count=variants_requested,
        )
        winning = select_winning_variant(variant_results)
        prepared = winning["prepared"]
        variants_summary = [
            {
                "index": variant["index"],
                "name": variant["name"],
                "spec": variant["spec"],
                "size_strategy": variant["size_strategy"],
                "skipped_reason": variant["skipped_reason"],
                "content_chars": variant["content_chars"],
                "support_files": variant["support_files"],
                "score": variant["score"],
                "score_breakdown": variant["score_breakdown"],
                "selected": variant["index"] == winning["index"],
            }
            for variant in variant_results
        ]
        candidate["variants_requested"] = variants_requested
        candidate["variants"] = variants_summary
        candidate["selected_variant"] = {
            "index": winning["index"],
            "name": winning["name"],
            "score": winning["score"],
        }
        if prepared.skipped_reason:
            candidate["status"] = "skipped"
            candidate["reason"] = prepared.skipped_reason
            candidate["size_strategy"] = prepared.size_strategy
            candidates.append(candidate)
            continue
        updated = prepared.content
        candidate.update(
            {
                "status": "planned",
                "current_sha256": sha256_file(skill_file),
                "new_content_changed": updated != original,
                "size_strategy": prepared.size_strategy,
                "support_files": sorted(prepared.support_files),
                "content_size": {
                    "current_chars": len(original),
                    "updated_chars": len(updated),
                    "soft_limit_chars": _SOFT_SKILL_CONTENT_CHARS,
                    "hard_limit_chars": _MAX_SKILL_CONTENT_CHARS,
                },
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
                    pre_verify_command=cfg.pre_verify_command,
                    staged_verify=bool(cfg.staged_verify or cfg.pre_verify_command),
                )
                candidate["apply_result"] = apply_result
                if apply_result.get("applied"):
                    for relative_path, content in prepared.support_files.items():
                        support_path = skill_file.parent / relative_path
                        support_path.parent.mkdir(parents=True, exist_ok=True)
                        support_path.write_text(content, encoding="utf-8")
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
            "mutation_policy": "bounded managed block + reference spillover + guarded apply backup/rollback",
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
            "variants": _bounded(cfg.variants or 1, minimum=1, maximum=len(_VARIANT_SPECS)),
            "staged_verify": bool(cfg.staged_verify or cfg.pre_verify_command),
            "pre_verify_command": cfg.pre_verify_command,
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
