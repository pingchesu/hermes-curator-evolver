"""Import historical Hermes session files into the evidence store."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .storage import EvidenceStore, _compact


def default_sessions_dir() -> Path:
    return Path.home() / ".hermes" / "sessions"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def _tool_call_id(call: dict[str, Any], index: int) -> str:
    return str(call.get("id") or call.get("call_id") or call.get("tool_call_id") or f"tool-{index}")


def _tool_call_name_and_args(call: dict[str, Any]) -> tuple[str, Any]:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(function.get("name") or call.get("name") or "")
    raw_args = function.get("arguments", call.get("arguments", {}))
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {"raw_arguments": raw_args}
    else:
        args = raw_args or {}
    return name, args


def _tool_results_by_call_id(messages: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        call_id = message.get("tool_call_id") or message.get("id")
        if call_id:
            results[str(call_id)] = message.get("content")
    return results


def _tool_event_exists(store: EvidenceStore, *, session_id: str, task_id: str, tool_name: str) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM tool_events
            WHERE session_id = ? AND task_id = ? AND tool_name = ?
            LIMIT 1
            """,
            (session_id, task_id, tool_name),
        ).fetchone()
    return row is not None


def _turn_event_exists(
    store: EvidenceStore,
    *,
    session_id: str,
    model: str,
    platform: str,
    user_message: str,
    assistant_response: str,
) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM turn_events
            WHERE session_id = ? AND model = ? AND platform = ?
              AND user_preview = ? AND assistant_preview = ?
            LIMIT 1
            """,
            (
                session_id,
                model,
                platform,
                _compact(user_message, store.preview_chars),
                _compact(assistant_response, store.preview_chars),
            ),
        ).fetchone()
    return row is not None


def _session_event_exists(store: EvidenceStore, *, session_id: str) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM session_events WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
    return row is not None


def _iter_session_files(sessions_dir: Path, limit: int | None) -> list[Path]:
    files = sorted(sessions_dir.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None and limit > 0:
        return files[:limit]
    return files


def backfill_sessions(
    *,
    sessions_dir: str | Path | None = None,
    store: EvidenceStore | None = None,
    days: int = 30,
    limit: int | None = None,
) -> dict[str, Any]:
    """Backfill evidence from existing Hermes `session_*.json` transcripts.

    The importer is conservative: it records observable turns, session end markers,
    and tool calls with parseable `tool_calls`. Re-running it is duplicate-safe for
    the same session/tool/turn signatures.
    """

    target_dir = Path(sessions_dir) if sessions_dir is not None else default_sessions_dir()
    evidence = store or EvidenceStore()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(days or 1), 1))
    result: dict[str, Any] = {
        "sessions_dir": str(target_dir),
        "db_path": str(evidence.db_path),
        "days": max(int(days or 1), 1),
        "limit": limit,
        "sessions_seen": 0,
        "sessions_imported": 0,
        "sessions_skipped_old": 0,
        "files_failed": 0,
        "tool_events_imported": 0,
        "turn_events_imported": 0,
        "session_events_imported": 0,
    }
    if not target_dir.exists():
        result["missing"] = True
        return result

    for path in _iter_session_files(target_dir, limit):
        result["sessions_seen"] += 1
        try:
            data = _load_json(path)
        except (OSError, json.JSONDecodeError):
            result["files_failed"] += 1
            continue

        session_dt = _parse_dt(data.get("session_start")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if session_dt < cutoff:
            result["sessions_skipped_old"] += 1
            continue

        session_id = str(data.get("session_id") or path.stem.replace("session_", ""))
        model = str(data.get("model") or "")
        platform = str(data.get("platform") or "")
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        messages = [m for m in messages if isinstance(m, dict)]
        before = (
            result["tool_events_imported"],
            result["turn_events_imported"],
            result["session_events_imported"],
        )

        tool_results = _tool_results_by_call_id(messages)
        for index, message in enumerate(messages):
            calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            for call_index, call in enumerate(calls):
                if not isinstance(call, dict):
                    continue
                tool_name, args = _tool_call_name_and_args(call)
                if not tool_name:
                    continue
                call_id = _tool_call_id(call, call_index)
                task_id = f"backfill:{session_id}:{call_id}"
                if _tool_event_exists(evidence, session_id=session_id, task_id=task_id, tool_name=tool_name):
                    continue
                evidence.record_tool_call(
                    tool_name=tool_name,
                    args=args,
                    result=tool_results.get(call_id, ""),
                    task_id=task_id,
                    session_id=session_id,
                    created_at=_iso(session_dt),
                )
                result["tool_events_imported"] += 1

        pending_user: str | None = None
        for message in messages:
            role = message.get("role")
            content = _content_text(message.get("content"))
            if role == "user" and content.strip():
                pending_user = content
            elif role == "assistant" and pending_user and content.strip():
                if not _turn_event_exists(
                    evidence,
                    session_id=session_id,
                    model=model,
                    platform=platform,
                    user_message=pending_user,
                    assistant_response=content,
                ):
                    evidence.record_turn(
                        session_id=session_id,
                        user_message=pending_user,
                        assistant_response=content,
                        model=model,
                        platform=platform,
                        created_at=_iso(session_dt),
                    )
                    result["turn_events_imported"] += 1
                pending_user = None

        if not _session_event_exists(evidence, session_id=session_id):
            evidence.record_session_end(
                session_id=session_id,
                completed=True,
                interrupted=False,
                model=model,
                platform=platform,
                created_at=_iso(_parse_dt(data.get("last_updated")) or session_dt),
            )
            result["session_events_imported"] += 1

        after = (
            result["tool_events_imported"],
            result["turn_events_imported"],
            result["session_events_imported"],
        )
        if after != before:
            result["sessions_imported"] += 1

    return result
