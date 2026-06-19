"""Read-only SKILL.md structure audit and consolidation safety checks.

The curator needs local, deterministic signals before it asks any model to grow,
shrink, or consolidate skills.  This module deliberately does not mutate skill
files; it only reports blast-radius risks such as token-heavy SKILL.md bodies,
missing reference spillover, and executable capacity that would be lost by a
naive umbrella merge.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REFERENCE_DIRS = ("references", "templates", "scripts", "assets")
EXECUTABLE_SUFFIXES = (".bash", ".expect", ".js", ".ps1", ".py", ".rb", ".sh", ".ts")

SOFT_SKILL_CHARS = 16_000
HIGH_SKILL_CHARS = 32_000
CRITICAL_SKILL_CHARS = 64_000
LONG_LINE_CHARS = 4_000

_FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*[\"']?(?P<name>[^\"'\n]+)[\"']?\s*$", re.MULTILINE)
_DESCRIPTION_RE = re.compile(
    r"^description:\s*[\"']?(?P<description>[^\"'\n]+)[\"']?\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SkillIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class SkillStructure:
    name: str
    path: str
    skill_dir: str
    chars: int
    bytes: int
    approx_tokens: int
    lines: int
    longest_line_chars: int
    support_file_count: int
    support_bytes: int
    support_dirs: dict[str, int] = field(default_factory=dict)
    executable_file_count: int = 0
    executable_dirs: list[str] = field(default_factory=list)
    executable_paths: list[str] = field(default_factory=list)
    has_references: bool = False
    has_executable_capacity: bool = False
    issues: list[SkillIssue] = field(default_factory=list)
    risk: str = "ok"
    description: str = ""


@dataclass(frozen=True)
class ConsolidationCapacityCheck:
    allowed: bool
    source: SkillStructure
    target: SkillStructure
    failures: list[str]
    warnings: list[str]
    missing_executable_dirs: list[str]


def _frontmatter_value(text: str, regex: re.Pattern[str], fallback: str = "") -> str:
    match = _FRONTMATTER_RE.match(text)
    haystack = match.group("body") if match else text
    value = regex.search(haystack)
    if not value:
        return fallback
    group_name = "name" if "name" in value.groupdict() else "description"
    return value.group(group_name).strip()


def _is_skill_support_path(path: Path) -> bool:
    return any(part in set(REFERENCE_DIRS) for part in path.parts)


def _support_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in REFERENCE_DIRS:
        directory = skill_dir / dirname
        if not directory.exists():
            continue
        files.extend(sorted(path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()))
    return files


def _executable_files(skill_dir: Path, support_files: list[Path]) -> list[Path]:
    executable: list[Path] = []
    for path in support_files:
        if path.suffix.casefold() in EXECUTABLE_SUFFIXES:
            executable.append(path)
            continue
        try:
            mode = path.stat().st_mode
        except OSError:
            continue
        if mode & 0o111:
            executable.append(path)
    return executable


def _risk_from_issues(issues: list[SkillIssue]) -> str:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    if not issues:
        return "ok"
    return max(issues, key=lambda issue: order.get(issue.severity, 0)).severity


def inspect_skill_structure(skill_file: str | Path) -> SkillStructure:
    """Return deterministic structure metadata for one SKILL.md file."""

    path = Path(skill_file)
    skill_dir = path.parent
    text = path.read_text(encoding="utf-8", errors="replace")
    encoded_size = len(text.encode("utf-8"))
    lines = text.splitlines() or [""]
    support = _support_files(skill_dir)
    executable = _executable_files(skill_dir, support)
    support_dirs: dict[str, int] = {}
    for support_file in support:
        try:
            top = support_file.relative_to(skill_dir).parts[0]
        except (OSError, ValueError, IndexError):
            continue
        support_dirs[top] = support_dirs.get(top, 0) + 1

    executable_dirs = sorted(
        {
            str(path.relative_to(skill_dir).parts[0])
            for path in executable
            if path.relative_to(skill_dir).parts
        }
    )
    executable_paths = [str(path.relative_to(skill_dir)) for path in executable[:25]]
    name = _frontmatter_value(text, _NAME_RE, fallback=skill_dir.name)
    description = _frontmatter_value(text, _DESCRIPTION_RE)

    issues: list[SkillIssue] = []
    if len(text) >= CRITICAL_SKILL_CHARS:
        issues.append(
            SkillIssue(
                "critical",
                "critical-main-content-size",
                "SKILL.md is large enough to become a context/token bomb even when support files exist.",
            )
        )
    elif len(text) >= HIGH_SKILL_CHARS:
        issues.append(
            SkillIssue(
                "high",
                "large-main-content-size",
                "SKILL.md is large; keep only routing/decision logic inline and move details to references/.",
            )
        )
    elif len(text) >= SOFT_SKILL_CHARS:
        issues.append(
            SkillIssue(
                "low",
                "watch-main-content-size",
                "SKILL.md is approaching a size where future auto-curation should prefer reference spillover.",
            )
        )

    has_references = bool(support_dirs.get("references"))
    if len(text) >= HIGH_SKILL_CHARS and not has_references:
        issues.append(
            SkillIssue(
                "high",
                "large-skill-without-references",
                "Large SKILL.md has no references/ spillover; any load reads the whole body.",
            )
        )
    elif len(text) >= SOFT_SKILL_CHARS and not has_references:
        issues.append(
            SkillIssue(
                "medium",
                "medium-skill-without-references",
                "Medium-sized SKILL.md has no references/ support files; split detailed runbooks before it grows.",
            )
        )

    longest_line = max(len(line) for line in lines)
    if longest_line >= LONG_LINE_CHARS:
        issues.append(
            SkillIssue(
                "high",
                "very-long-line",
                "SKILL.md contains a very long line; this usually means generated docs or transcripts were inlined.",
            )
        )

    if executable:
        issues.append(
            SkillIssue(
                "low",
                "executable-capacity",
                "Skill carries executable/support automation; consolidation must preserve or explicitly demote that capacity.",
            )
        )

    return SkillStructure(
        name=name,
        path=str(path),
        skill_dir=str(skill_dir),
        chars=len(text),
        bytes=encoded_size,
        approx_tokens=max(1, round(len(text) / 4)),
        lines=len(lines),
        longest_line_chars=longest_line,
        support_file_count=len(support),
        support_bytes=sum(file.stat().st_size for file in support),
        support_dirs=support_dirs,
        executable_file_count=len(executable),
        executable_dirs=executable_dirs,
        executable_paths=executable_paths,
        has_references=has_references,
        has_executable_capacity=bool(executable),
        issues=issues,
        risk=_risk_from_issues(issues),
        description=description,
    )


def discover_auditable_skill_files(skills_dir: str | Path, *, include_archive: bool = False) -> list[Path]:
    root = Path(skills_dir)
    if not root.exists():
        return []
    ignored = {".curator_backups", ".git", ".hub", "__pycache__"}
    if not include_archive:
        ignored.add(".archive")
    result: list[Path] = []
    for path in sorted(root.rglob("SKILL.md")):
        if any(part in ignored for part in path.parts):
            continue
        if _is_skill_support_path(path.relative_to(root)):
            continue
        result.append(path)
    return result


def audit_skill_library(skills_dir: str | Path, *, include_archive: bool = False) -> dict[str, Any]:
    """Inspect a skill tree and return token-bloat/reference/executable risks."""

    root = Path(skills_dir)
    skills = [inspect_skill_structure(path) for path in discover_auditable_skill_files(root, include_archive=include_archive)]
    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "ok": 0}
    issue_counts: dict[str, int] = {}
    for skill in skills:
        risk_counts[skill.risk] = risk_counts.get(skill.risk, 0) + 1
        for issue in skill.issues:
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1
    return {
        "schema_version": "0.1",
        "skills_dir": str(root),
        "include_archive": bool(include_archive),
        "total_skills": len(skills),
        "summary": {
            "risk_counts": risk_counts,
            "issue_counts": dict(sorted(issue_counts.items())),
            "risky_skill_count": len([skill for skill in skills if skill.risk != "ok"]),
            "executable_skill_count": len([skill for skill in skills if skill.has_executable_capacity]),
        },
        "skills": [asdict(skill) for skill in sorted(skills, key=lambda item: (item.risk == "ok", -item.chars, item.name))],
    }


def check_consolidation_capacity(source_skill_dir: str | Path, target_skill_dir: str | Path) -> dict[str, Any]:
    """Verify a proposed source→umbrella merge preserves executable capacity.

    This is the deterministic guard for issue #19: if the source has scripts or
    executable support files, an umbrella target with no equivalent executable
    directories is not safe for blind consolidation.
    """

    source_dir = Path(source_skill_dir)
    target_dir = Path(target_skill_dir)
    source = inspect_skill_structure(source_dir / "SKILL.md")
    target = inspect_skill_structure(target_dir / "SKILL.md")
    failures: list[str] = []
    warnings: list[str] = []

    missing_dirs = sorted(set(source.executable_dirs) - set(target.executable_dirs))
    if source.has_executable_capacity and not target.has_executable_capacity:
        failures.append(
            "source has executable capacity but target has none; consolidation would archive runnable automation"
        )
    elif missing_dirs:
        failures.append(
            "target is missing executable support directories present in source: " + ", ".join(missing_dirs)
        )

    if source.support_dirs.get("references") and not target.support_dirs.get("references"):
        warnings.append("source has references/ but target has no references/ directory")
    if source.has_executable_capacity:
        warnings.append(
            "preserve source support files or demote source to a reference file; do not delete/archive the source skill blindly"
        )

    check = ConsolidationCapacityCheck(
        allowed=not failures,
        source=source,
        target=target,
        failures=failures,
        warnings=warnings,
        missing_executable_dirs=missing_dirs,
    )
    return asdict(check)


def format_skill_audit_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    summary = report.get("summary") or {}
    risk_counts = summary.get("risk_counts") or {}
    lines = [
        "# Skill Structure Audit",
        "",
        f"- Skills dir: `{report.get('skills_dir')}`",
        f"- Total skills: {report.get('total_skills', 0)}",
        f"- Risk counts: critical={risk_counts.get('critical', 0)}, high={risk_counts.get('high', 0)}, medium={risk_counts.get('medium', 0)}, low={risk_counts.get('low', 0)}, ok={risk_counts.get('ok', 0)}",
        f"- Executable skills: {summary.get('executable_skill_count', 0)}",
        "",
        "## Highest-risk skills",
        "",
    ]
    risky = [skill for skill in report.get("skills") or [] if skill.get("risk") != "ok"][:limit]
    if not risky:
        lines.append("No structural risks found.")
    for skill in risky:
        issue_codes = ", ".join(issue["code"] for issue in skill.get("issues") or [])
        lines.append(
            f"- **{skill.get('risk')}** `{skill.get('name')}` — {skill.get('chars')} chars, "
            f"~{skill.get('approx_tokens')} tokens, refs={skill.get('support_dirs', {}).get('references', 0)}, "
            f"exec={skill.get('executable_file_count', 0)}"
        )
        lines.append(f"  - path: `{skill.get('path')}`")
        if issue_codes:
            lines.append(f"  - issues: {issue_codes}")
    return "\n".join(lines).rstrip() + "\n"


def format_consolidation_check_markdown(check: dict[str, Any]) -> str:
    source = check.get("source") or {}
    target = check.get("target") or {}
    lines = [
        "# Skill Consolidation Capacity Check",
        "",
        f"- Allowed: `{bool(check.get('allowed'))}`",
        f"- Source: `{source.get('name')}` exec={source.get('executable_file_count', 0)} dirs={source.get('executable_dirs', [])}",
        f"- Target: `{target.get('name')}` exec={target.get('executable_file_count', 0)} dirs={target.get('executable_dirs', [])}",
    ]
    failures = check.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)
    warnings = check.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).rstrip() + "\n"


def format_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
