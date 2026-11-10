"""Data carried by the terminal chat: agents, tool traces, session state and turn results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ExitLauncher(SystemExit):
    """Raised to close the whole script."""


class ReturnToLauncher(Exception):
    """Raised to go back to the agent selector."""


@dataclass
class AgentRef:
    """An agent bundle found on disk.

    Attributes:
        company: Folder under ``companies/``.
        slug: Bundle folder name.
        root: Absolute path of the bundle.
    """

    company: str
    slug: str
    root: Path

    @property
    def label(self) -> str:
        """Text shown in the selector."""
        return f"{self.slug}  ({self.company})"


@dataclass
class ToolTrace:
    """One tool call made during a turn."""

    tool_name: str
    args: dict[str, Any]
    status_code: int | None = None
    response_body: Any = None


@dataclass
class SessionState:
    """What the TUI remembers about one conversation (the graph state lives in the checkpoint)."""

    agent: AgentRef
    thread_id: str
    history: list[dict[str, Any]] = field(default_factory=list)
    last_traces: list[ToolTrace] = field(default_factory=list)
    # "agent" (outbound/voice: the agent speaks first) or "user" (inbound/text: the user writes first).
    first_speaker: str = "agent"
    log_llm: bool = False
    log_http: bool = False
    log_tools: bool = False
    initial_slots: dict[str, Any] = field(default_factory=dict)
    contact: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_slug(self) -> str:
        """Slug of the agent being tested."""
        return self.agent.slug


@dataclass
class ChatTurnResult:
    """Outcome of one turn."""

    messages: list[str]
    conversation_ended: bool
    current_state: str | None
    traces: list[ToolTrace]
