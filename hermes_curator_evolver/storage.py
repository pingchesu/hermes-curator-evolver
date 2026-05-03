"""SQLite evidence storage for Hermes Curator Evolver."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import default_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    duration_ms INTEGER,
    is_error INTEGER NOT NULL,
    skill_name TEXT,
    args_json TEXT NOT NULL,
    result_preview TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_events_created ON tool_events(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_events_skill ON tool_events(skill_name);

CREATE TABLE IF NOT EXISTS turn_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    platform TEXT NOT NULL,
    user_preview TEXT NOT NULL,
    assistant_preview TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turn_events_created ON turn_events(created_at);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    completed INTEGER NOT NULL,
    interrupted INTEGER NOT NULL,
    model TEXT NOT NULL,
    platform TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_events_created ON session_events(created_at);
"""

MANAGE_TOOL_NAME = "skill" + "_" + "manage"
SKILL_TOOL_NAMES = {"skill_view", MANAGE_TOOL_NAME}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).isoformat(
        timespec="seconds"
    )


def _compact(value: Any, limit: int) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = repr(value)
    text = text.replace("\\x00", "")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _json_dumps(value: Any, limit: int) -> str:
    try:
        text = json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = json.dumps({"repr": repr(value)}, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return json.dumps({"preview": text[: max(limit - 1, 0)] + "…"}, ensure_ascii=False)


def _looks_like_error(result: Any) -> bool:
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith("{"):
            try:
                return _looks_like_error(json.loads(stripped))
            except json.JSONDecodeError:
                pass
    if isinstance(result, dict):
        if result.get("error") or result.get("success") is False:
            return True
        if result.get("exit_code") not in (None, 0):
            return True
        return False
    text = _compact(result, 2048).lower()
    markers = ("traceback", "exception", "error", "failed", "exit_code")
    return any(marker in text for marker in markers)


def _extract_skill_name(tool_name: str, args: Any) -> str | None:
    if not isinstance(args, dict):
        return None
    if tool_name in SKILL_TOOL_NAMES:
        name = args.get("name") or args.get("skill") or args.get("skill_name")
        return str(name) if name else None
    skills = args.get("skills")
    if isinstance(skills, list) and skills:
        first = skills[0]
        return str(first) if first else None
    return None


class EvidenceStore:
    """Small SQLite repository for local curator evidence."""

    def __init__(self, db_path: str | Path | None = None, preview_chars: int = 500):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.preview_chars = preview_chars
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    def record_tool_call(
        self,
        *,
        tool_name: str,
        args: Any,
        result: Any,
        task_id: str = "",
        session_id: str = "",
        duration_ms: int | None = None,
    ) -> None:
        skill_name = _extract_skill_name(tool_name, args)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_events (
                    created_at, session_id, task_id, tool_name, duration_ms,
                    is_error, skill_name, args_json, result_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    session_id or "",
                    task_id or "",
                    tool_name or "",
                    duration_ms,
                    1 if _looks_like_error(result) else 0,
                    skill_name,
                    _json_dumps(args, self.preview_chars * 2),
                    _compact(result, self.preview_chars),
                ),
            )

    def record_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_response: str,
        model: str = "",
        platform: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO turn_events (
                    created_at, session_id, model, platform,
                    user_preview, assistant_preview
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    session_id or "",
                    model or "",
                    platform or "",
                    _compact(user_message, self.preview_chars),
                    _compact(assistant_response, self.preview_chars),
                ),
            )

    def record_session_end(
        self,
        *,
        session_id: str,
        completed: bool,
        interrupted: bool,
        model: str = "",
        platform: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_events (
                    created_at, session_id, completed, interrupted, model, platform
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    session_id or "",
                    1 if completed else 0,
                    1 if interrupted else 0,
                    model or "",
                    platform or "",
                ),
            )

    def summary(self, *, days: int, skill: str | None = None) -> dict[str, Any]:
        where = "created_at >= ?"
        params: list[Any] = [cutoff_iso(days)]
        if skill:
            where += " AND skill_name = ?"
            params.append(skill)
        with self.connect() as conn:
            tool_counts = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS tool_events,
                    COALESCE(SUM(is_error), 0) AS error_events,
                    COALESCE(SUM(CASE WHEN skill_name IS NOT NULL THEN 1 ELSE 0 END), 0)
                        AS skill_events
                FROM tool_events
                WHERE {where}
                """,
                params,
            ).fetchone()
            turn_events = conn.execute(
                "SELECT COUNT(*) AS count FROM turn_events WHERE created_at >= ?",
                [cutoff_iso(days)],
            ).fetchone()["count"]
            session_events = conn.execute(
                "SELECT COUNT(*) AS count FROM session_events WHERE created_at >= ?",
                [cutoff_iso(days)],
            ).fetchone()["count"]
            skills = conn.execute(
                f"""
                SELECT skill_name, COUNT(*) AS event_count, COALESCE(SUM(is_error), 0) AS errors
                FROM tool_events
                WHERE {where} AND skill_name IS NOT NULL
                GROUP BY skill_name
                ORDER BY event_count DESC, skill_name ASC
                LIMIT 20
                """,
                params,
            ).fetchall()
            tools = conn.execute(
                f"""
                SELECT tool_name, COUNT(*) AS event_count, COALESCE(SUM(is_error), 0) AS errors
                FROM tool_events
                WHERE {where}
                GROUP BY tool_name
                ORDER BY event_count DESC, tool_name ASC
                LIMIT 20
                """,
                params,
            ).fetchall()
        return {
            "tool_events": int(tool_counts["tool_events"]),
            "error_events": int(tool_counts["error_events"]),
            "skill_events": int(tool_counts["skill_events"]),
            "turn_events": int(turn_events),
            "session_events": int(session_events),
            "skills": [dict(row) for row in skills],
            "tools": [dict(row) for row in tools],
        }

    def recent_tool_events(
        self, *, days: int, skill: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        where = "created_at >= ?"
        params: list[Any] = [cutoff_iso(days)]
        if skill:
            where += " AND skill_name = ?"
            params.append(skill)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT created_at, session_id, task_id, tool_name, duration_ms,
                       is_error, skill_name, args_json, result_preview
                FROM tool_events
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_turns(self, *, days: int, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, session_id, model, platform, user_preview, assistant_preview
                FROM turn_events
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [cutoff_iso(days), limit],
            ).fetchall()
        return [dict(row) for row in rows]
