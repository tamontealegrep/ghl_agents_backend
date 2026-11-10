"""The local conversation log (``tui_sessions/``) shown by ``/history``."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import BACKEND_ROOT, DEFAULT_SESSION_DIR
from .models import AgentRef, SessionState

# ----------------------------------------------------------------------------------------- session log


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _history_entry(direction: str, body: str) -> dict[str, Any]:
    return {"direction": direction, "body": body, "at": _now_iso()}


def _new_state(agent: AgentRef) -> SessionState:
    return SessionState(agent=agent, thread_id=f"tui-{uuid.uuid4().hex[:12]}")


def save_session(state: SessionState, session_file: Path) -> None:
    """Writes the local history and the session settings.

    Args:
        state: Session to save.
        session_file: Destination file.
    """
    payload = {
        "company": state.agent.company,
        "agent_slug": state.agent_slug,
        "thread_id": state.thread_id,
        "history": state.history,
        "first_speaker": state.first_speaker,
        "log_llm": state.log_llm,
        "log_http": state.log_http,
        "log_tools": state.log_tools,
        "initial_slots": state.initial_slots,
        "contact": state.contact,
        "saved_at": _now_iso(),
    }
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_session(session_file: Path, agents: list[AgentRef]) -> SessionState:
    """Reads a saved session.

    Args:
        session_file: File written by ``save_session``.
        agents: Agents available now, to find the one the session belongs to.

    Returns:
        The restored session.

    Raises:
        KeyError: The session's agent no longer exists.
    """
    data = json.loads(session_file.read_text(encoding="utf-8"))
    matches = [
        a
        for a in agents
        if a.slug == data["agent_slug"] and (not data.get("company") or a.company == data["company"])
    ]
    if not matches:
        raise KeyError(f"Agent {data['agent_slug']!r} of the session no longer exists")
    return SessionState(
        agent=matches[0],
        thread_id=data["thread_id"],
        history=data.get("history", []),
        first_speaker=data.get("first_speaker", "agent"),
        log_llm=data.get("log_llm", False),
        log_http=data.get("log_http", False),
        log_tools=data.get("log_tools", False),
        initial_slots=data.get("initial_slots", {}),
        contact=data.get("contact", {}),
    )


def resolve_session_file(slug: str, session_file_arg: str | None) -> Path:
    """Chooses the local log file of a session.

    Args:
        slug: Agent slug.
        session_file_arg: ``--session-file`` value, if any.

    Returns:
        That file (relative paths are taken from ``backend/``), or a new timestamped file in ``tui_sessions/``.
    """
    if session_file_arg:
        path = Path(session_file_arg)
        return path if path.is_absolute() else (BACKEND_ROOT / path).resolve()
    DEFAULT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_SESSION_DIR / f"{slug}_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
