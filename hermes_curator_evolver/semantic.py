"""Candidate generation for skill evolution review."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

_EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"
_EMBEDDING_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
_RERANKER_MODEL = "bge-reranker-v2-m3"
_RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
_DEFAULT_SEMANTIC_DEVICE = "auto"
_DEFAULT_SEMANTIC_TEXT_LIMIT = 512


def semantic_model_plan() -> dict[str, str]:
    return {
        "embedding": _EMBEDDING_MODEL,
        "embedding_model_id": _EMBEDDING_MODEL_ID,
        "reranker": _RERANKER_MODEL,
        "reranker_model_id": _RERANKER_MODEL_ID,
        "purpose": "Candidate generation only: embed skill/evidence text, then rerank likely related skills before human/model review.",
        "default": "off; no model download is performed unless semantic execution is explicitly requested.",
        "runtime_device": _semantic_device() or "auto",
        "text_limit_chars": str(_semantic_text_limit()),
    }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[\w-]+", text, flags=re.UNICODE) if len(token) > 1}


def _semantic_device() -> str | None:
    value = os.getenv("HERMES_CURATOR_EVOLVER_SEMANTIC_DEVICE", _DEFAULT_SEMANTIC_DEVICE).strip()
    if not value or value.lower() == "auto":
        return None
    return value


def _semantic_text_limit() -> int:
    raw = os.getenv("HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT", str(_DEFAULT_SEMANTIC_TEXT_LIMIT)).strip()
    try:
        return max(200, int(raw))
    except ValueError:
        return _DEFAULT_SEMANTIC_TEXT_LIMIT


def _semantic_text(text: str) -> str:
    limit = _semantic_text_limit()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated for semantic candidate ranking]"


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


def _read_skill_rows(skills_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _skill_files(skills_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append({"skill_name": _skill_name(path, skills_dir), "path": str(path), "text": text})
    return rows


def _lexical_candidates(query: str, skills_dir: Path, limit: int) -> list[dict[str, Any]]:
    query_terms = _tokens(query)
    rows: list[dict[str, Any]] = []
    for item in _read_skill_rows(skills_dir):
        terms = _tokens(str(item["text"]))
        overlap = sorted(query_terms & terms)
        score = len(overlap) / max(len(query_terms), 1)
        rows.append(
            {
                "skill_name": item["skill_name"],
                "path": item["path"],
                "score": round(score, 4),
                "reasons": [f"matched `{term}`" for term in overlap[:8]],
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), row["skill_name"]))
    return rows[:limit]


def _as_vectors(raw: Any) -> list[list[float]]:
    if hasattr(raw, "detach"):
        raw = raw.detach().cpu().tolist()
    elif hasattr(raw, "tolist"):
        raw = raw.tolist()
    return [[float(value) for value in vector] for vector in raw]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _cosine(left: list[float], right: list[float]) -> float:
    denom = _norm(left) * _norm(right)
    if denom == 0:
        return 0.0
    return _dot(left, right) / denom


def _encode(backend: Any, texts: list[str]) -> list[list[float]]:
    raw = backend.encode(
        texts,
        normalize_embeddings=False,
        show_progress_bar=False,
        batch_size=1,
        convert_to_tensor=False,
    )
    return _as_vectors(raw)


def _predict_rerank(backend: Any, pairs: list[tuple[str, str]]) -> list[float]:
    if hasattr(backend, "predict"):
        raw = backend.predict(pairs)
    elif callable(backend):
        raw = backend(pairs)
    else:
        raise TypeError("reranker backend must expose predict(pairs) or be callable")
    if hasattr(raw, "detach"):
        raw = raw.detach().cpu().tolist()
    elif hasattr(raw, "tolist"):
        raw = raw.tolist()
    return [float(value) for value in raw]


def _load_embedding_backend() -> Any:
    from sentence_transformers import SentenceTransformer

    device = _semantic_device()
    return SentenceTransformer(_EMBEDDING_MODEL_ID, device=device)


def _load_reranker_backend() -> Any:
    from sentence_transformers import CrossEncoder

    device = _semantic_device()
    return CrossEncoder(_RERANKER_MODEL_ID, device=device)


def _semantic_candidates(
    *,
    query: str,
    skills_dir: Path,
    limit: int,
    embedding_backend: Any,
    reranker_backend: Any | None = None,
    model_downloaded: bool | str = False,
) -> dict[str, Any]:
    rows = _read_skill_rows(skills_dir)
    if not rows:
        return {
            "mode": "semantic",
            "query": query,
            "models": {"embedding": _EMBEDDING_MODEL, "reranker": _RERANKER_MODEL},
            "model_downloaded": model_downloaded,
            "model_executed": True,
            "reranker_executed": False,
            "candidates": [],
        }

    texts = [_semantic_text(query)] + [_semantic_text(str(row["text"])) for row in rows]
    vectors = _encode(embedding_backend, texts)
    query_vector, skill_vectors = vectors[0], vectors[1:]
    candidates: list[dict[str, Any]] = []
    for row, vector in zip(rows, skill_vectors):
        score = _cosine(query_vector, vector)
        candidates.append(
            {
                "skill_name": row["skill_name"],
                "path": row["path"],
                "score": round(score, 6),
                "reasons": ["semantic embedding similarity"],
                "text_preview": str(row["text"])[:500],
            }
        )
    candidates.sort(key=lambda row: (-float(row["score"]), row["skill_name"]))
    candidates = candidates[: max(1, limit)]
    mode = "semantic"
    reranker_executed = False

    if reranker_backend is not None and candidates:
        pairs = [(query, str(item.get("text_preview", ""))) for item in candidates]
        rerank_scores = _predict_rerank(reranker_backend, pairs)
        for item, score in zip(candidates, rerank_scores):
            item["embedding_score"] = item["score"]
            item["score"] = round(float(score), 6)
            item["reasons"].append("reranker relevance score")
        candidates.sort(key=lambda row: (-float(row["score"]), row["skill_name"]))
        mode = "semantic-reranked"
        reranker_executed = True

    for item in candidates:
        item.pop("text_preview", None)

    return {
        "mode": mode,
        "query": query,
        "models": {"embedding": _EMBEDDING_MODEL, "reranker": _RERANKER_MODEL},
        "runtime": {"device": _semantic_device() or "auto", "text_limit_chars": _semantic_text_limit()},
        "model_downloaded": model_downloaded,
        "model_executed": True,
        "reranker_executed": reranker_executed,
        "candidates": candidates,
    }


def find_skill_candidates(
    *,
    query: str,
    skills_dir: str | Path,
    semantic: bool = False,
    limit: int = 10,
    embedding_backend: Any | None = None,
    reranker_backend: Any | None = None,
    load_models: bool = False,
    load_reranker: bool = False,
) -> dict[str, Any]:
    """Find candidate skills for review.

    Lexical mode is dependency-free. Semantic mode remains safe by default: it
    returns the execution plan unless a backend is injected by tests/callers or
    model loading is explicitly requested.
    """

    plan = semantic_model_plan()
    path = Path(skills_dir)
    bounded_limit = max(1, int(limit or 10))
    if semantic:
        if embedding_backend is None and load_models:
            try:
                embedding_backend = _load_embedding_backend()
            except Exception as exc:  # pragma: no cover - depends on local ML setup
                return {
                    "mode": "semantic-unavailable",
                    "query": query,
                    "models": {"embedding": plan["embedding"], "reranker": plan["reranker"]},
                    "model_downloaded": "unknown",
                    "model_executed": False,
                    "candidates": [],
                    "error": str(exc),
                }
        if reranker_backend is None and load_reranker:
            try:
                reranker_backend = _load_reranker_backend()
            except Exception as exc:  # pragma: no cover - depends on local ML setup
                return {
                    "mode": "semantic-reranker-unavailable",
                    "query": query,
                    "models": {"embedding": plan["embedding"], "reranker": plan["reranker"]},
                    "model_downloaded": "unknown",
                    "model_executed": embedding_backend is not None,
                    "reranker_executed": False,
                    "candidates": [],
                    "error": str(exc),
                }
        if embedding_backend is not None:
            try:
                return _semantic_candidates(
                    query=query,
                    skills_dir=path,
                    limit=bounded_limit,
                    embedding_backend=embedding_backend,
                    reranker_backend=reranker_backend,
                    model_downloaded="unknown" if load_models else False,
                )
            except Exception as exc:  # pragma: no cover - depends on local ML runtime
                return {
                    "mode": "semantic-execution-unavailable",
                    "query": query,
                    "models": {"embedding": plan["embedding"], "reranker": plan["reranker"]},
                    "runtime": {"device": _semantic_device() or "auto", "text_limit_chars": _semantic_text_limit()},
                    "model_downloaded": "unknown" if load_models else False,
                    "model_executed": False,
                    "reranker_executed": False,
                    "candidates": [],
                    "error": str(exc),
                }
        return {
            "mode": "semantic-plan",
            "query": query,
            "models": {"embedding": plan["embedding"], "reranker": plan["reranker"]},
            "model_downloaded": False,
            "model_executed": False,
            "candidates": [],
            "note": "Semantic model execution is opt-in; no model was downloaded or run.",
        }
    return {
        "mode": "lexical",
        "query": query,
        "models": {"embedding": "not-used", "reranker": "not-used"},
        "model_downloaded": False,
        "model_executed": False,
        "candidates": _lexical_candidates(query, path, bounded_limit),
    }
