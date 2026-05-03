"""Candidate generation for skill evolution review."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"
_RERANKER_MODEL = "bge-reranker-v2-m3"


def semantic_model_plan() -> dict[str, str]:
    return {
        "embedding": _EMBEDDING_MODEL,
        "reranker": _RERANKER_MODEL,
        "purpose": "Candidate generation only: embed skill/evidence text, then rerank likely related skills before human/model review.",
        "default": "off; no model download is performed unless semantic mode is explicitly enabled by a future integration.",
    }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[\w-]+", text, flags=re.UNICODE) if len(token) > 1}


def _skill_files(skills_dir: Path) -> list[Path]:
    if not skills_dir.exists():
        return []
    return sorted(path for path in skills_dir.rglob("SKILL.md") if path.is_file())


def _skill_name(path: Path, skills_dir: Path) -> str:
    try:
        rel = path.parent.relative_to(skills_dir)
        if str(rel) != ".":
            return rel.parts[-1]
    except ValueError:
        pass
    return path.parent.name


def _lexical_candidates(query: str, skills_dir: Path, limit: int) -> list[dict[str, Any]]:
    query_terms = _tokens(query)
    rows: list[dict[str, Any]] = []
    for path in _skill_files(skills_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        terms = _tokens(text)
        overlap = sorted(query_terms & terms)
        score = len(overlap) / max(len(query_terms), 1)
        rows.append(
            {
                "skill_name": _skill_name(path, skills_dir),
                "path": str(path),
                "score": round(score, 4),
                "reasons": [f"matched `{term}`" for term in overlap[:8]],
            }
        )
    rows.sort(key=lambda item: (-float(item["score"]), item["skill_name"]))
    return rows[:limit]


def find_skill_candidates(
    *, query: str, skills_dir: str | Path, semantic: bool = False, limit: int = 10
) -> dict[str, Any]:
    """Find candidate skills for review.

    v0.3 keeps semantic mode as an explicit plan/interface. The default lexical
    implementation is dependency-free and never downloads models.
    """

    plan = semantic_model_plan()
    if semantic:
        return {
            "mode": "semantic-plan",
            "query": query,
            "models": {"embedding": plan["embedding"], "reranker": plan["reranker"]},
            "model_downloaded": False,
            "candidates": [],
            "note": "Semantic model execution is opt-in future integration; no model was downloaded or run.",
        }
    return {
        "mode": "lexical",
        "query": query,
        "models": {"embedding": "not-used", "reranker": "not-used"},
        "model_downloaded": False,
        "candidates": _lexical_candidates(query, Path(skills_dir), max(1, limit)),
    }
