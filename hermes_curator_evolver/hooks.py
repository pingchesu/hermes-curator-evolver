"""Hermes lifecycle hook callbacks."""

from __future__ import annotations

import logging
from typing import Any

from .storage import EvidenceStore

logger = logging.getLogger(__name__)


def _store() -> EvidenceStore:
    return EvidenceStore()


def on_post_tool_call(
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    result: Any = None,
    task_id: str = "",
    duration_ms: int | None = None,
    session_id: str = "",
    **kwargs: Any,
) -> None:
    """Record compact evidence after a tool call.

    Hooks must never break a Hermes session, so storage errors are logged and
    swallowed here by design.
    """
    try:
        _store().record_tool_call(
            tool_name=tool_name,
            args=args or {},
            result=result,
            task_id=task_id,
            session_id=session_id or str(kwargs.get("session_id") or ""),
            duration_ms=duration_ms,
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("curator-evolver post_tool_call skipped: %s", exc)
    except Exception as exc:  # Hook boundary: never interrupt Hermes sessions.
        logger.warning("curator-evolver post_tool_call failed: %s", exc)


def on_post_llm_call(
    session_id: str = "",
    user_message: str = "",
    assistant_response: str = "",
    model: str = "",
    platform: str = "",
    **kwargs: Any,
) -> None:
    """Record compact turn previews after a successful LLM turn."""
    try:
        _store().record_turn(
            session_id=session_id or str(kwargs.get("session_id") or ""),
            user_message=user_message or "",
            assistant_response=assistant_response or "",
            model=model or "",
            platform=platform or "",
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("curator-evolver post_llm_call skipped: %s", exc)
    except Exception as exc:  # Hook boundary: never interrupt Hermes sessions.
        logger.warning("curator-evolver post_llm_call failed: %s", exc)


def on_session_end(
    session_id: str = "",
    completed: bool = False,
    interrupted: bool = False,
    model: str = "",
    platform: str = "",
    **kwargs: Any,
) -> None:
    """Record session completion metadata."""
    try:
        _store().record_session_end(
            session_id=session_id or str(kwargs.get("session_id") or ""),
            completed=bool(completed),
            interrupted=bool(interrupted),
            model=model or "",
            platform=platform or "",
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("curator-evolver on_session_end skipped: %s", exc)
    except Exception as exc:  # Hook boundary: never interrupt Hermes sessions.
        logger.warning("curator-evolver on_session_end failed: %s", exc)
