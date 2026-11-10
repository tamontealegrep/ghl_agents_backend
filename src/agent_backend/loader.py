"""Builds and caches the runnable graph of each agent bundle."""

from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from agent_backend.auth import API_KEY_HEADER
from agent_backend.bundle import AgentBundle, load_bundle
from agent_backend.persistence.postgres import build_postgres_checkpointer, postgres_enabled
from agent_backend.settings import Settings
from agent_backend.tool_client import ToolRoutingClient
from agent_runtime.runtime.graph_builder import build_graph
from agent_runtime.runtime.knowledge_base import MarkdownKnowledgeBase
from agent_runtime.runtime.llm_client import OpenAILLMClient
from agent_runtime.targets.langgraph.runtime_artifact import RuntimeArtifact, runtime_artifact_from_dict

SESSIONS_DB = "sessions.db"

# say_callback is fixed once, at build_graph() time, not per request. A message-only node has no
# other way to surface its text, so a ContextVar keeps the buffer isolated per request; the chat
# routes set a fresh list before every invoke() and read it back after.
message_buffer: contextvars.ContextVar[list[str]] = contextvars.ContextVar("message_buffer")


def _say_callback(text: str) -> None:
    """Collects text a message-only node wants to say during this request.

    Args:
        text: Message produced by the graph.
    """
    message_buffer.get().append(text)


@dataclass(frozen=True)
class LoadedAgent:
    """A compiled agent ready to run.

    Attributes:
        artifact: Metadata such as ``agent_id`` and the session timeout.
        graph: The compiled, checkpointed LangGraph graph.
    """

    artifact: RuntimeArtifact
    graph: Any


class AgentRegistry:
    """Owns the loaded agents of one running backend.

    Replaces module-level caches so tests (and several apps in one process)
    never share state.

    Args:
        settings: Process settings; used to locate bundles and tool routes.
    """

    def __init__(self, settings: Settings) -> None:
        """Creates an empty registry bound to the process settings."""
        self._settings = settings
        self._agents: dict[str, LoadedAgent] = {}
        self._lock = threading.Lock()

    def tools_base_url(self, slug: str) -> str:
        """Returns where the agent's tool calls land.

        Args:
            slug: Agent slug.

        Returns:
            Absolute URL of the tool mount on this same server: the company's
            (``/agents/<company>/tools``) when ``COMPANY`` is set, else the agent's.
        """
        owner = self._settings.company or slug
        return f"{self._settings.self_base_url}/agents/{owner}/tools"

    def _build(self, slug: str) -> LoadedAgent:
        """Builds the graph from the bundle currently on disk, without caching.

        Persistence uses a shared Postgres saver when ``DATABASE_URL`` is set;
        otherwise a per-agent SQLite file inside the bundle folder (fine for
        local development, lost with the container filesystem).

        Args:
            slug: Agent slug.

        Returns:
            The freshly built agent.

        Raises:
            FileNotFoundError: If the bundle or its ``graph.json`` is missing.
        """
        bundle: AgentBundle = load_bundle(self._settings.agents_dir / slug)
        artifact = runtime_artifact_from_dict(json.loads(bundle.graph_path.read_text(encoding="utf-8")))

        if postgres_enabled():
            checkpointer = build_postgres_checkpointer()
        else:
            conn = sqlite3.connect(str(bundle.root / SESSIONS_DB), check_same_thread=False)
            checkpointer = SqliteSaver(conn)

        # A document too large for the model fails here, at startup, not on every question.
        knowledge_base = (
            MarkdownKnowledgeBase.from_file(bundle.knowledge_path)
            if bundle.knowledge_path.is_file()
            else None
        )
        graph = build_graph(
            artifact,
            OpenAILLMClient(api_key=os.environ.get("OPENAI_API_KEY")),
            tools_base_url=self.tools_base_url(slug),
            tool_http_client=ToolRoutingClient(
                route_suffixes=bundle.config.tool_route_suffixes,
                headers={API_KEY_HEADER: self._settings.api_token} if self._settings.api_token else None,
            ),
            checkpointer=checkpointer,
            say_callback=_say_callback,
            knowledge_base=knowledge_base,
        )
        return LoadedAgent(artifact=artifact, graph=graph)

    def get(self, slug: str) -> LoadedAgent:
        """Returns the agent, building it on first use.

        Args:
            slug: Agent slug.

        Returns:
            The cached agent.

        Raises:
            FileNotFoundError: If the bundle does not exist.
        """
        with self._lock:
            cached = self._agents.get(slug)
        if cached is not None:
            return cached
        built = self._build(slug)
        with self._lock:
            return self._agents.setdefault(slug, built)

    def reload(self, slug: str) -> LoadedAgent:
        """Rebuilds one agent from disk and swaps it in without a restart.

        In-flight turns keep the pair they already fetched, and other agents
        are untouched.

        Args:
            slug: Agent slug.

        Returns:
            The newly built agent.

        Raises:
            FileNotFoundError: If the bundle does not exist.
        """
        built = self._build(slug)
        with self._lock:
            self._agents[slug] = built
        return built
