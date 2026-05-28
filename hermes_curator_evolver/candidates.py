"""Read-only candidate mining for the curator-evolver review queue.

This module classifies redacted evidence snippets into review candidates.
Nothing here writes to user memory, mutates skills, or auto-applies anything;
every produced candidate defaults to ``auto_apply_allowed=False`` and
``requires_human_review=True``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .storage import MANAGE_TOOL_NAME

CANDIDATE_TYPE_MEMORY = "memory"
CANDIDATE_TYPE_SKILL_UPDATE = "skill_update"
CANDIDATE_TYPE_SKILL_NEW = "skill_new"
CANDIDATE_TYPE_REPLAY_BENCHMARK = "replay_benchmark"
CANDIDATE_TYPE_IGNORE = "ignore"

CANDIDATE_TYPES = {
    CANDIDATE_TYPE_MEMORY,
    CANDIDATE_TYPE_SKILL_UPDATE,
    CANDIDATE_TYPE_SKILL_NEW,
    CANDIDATE_TYPE_REPLAY_BENCHMARK,
    CANDIDATE_TYPE_IGNORE,
}

SKILL_MD_NEAR_CAP_BYTES = 90_000
SKILL_MD_HARD_CAP_BYTES = 100_000


def candidate_id(candidate_type: str, title: str, evidence_refs: Iterable[str]) -> str:
    """Stable sha256-derived id over type, title, and sorted evidence refs."""
    refs = ",".join(sorted(str(r) for r in evidence_refs))
    payload = f"{candidate_type}|{title}|{refs}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


@dataclass
class Candidate:
    candidate_type: str
    title: str
    rationale: str
    confidence: float
    evidence_refs: list[str]
    target_skill: str | None = None
    auto_apply_allowed: bool = False
    requires_human_review: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if self.candidate_type not in CANDIDATE_TYPES:
            raise ValueError(f"unknown candidate_type: {self.candidate_type!r}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.auto_apply_allowed:
            raise ValueError(
                "auto_apply_allowed must remain False in the read-only candidate miner"
            )
        if not self.requires_human_review:
            raise ValueError(
                "requires_human_review must remain True in the read-only candidate miner"
            )
        if not self.id:
            self.id = candidate_id(self.candidate_type, self.title, self.evidence_refs)


_SAFETY_PREF_PATTERN = re.compile(
    r"curator[-\s]?evolver.*(auto[-\s]?apply).*(agent[-\s]?created|non[-\s]?core)",
    re.IGNORECASE | re.DOTALL,
)
_SAFETY_PROHIBIT_PATTERN = re.compile(
    r"(must not|never|do not|don't).*(modify|touch|change).*(core|official|external)",
    re.IGNORECASE | re.DOTALL,
)
_MEMORY_POLICY_PATTERN = re.compile(
    r"durable\s+memory.*(只存|不存|流程/步驟/SOP|task\s+progress|PR\s*/\s*SHA)",
    re.IGNORECASE | re.DOTALL,
)

_STEP_NUMBERED_PATTERN = re.compile(r"\b[1-9]\.\s+\S")
_STEP_KEYWORD_PATTERN = re.compile(
    r"\b(first|then|next|finally|step\s+\d+)\b|先|再|最後|流程|步驟|SOP",
    re.IGNORECASE,
)
_SHELL_COMMAND_PATTERN = re.compile(r"`[^`]{2,}`|\brun\s+`", re.IGNORECASE)
_ZH_WORKFLOW_PATTERN = re.compile(
    r"(流程|步驟|SOP).{0,80}(先|再|最後).{0,160}(先|再|最後)", re.DOTALL
)

_ERROR_KEYWORD_PATTERN = re.compile(
    r"\b(traceback|not[_\s-]found|exit\s+code\s+\d+|exit\s*=\s*[1-9]"
    r"|nonzero|failed|size\s+cap|exceeded|stderr)\b",
    re.IGNORECASE,
)

_PR_REF_PATTERN = re.compile(r"\bPR\s*#?\d+\b|\bpull[-\s]request\s*#?\d+\b", re.IGNORECASE)
_ISSUE_ONLY_PATTERN = re.compile(r"^#\d+$")
_SHA_ONLY_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_EPHEMERAL_KEYWORDS = re.compile(
    r"\b(merged|squashed|rebased|todo|wip)\b", re.IGNORECASE
)

_SKILL_MD_SIZE_PATTERN = re.compile(
    r"SKILL\.md.{0,40}?(\d{4,6})\s*bytes", re.IGNORECASE | re.DOTALL
)
_NEAR_CAP_WORDS = re.compile(r"near\s+100k|near\s+cap|over\s+cap", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _extract_inner_text(text: str) -> str:
    """Return reviewer-readable text from common tool-result JSON wrappers."""
    stripped = (text or "").strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return text

    def collect(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                out.extend(collect(item))
            return out
        if isinstance(value, dict):
            out: list[str] = []
            for key in ("summary", "text", "output", "content", "error", "exception"):
                if key in value:
                    out.extend(collect(value[key]))
            if not out and "results" in value:
                out.extend(collect(value["results"]))
            return out
        return []

    parts = [p.strip() for p in collect(payload) if p and p.strip()]
    return "\n".join(parts) if parts else text


def _evidence_refs(record: dict[str, Any]) -> list[str]:
    raw = record.get("evidence_refs") or record.get("evidence_ref") or []
    if isinstance(raw, str):
        return [raw] if raw else []
    return [str(r) for r in raw if r]


def _is_safety_preference(text: str) -> bool:
    if not text:
        return False
    if _SAFETY_PREF_PATTERN.search(text):
        return True
    if _MEMORY_POLICY_PATTERN.search(text):
        return True
    if "curator" in text.lower() and _SAFETY_PROHIBIT_PATTERN.search(text):
        return True
    return False


def _looks_workflow(text: str) -> bool:
    if not text:
        return False
    numbered = len(_STEP_NUMBERED_PATTERN.findall(text)) >= 2
    keyword_hits = len(_STEP_KEYWORD_PATTERN.findall(text))
    shell_hits = len(_SHELL_COMMAND_PATTERN.findall(text))
    if _ZH_WORKFLOW_PATTERN.search(text):
        return True
    return numbered or (keyword_hits >= 2 and shell_hits >= 1) or (shell_hits >= 2)


def _is_tool_failure(record: dict[str, Any], text: str) -> bool:
    if bool(record.get("is_error")):
        return True
    try:
        payload = json.loads(text) if isinstance(text, str) and text.strip().startswith("{") else None
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, (int, float)) and int(exit_code) != 0:
            return True
        if payload.get("error") or payload.get("exception"):
            return True
    tool = (record.get("tool_name") or "").lower()
    if tool == MANAGE_TOOL_NAME and "cap" in text.lower():
        return True
    if _ERROR_KEYWORD_PATTERN.search(text):
        return True
    return False


def _is_ephemeral(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    if _ISSUE_ONLY_PATTERN.match(stripped):
        return True
    if _SHA_ONLY_PATTERN.match(stripped):
        return True
    if _PR_REF_PATTERN.search(stripped) and _EPHEMERAL_KEYWORDS.search(stripped):
        return True
    return False


def _detect_skill_md_size(record: dict[str, Any], text: str) -> int | None:
    explicit = record.get("skill_md_size")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return int(explicit)
    match = _SKILL_MD_SIZE_PATTERN.search(text or "")
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _is_near_cap(record: dict[str, Any], text: str) -> bool:
    size = _detect_skill_md_size(record, text)
    if size is not None and size >= SKILL_MD_NEAR_CAP_BYTES:
        return True
    if _NEAR_CAP_WORDS.search(text or ""):
        return True
    return False


def _looks_line_numbered_dump(text: str) -> bool:
    """Detect raw read_file-style source/doc dumps such as ``1|...`` lines."""
    return len(re.findall(r"(?:^|\n|\s)\d+\|", text or "")) >= 2


def _truncate(text: str, limit: int = 140) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def classify_record(record: dict[str, Any]) -> Candidate:
    """Classify a single redacted evidence record into one Candidate.

    Always returns a Candidate; unknown or low-confidence cases default to
    ``CANDIDATE_TYPE_IGNORE`` with ``requires_human_review=True``. The function
    never returns ``auto_apply_allowed=True``.
    """

    raw_text = _normalize_text(record.get("text"))
    text = _extract_inner_text(raw_text)
    refs = _evidence_refs(record)
    target_skill = record.get("target_skill") or None

    if _looks_line_numbered_dump(text) and not record.get("skill_md_size") and not record.get("is_error"):
        return Candidate(
            candidate_type=CANDIDATE_TYPE_IGNORE,
            title="line-numbered source dump",
            rationale="raw source/document dump is not a durable candidate signal",
            confidence=0.2,
            evidence_refs=refs,
            metadata={"category": "source_dump"},
        )

    if _is_near_cap(record, text):
        size = _detect_skill_md_size(record, text)
        rationale_bits = ["SKILL.md is at or near the 100k cap"]
        if size:
            rationale_bits.append(f"observed size ~{size} bytes")
        rationale = "; ".join(rationale_bits)
        return Candidate(
            candidate_type=CANDIDATE_TYPE_SKILL_UPDATE,
            title=f"near-cap SKILL.md for {target_skill or 'unknown skill'}",
            rationale=rationale,
            confidence=0.7,
            evidence_refs=refs,
            target_skill=target_skill,
            metadata={
                "direct_append_allowed": False,
                "reason": "skill_md_near_cap",
                "observed_size_bytes": size,
            },
        )

    if _is_safety_preference(text):
        return Candidate(
            candidate_type=CANDIDATE_TYPE_MEMORY,
            title="curator-evolver safety preference",
            rationale=_truncate(text),
            confidence=0.9,
            evidence_refs=refs,
            metadata={"category": "user_safety_preference"},
        )

    if _is_tool_failure(record, raw_text) or _is_tool_failure(record, text):
        tool = (record.get("tool_name") or "").lower() or "unknown"
        return Candidate(
            candidate_type=CANDIDATE_TYPE_REPLAY_BENCHMARK,
            title=f"replay benchmark for {tool} failure",
            rationale=_truncate(text),
            confidence=0.75,
            evidence_refs=refs,
            target_skill=target_skill,
            metadata={"tool_name": tool, "is_error": True},
        )

    if _looks_workflow(text):
        kind = CANDIDATE_TYPE_SKILL_UPDATE if target_skill else CANDIDATE_TYPE_SKILL_NEW
        return Candidate(
            candidate_type=kind,
            title=(
                f"workflow update for {target_skill}"
                if target_skill
                else "new workflow skill candidate"
            ),
            rationale=_truncate(text),
            confidence=0.65,
            evidence_refs=refs,
            target_skill=target_skill,
            metadata={"category": "workflow"},
        )

    if _is_ephemeral(text):
        return Candidate(
            candidate_type=CANDIDATE_TYPE_IGNORE,
            title="ephemeral progress note",
            rationale=_truncate(text) or "empty or short-term state",
            confidence=0.2,
            evidence_refs=refs,
            metadata={"category": "ephemeral"},
        )

    return Candidate(
        candidate_type=CANDIDATE_TYPE_IGNORE,
        title="unclassified evidence",
        rationale=_truncate(text) or "no recognizable signal",
        confidence=0.1,
        evidence_refs=refs,
        metadata={"category": "low_confidence"},
    )


def mine_candidates(records: Iterable[dict[str, Any]]) -> list[Candidate]:
    """Classify each redacted record into a Candidate, preserving input order."""
    return [classify_record(dict(r)) for r in records]
