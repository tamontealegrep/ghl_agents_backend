"""Finds agents and runs one in-process, tracing every LLM and tool call."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    import httpx
    from rich.panel import Panel
except ImportError as exc:  # pragma: no cover - only without the optional dependencies
    raise SystemExit(f'Missing dependency ({exc.name}). Install it with: pip install -e ".[tui]"') from exc

from .common import BACKEND_ROOT, COMPANIES_DIR, OUTBOUND_ANSWERED_SEED_LINE, SESSIONS_DB, console
from .models import AgentRef, ChatTurnResult, ToolTrace

# ----------------------------------------------------------------------------------------- discovery


def discover_agents(company: str | None = None, companies_dir: Path = COMPANIES_DIR) -> list[AgentRef]:
    """Finds the agent bundles of one or every company.

    Args:
        company: Only this company, or None for all.
        companies_dir: Folder with the companies.

    Returns:
        The bundles that have a ``graph.json``, sorted by company and slug (``_tools`` folders are skipped).
    """
    found: list[AgentRef] = []
    for company_dir in (
        sorted(p for p in companies_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
        if companies_dir.exists()
        else []
    ):
        if company and company_dir.name != company:
            continue
        bundles = company_dir / "bundles"
        if not bundles.is_dir():
            continue
        for bundle in sorted(bundles.iterdir()):
            if bundle.is_dir() and not bundle.name.startswith("_") and (bundle / "graph.json").is_file():
                found.append(AgentRef(company_dir.name, bundle.name, bundle))
    return found


def definitions_dir() -> Path | None:
    """Folder with the compiler's agent definitions, used only to describe the input variables.

    Returns:
        ``AGENT_DEFINITIONS_DIR`` if set, else the sibling ``compiler/definitions`` when it exists, else None.
    """
    configured = os.environ.get("AGENT_DEFINITIONS_DIR", "").strip()
    path = Path(configured) if configured else BACKEND_ROOT.parent / "compiler" / "definitions"
    return path if path.is_dir() else None


# ----------------------------------------------------------------------------------------- tracing


class TracingLLMClient:
    """Wraps an LLM client and prints prompts and responses while ``enabled``."""

    def __init__(self, real_client: Any) -> None:
        self.real_client = real_client
        self.enabled = False

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Runs a plain completion.

        Args:
            prompt: Prompt text.
            temperature: Sampling temperature.

        Returns:
            The model's text.
        """
        if self.enabled:
            console.print(Panel(prompt, title="LLM Prompt (complete)", border_style="blue"))
        result = self.real_client.complete(prompt, temperature=temperature)
        if self.enabled:
            console.print(Panel(result, title="LLM Response", border_style="blue"))
        return result

    def extract_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """Runs a structured extraction.

        Args:
            prompt: Prompt text.
            json_schema: JSON Schema of the expected object.

        Returns:
            The extracted object.
        """
        if self.enabled:
            console.print(Panel(prompt, title="LLM Prompt (extract_structured)", border_style="blue"))
            console.print(
                Panel(
                    json.dumps(json_schema, indent=2, ensure_ascii=False), title="Schema", border_style="blue"
                )
            )
        result = self.real_client.extract_structured(prompt, json_schema)
        if self.enabled:
            console.print(
                Panel(
                    json.dumps(result, indent=2, ensure_ascii=False),
                    title="LLM Response (JSON)",
                    border_style="blue",
                )
            )
        return result


class TracingToolClient(httpx.Client):
    """The HTTP client the graph uses for tool calls: records every POST and can print the traffic.

    Calls go to the company's own backend app in this process (no server needed). A route that answers 404 is
    retried on the other candidate routes, the way the backend does it (``agent_backend.tool_client``).
    """

    def __init__(
        self, *, trace_sink: list[ToolTrace], local_client: Any, route_suffixes: tuple[str, ...]
    ) -> None:
        super().__init__()
        self._trace_sink = trace_sink
        self._local_client = local_client
        self._route_suffixes = route_suffixes
        self.enabled = False

    def post(self, url: Any, *args: Any, json: Any = None, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        """Posts a tool call, printing and recording it.

        Args:
            url: The requested tool URL.
            args: Forwarded to the HTTP client.
            json: Request body.
            kwargs: Forwarded to the HTTP client.

        Returns:
            The first non-404 response, or the first response when every candidate answers 404.
        """
        from agent_backend.tool_client import candidate_urls

        body_out = json
        if self.enabled:
            console.print(f"[dim]HTTP POST {url}[/dim]")
            if body_out:
                console.print(Panel(_dumps(body_out), title="HTTP Request Body", border_style="cyan"))

        first: httpx.Response | None = None
        used = str(url)
        for candidate in candidate_urls(str(url), self._route_suffixes):
            response = self._local_client.post(candidate, *args, json=body_out, **kwargs)
            if response.status_code != 404:
                first, used = response, candidate
                break
            first = first or response
        assert first is not None
        response = first

        if self.enabled:
            console.print(f"[dim]HTTP Response {response.status_code}[/dim]")
            try:
                console.print(Panel(_dumps(response.json()), title="HTTP Response Body", border_style="cyan"))
            except ValueError:
                console.print(Panel(response.text, title="HTTP Response Body", border_style="cyan"))

        try:
            parsed: Any = response.json()
        except ValueError:
            parsed = response.text
        self._trace_sink.append(
            ToolTrace(
                tool_name=used.rstrip("/").rsplit("/", 1)[-1],
                args=dict(body_out or {}),
                status_code=response.status_code,
                response_body=parsed,
            )
        )
        return response


def _dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------------------------- harness


class AgentHarness:
    """One real LangGraph graph per TUI session, reused turn after turn through the same ``thread_id``.

    Args:
        agent: The bundle to run.
        contact: CRM fields of the simulated contact.
        log_llm: Print LLM prompts and responses.
        log_http: Print the tool traffic.
        llm_client: Replacement for the OpenAI client (tests).
        local_client: Replacement for the in-process backend client (tests).
    """

    def __init__(
        self,
        agent: AgentRef,
        contact: dict[str, Any] | None = None,
        log_llm: bool = False,
        log_http: bool = False,
        llm_client: Any = None,
        local_client: Any = None,
    ) -> None:
        from fastapi.testclient import TestClient
        from langgraph.checkpoint.sqlite import SqliteSaver

        from agent_backend.app import create_app
        from agent_backend.bundle import load_bundle
        from agent_backend.settings import Settings
        from agent_runtime.runtime.graph_builder import build_graph
        from agent_runtime.runtime.knowledge_base import MarkdownKnowledgeBase
        from agent_runtime.runtime.llm_client import OpenAILLMClient
        from agent_runtime.targets.langgraph.runtime_artifact import runtime_artifact_from_dict

        self.agent = agent
        self.contact = contact or {}
        bundle = load_bundle(agent.root)
        artifact_json = json.loads(bundle.graph_path.read_text(encoding="utf-8"))
        self.artifact = runtime_artifact_from_dict(artifact_json)
        self._artifact_dict: dict[str, Any] = artifact_json

        self._say_buffer: list[str] = []
        self._trace_buffer: list[ToolTrace] = []

        checkpointer = SqliteSaver(sqlite3.connect(str(agent.root / SESSIONS_DB), check_same_thread=False))

        settings = Settings(
            host="127.0.0.1",
            port=int(os.environ.get("PORT") or 8010),
            agents_dir=agent.root.parent,
            admin_token=None,
        )
        self.tools_base_url = f"{settings.self_base_url}/agents/{agent.slug}/tools"
        self.tracing_http_client = TracingToolClient(
            trace_sink=self._trace_buffer,
            local_client=local_client or TestClient(create_app(settings)),
            route_suffixes=bundle.config.tool_route_suffixes,
        )
        self.tracing_http_client.enabled = log_http

        self.tracing_llm_client = TracingLLMClient(
            llm_client or OpenAILLMClient(api_key=os.environ.get("OPENAI_API_KEY"))
        )
        self.tracing_llm_client.enabled = log_llm

        knowledge_base = (
            MarkdownKnowledgeBase.from_file(bundle.knowledge_path)
            if bundle.knowledge_path.is_file()
            else None
        )
        self.graph = build_graph(
            self.artifact,
            self.tracing_llm_client,
            tools_base_url=self.tools_base_url,
            tool_http_client=self.tracing_http_client,
            checkpointer=checkpointer,
            say_callback=self._say_buffer.append,
            knowledge_base=knowledge_base,
        )

    def discover_slot_names(self) -> list[str]:
        """Suggests editable slot names from the graph.

        Takes every ``capture`` name and every identifier in brackets in a ``store`` line, from the graph nodes and
        the global router handlers, minus the compiled constants.

        Returns:
            Sorted slot names.
        """
        names: set[str] = set()
        sources = [
            *(getattr(self.artifact.graph, "nodes", []) or []),
            *(getattr(self.artifact.global_router, "handlers", []) or []),
        ]
        for item in sources:
            for capture in getattr(item, "capture", []) or []:
                try:
                    names.add(str(capture[0]))
                except Exception:
                    pass
            for line in getattr(item, "store", []) or []:
                names.update(re.findall(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", line))
        for constant in getattr(self.artifact, "constants", {}).keys():
            names.discard(constant)
        return sorted(names)

    def discover_input_variables(self) -> list[dict[str, str]]:
        """Reads the agent's declared input variables from its definition, if the definitions are available.

        Returns:
            ``[{"name", "description"}]``; empty when the definitions folder or the file is missing.
        """
        root = definitions_dir()
        if root is None:
            return []
        try:
            import yaml

            path = root / self.agent.slug / "input_variables.yaml"
            if not path.exists():
                return []
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return [
                {
                    "name": str(item.get("name", "")).strip(),
                    "description": str(item.get("description", "")).strip(),
                }
                for item in data.get("input_variables", []) or []
                if str(item.get("name", "")).strip()
            ]
        except Exception:
            return []

    def discover_contact_fields(self) -> list[str]:
        """Finds the ``contact.*`` variables of this agent.

        Uses the declared input variables when the definitions are available; otherwise scans the graph texts for
        ``{{contact.X}}``.

        Returns:
            Sorted field names without the ``contact.`` prefix.
        """
        fields = {
            item["name"].split(".", 1)[1]
            for item in self.discover_input_variables()
            if item["name"].startswith("contact.")
        }
        if fields:
            return sorted(fields)

        def strings(node: Any):
            if isinstance(node, str):
                yield node
            elif isinstance(node, list):
                for child in node:
                    yield from strings(child)
            elif isinstance(node, dict):
                for child in node.values():
                    yield from strings(child)

        pattern = re.compile(r"\{\{\s*contact\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
        for text in strings(self._artifact_dict):
            fields.update(pattern.findall(text))
        return sorted(fields)

    def start(
        self,
        thread_id: str,
        first_speaker: str = "agent",
        opening_message: str | None = None,
        initial_slots: dict[str, Any] | None = None,
    ) -> ChatTurnResult:
        """Runs the very first turn of a brand-new thread.

        Args:
            thread_id: Conversation key.
            first_speaker: ``"agent"`` seeds a note that the call connected (outbound/voice); ``"user"`` seeds
                ``opening_message`` as the first thing the contact said (inbound/text).
            opening_message: The contact's first message when ``first_speaker`` is ``"user"``.
            initial_slots: Slots to preset before the graph runs.

        Returns:
            The turn's messages and state.
        """
        from agent_runtime.runtime.graph_builder import fresh_state

        config = {"configurable": {"thread_id": thread_id}}
        self._say_buffer.clear()
        self._trace_buffer.clear()
        if first_speaker == "user":
            state = fresh_state(
                self.artifact,
                contact=self.contact,
                seed_history=[f"user: {opening_message}"] if opening_message else [],
                seed_last_user_message=opening_message or "",
            )
        else:
            state = fresh_state(
                self.artifact, contact=self.contact, seed_history=[OUTBOUND_ANSWERED_SEED_LINE]
            )
        if initial_slots:
            state["slots"].update(initial_slots)
        return self._finish(thread_id, self.graph.invoke(state, config))

    def turn(self, thread_id: str, message: str | None) -> ChatTurnResult:
        """Runs one turn of an existing thread.

        Args:
            thread_id: Conversation key.
            message: What the user said.

        Returns:
            The turn's messages and state.

        Raises:
            RuntimeError: The thread is in progress and no message was given.
        """
        from langgraph.types import Command

        from agent_runtime.runtime.graph_builder import fresh_state
        from agent_runtime.runtime.session_resolver import resolve_session

        config = {"configurable": {"thread_id": thread_id}}
        self._say_buffer.clear()
        self._trace_buffer.clear()
        snapshot = self.graph.get_state(config)
        if resolve_session(snapshot.values, self.artifact.session_timeout_minutes) in ("new", "stale"):
            result = self.graph.invoke(fresh_state(self.artifact, contact=self.contact), config)
        else:
            if not message:
                raise RuntimeError(
                    "Este thread ya tiene una conversacion en curso -- se necesita un mensaje."
                )
            result = self.graph.invoke(Command(resume=message), config)
        return self._finish(thread_id, result)

    def _finish(self, thread_id: str, result: dict[str, Any]) -> ChatTurnResult:
        config = {"configurable": {"thread_id": thread_id}}
        interrupts = result.get("__interrupt__")
        messages = list(self._say_buffer)
        if interrupts:
            messages.extend(interrupts[0].value.get("prompt", []))
        final_state = self.graph.get_state(config).values
        return ChatTurnResult(
            messages=messages,
            conversation_ended=not interrupts,
            current_state=final_state.get("current_state"),
            traces=list(self._trace_buffer),
        )

    def state_snapshot(self, thread_id: str) -> dict[str, Any]:
        """Returns the real graph state of a thread.

        Args:
            thread_id: Conversation key.

        Returns:
            The checkpoint values; empty when the thread has not started.
        """
        return dict(self.graph.get_state({"configurable": {"thread_id": thread_id}}).values or {})
