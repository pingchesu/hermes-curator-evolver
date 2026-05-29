"""SQLite-backed review queue for curator-evolver candidates.

Persistence-only. This module stores candidate JSON and lifecycle status; it
never writes to user memory or skill files.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidates import CANDIDATE_TYPES, Candidate

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

VALID_STATUSES = {STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_candidates (
    id TEXT PRIMARY KEY,
    candidate_type TEXT NOT NULL,
    title TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    target_skill TEXT,
    auto_apply_allowed INTEGER NOT NULL DEFAULT 0,
    requires_human_review INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_candidates_status
    ON review_candidates(status);
CREATE INDEX IF NOT EXISTS idx_review_candidates_type
    ON review_candidates(candidate_type);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "candidate_type": row["candidate_type"],
        "title": row["title"],
        "rationale": row["rationale"],
        "confidence": float(row["confidence"]),
        "evidence_refs": json.loads(row["evidence_refs_json"] or "[]"),
        "target_skill": row["target_skill"],
        "auto_apply_allowed": bool(row["auto_apply_allowed"]),
        "requires_human_review": bool(row["requires_human_review"]),
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class ReviewQueue:
    """Tiny SQLite review queue for candidate triage.

    Stores already-classified Candidate objects only. The queue is
    write-once-per-id: enqueueing the same id twice is a no-op so that mining
    can be re-run safely.
    """

    def __init__(self, db_path: Path | str, *, create: bool = True) -> None:
        self.db_path = Path(db_path)
        self._create = create
        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        elif not self.db_path.exists():
            raise FileNotFoundError(f"review queue DB does not exist: {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        if self._create:
            conn = sqlite3.connect(self.db_path)
        else:
            conn = sqlite3.connect(f"file:{self.db_path.resolve().as_posix()}?mode=rw", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, candidate: Candidate) -> bool:
        """Insert a candidate; return True if newly inserted, False if duplicate."""
        if candidate.candidate_type not in CANDIDATE_TYPES:
            raise ValueError(
                f"refusing to enqueue unknown candidate_type "
                f"{candidate.candidate_type!r}"
            )
        if candidate.auto_apply_allowed:
            raise ValueError("refusing to enqueue auto_apply_allowed=True candidate")
        if not candidate.requires_human_review:
            raise ValueError("refusing to enqueue requires_human_review=False candidate")
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO review_candidates (
                    id,
                    candidate_type,
                    title,
                    rationale,
                    confidence,
                    evidence_refs_json,
                    target_skill,
                    auto_apply_allowed,
                    requires_human_review,
                    metadata_json,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.candidate_type,
                    candidate.title,
                    candidate.rationale,
                    float(candidate.confidence),
                    json.dumps(list(candidate.evidence_refs), ensure_ascii=False),
                    candidate.target_skill,
                    int(bool(candidate.auto_apply_allowed)),
                    int(bool(candidate.requires_human_review)),
                    json.dumps(candidate.metadata or {}, ensure_ascii=False, sort_keys=True),
                    STATUS_PENDING,
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.rowcount == 1

    def list_candidates(
        self,
        *,
        status: str | None = None,
        candidate_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status filter {status!r}")
            clauses.append("status = ?")
            params.append(status)
        if candidate_type is not None:
            if candidate_type not in CANDIDATE_TYPES:
                raise ValueError(
                    f"invalid candidate_type filter {candidate_type!r}"
                )
            clauses.append("candidate_type = ?")
            params.append(candidate_type)
        sql = "SELECT * FROM review_candidates"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def update_status(self, candidate_id: str, new_status: str) -> bool:
        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"new_status must be one of {sorted(VALID_STATUSES)!r}"
            )
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE review_candidates
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, now, candidate_id),
            )
            conn.commit()
            return cur.rowcount > 0
