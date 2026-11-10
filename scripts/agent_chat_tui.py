"""Terminal chat with any agent bundle, with real OpenAI calls, to test a company's agents by hand.

Run it from ``backend/``::

    python scripts/agent_chat_tui.py                      # pick the agent from a menu
    python scripts/agent_chat_tui.py --company babynova   # only that company's agents
    python scripts/agent_chat_tui.py --agent family_aims_sam_text --contact-name Ana --contact-language es
    python scripts/agent_chat_tui.py --list

It discovers every ``companies/<company>/bundles/<slug>/graph.json`` and runs the agent's LangGraph graph in this
process (no HTTP server needed), showing turn by turn the spoken reply, the internal state and every tool call with
its arguments and response. Tool calls run in-process against the company's own backend app, so they hit the real
services configured in ``companies/<company>/.env`` (GoHighLevel, Google, Gmail): booking or cancelling an
appointment in a test conversation changes the real calendar.

The conversation state is the real LangGraph checkpoint (``<bundle>/sessions.db``, the same file the backend uses
without Postgres), so a conversation started here can be continued over HTTP with the same ``thread_id``. The history
shown by ``/history`` is a separate local log in ``tui_sessions/``.

Needs the optional dependencies: ``pip install -e ".[tui]"``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devenv  # noqa: E402

try:
    import httpx
    import questionary
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError as exc:  # pragma: no cover - only without the optional dependencies
    raise SystemExit(f"Missing dependency ({exc.name}). Install it with: pip install -e \".[tui]\"") from exc

BACKEND_ROOT = devenv.BACKEND_ROOT
COMPANIES_DIR = BACKEND_ROOT / "companies"
DEFAULT_SESSION_DIR = BACKEND_ROOT / "tui_sessions"
SESSIONS_DB = "sessions.db"

console = Console()

# Seeded into `history` (never spoken) so the very first `eval: "llm"` gate of an outbound-call agent has evidence to
# reason from; on a genuinely empty history that gate reliably falls back to "not answered" and the agent never speaks.
OUTBOUND_ANSWERED_SEED_LINE = "[system note] The outbound call has connected -- the contact answered and is on the line."

STYLE = questionary.Style([
    ("qmark", "fg:#00d7af bold"),
    ("question", "bold"),
    ("answer", "fg:#00d7af bold"),
    ("pointer", "fg:#00d7af bold"),
    ("highlighted", "fg:#00d7af bold"),
    ("selected", "fg:#00d7af bold"),
    ("separator", "fg:#6c6c6c"),
    ("instruction", "fg:#6c6c6c italic"),
])


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
    args: Dict[str, Any]
    status_code: Optional[int] = None
    response_body: Any = None


@dataclass
class SessionState:
    """What the TUI remembers about one conversation (the graph state lives in the checkpoint)."""

    agent: AgentRef
    thread_id: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    last_traces: List[ToolTrace] = field(default_factory=list)
    # "agent" (outbound/voice: the agent speaks first) or "user" (inbound/text: the user writes first).
    first_speaker: str = "agent"
    log_llm: bool = False
    log_http: bool = False
    log_tools: bool = False
    initial_slots: Dict[str, Any] = field(default_factory=dict)
    contact: Dict[str, Any] = field(default_factory=dict)

    @property
    def agent_slug(self) -> str:
        """Slug of the agent being tested."""
        return self.agent.slug


@dataclass
class ChatTurnResult:
    """Outcome of one turn."""

    messages: List[str]
    conversation_ended: bool
    current_state: Optional[str]
    traces: List[ToolTrace]


# ----------------------------------------------------------------------------------------- discovery


def discover_agents(company: Optional[str] = None, companies_dir: Path = COMPANIES_DIR) -> List[AgentRef]:
    """Finds the agent bundles of one or every company.

    Args:
        company: Only this company, or None for all.
        companies_dir: Folder with the companies.

    Returns:
        The bundles that have a ``graph.json``, sorted by company and slug (``_tools`` folders are skipped).
    """
    found: List[AgentRef] = []
    for company_dir in sorted(p for p in companies_dir.iterdir() if p.is_dir() and not p.name.startswith("_")) if companies_dir.exists() else []:
        if company and company_dir.name != company:
            continue
        bundles = company_dir / "bundles"
        if not bundles.is_dir():
            continue
        for bundle in sorted(bundles.iterdir()):
            if bundle.is_dir() and not bundle.name.startswith("_") and (bundle / "graph.json").is_file():
                found.append(AgentRef(company_dir.name, bundle.name, bundle))
    return found


def definitions_dir() -> Optional[Path]:
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

    def extract_structured(self, prompt: str, json_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Runs a structured extraction.

        Args:
            prompt: Prompt text.
            json_schema: JSON Schema of the expected object.

        Returns:
            The extracted object.
        """
        if self.enabled:
            console.print(Panel(prompt, title="LLM Prompt (extract_structured)", border_style="blue"))
            console.print(Panel(json.dumps(json_schema, indent=2, ensure_ascii=False), title="Schema", border_style="blue"))
        result = self.real_client.extract_structured(prompt, json_schema)
        if self.enabled:
            console.print(Panel(json.dumps(result, indent=2, ensure_ascii=False), title="LLM Response (JSON)", border_style="blue"))
        return result


class TracingToolClient(httpx.Client):
    """The HTTP client the graph uses for tool calls: records every POST and can print the traffic.

    Calls go to the company's own backend app in this process (no server needed). A route that answers 404 is
    retried on the other candidate routes, the way the backend does it (``agent_backend.tool_client``).
    """

    def __init__(self, *, trace_sink: List[ToolTrace], local_client: Any, route_suffixes: tuple[str, ...]) -> None:
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

        first: Optional[httpx.Response] = None
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
            ToolTrace(tool_name=used.rstrip("/").rsplit("/", 1)[-1], args=dict(body_out or {}), status_code=response.status_code, response_body=parsed)
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
        contact: Optional[Dict[str, Any]] = None,
        log_llm: bool = False,
        log_http: bool = False,
        llm_client: Any = None,
        local_client: Any = None,
    ) -> None:
        from agent_backend.app import create_app
        from agent_backend.bundle import load_bundle
        from agent_backend.settings import Settings
        from agent_runtime.runtime.graph_builder import build_graph
        from agent_runtime.runtime.knowledge_base import MarkdownKnowledgeBase
        from agent_runtime.runtime.llm_client import OpenAILLMClient
        from agent_runtime.targets.langgraph.runtime_artifact import runtime_artifact_from_dict
        from fastapi.testclient import TestClient
        from langgraph.checkpoint.sqlite import SqliteSaver

        self.agent = agent
        self.contact = contact or {}
        bundle = load_bundle(agent.root)
        artifact_json = json.loads(bundle.graph_path.read_text(encoding="utf-8"))
        self.artifact = runtime_artifact_from_dict(artifact_json)
        self._artifact_dict: Dict[str, Any] = artifact_json

        self._say_buffer: List[str] = []
        self._trace_buffer: List[ToolTrace] = []

        checkpointer = SqliteSaver(sqlite3.connect(str(agent.root / SESSIONS_DB), check_same_thread=False))

        settings = Settings(host="127.0.0.1", port=int(os.environ.get("PORT") or 8010), agents_dir=agent.root.parent, admin_token=None)
        self.tools_base_url = f"{settings.self_base_url}/agents/{agent.slug}/tools"
        self.tracing_http_client = TracingToolClient(
            trace_sink=self._trace_buffer,
            local_client=local_client or TestClient(create_app(settings)),
            route_suffixes=bundle.config.tool_route_suffixes,
        )
        self.tracing_http_client.enabled = log_http

        self.tracing_llm_client = TracingLLMClient(llm_client or OpenAILLMClient(api_key=os.environ.get("OPENAI_API_KEY")))
        self.tracing_llm_client.enabled = log_llm

        knowledge_base = MarkdownKnowledgeBase.from_file(bundle.knowledge_path) if bundle.knowledge_path.is_file() else None
        self.graph = build_graph(
            self.artifact,
            self.tracing_llm_client,
            tools_base_url=self.tools_base_url,
            tool_http_client=self.tracing_http_client,
            checkpointer=checkpointer,
            say_callback=self._say_buffer.append,
            knowledge_base=knowledge_base,
        )

    def discover_slot_names(self) -> List[str]:
        """Suggests editable slot names from the graph.

        Takes every ``capture`` name and every identifier in brackets in a ``store`` line, from the graph nodes and
        the global router handlers, minus the compiled constants.

        Returns:
            Sorted slot names.
        """
        names: set[str] = set()
        sources = [*(getattr(self.artifact.graph, "nodes", []) or []), *(getattr(self.artifact.global_router, "handlers", []) or [])]
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

    def discover_input_variables(self) -> List[Dict[str, str]]:
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
                {"name": str(item.get("name", "")).strip(), "description": str(item.get("description", "")).strip()}
                for item in data.get("input_variables", []) or []
                if str(item.get("name", "")).strip()
            ]
        except Exception:
            return []

    def discover_contact_fields(self) -> List[str]:
        """Finds the ``contact.*`` variables of this agent.

        Uses the declared input variables when the definitions are available; otherwise scans the graph texts for
        ``{{contact.X}}``.

        Returns:
            Sorted field names without the ``contact.`` prefix.
        """
        fields = {item["name"].split(".", 1)[1] for item in self.discover_input_variables() if item["name"].startswith("contact.")}
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
        opening_message: Optional[str] = None,
        initial_slots: Optional[Dict[str, Any]] = None,
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
            state = fresh_state(self.artifact, contact=self.contact, seed_history=[OUTBOUND_ANSWERED_SEED_LINE])
        if initial_slots:
            state["slots"].update(initial_slots)
        return self._finish(thread_id, self.graph.invoke(state, config))

    def turn(self, thread_id: str, message: Optional[str]) -> ChatTurnResult:
        """Runs one turn of an existing thread.

        Args:
            thread_id: Conversation key.
            message: What the user said.

        Returns:
            The turn's messages and state.

        Raises:
            RuntimeError: The thread is in progress and no message was given.
        """
        from agent_runtime.runtime.graph_builder import fresh_state
        from agent_runtime.runtime.session_resolver import resolve_session
        from langgraph.types import Command

        config = {"configurable": {"thread_id": thread_id}}
        self._say_buffer.clear()
        self._trace_buffer.clear()
        snapshot = self.graph.get_state(config)
        if resolve_session(snapshot.values, self.artifact.session_timeout_minutes) in ("new", "stale"):
            result = self.graph.invoke(fresh_state(self.artifact, contact=self.contact), config)
        else:
            if not message:
                raise RuntimeError("Este thread ya tiene una conversacion en curso -- se necesita un mensaje.")
            result = self.graph.invoke(Command(resume=message), config)
        return self._finish(thread_id, result)

    def _finish(self, thread_id: str, result: Dict[str, Any]) -> ChatTurnResult:
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

    def state_snapshot(self, thread_id: str) -> Dict[str, Any]:
        """Returns the real graph state of a thread.

        Args:
            thread_id: Conversation key.

        Returns:
            The checkpoint values; empty when the thread has not started.
        """
        return dict(self.graph.get_state({"configurable": {"thread_id": thread_id}}).values or {})


# ----------------------------------------------------------------------------------------- session log


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_entry(direction: str, body: str) -> Dict[str, Any]:
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


def load_session(session_file: Path, agents: List[AgentRef]) -> SessionState:
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
    matches = [a for a in agents if a.slug == data["agent_slug"] and (not data.get("company") or a.company == data["company"])]
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


def resolve_session_file(slug: str, session_file_arg: Optional[str]) -> Path:
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


# ----------------------------------------------------------------------------------------- rendering


def render_history(state: SessionState) -> None:
    if not state.history:
        console.print("[yellow]No hay historial todavia.[/yellow]")
        return
    for item in state.history:
        inbound = item.get("direction") == "inbound"
        console.print(Panel.fit(str(item.get("body", "")), title="User" if inbound else state.agent_slug, border_style="green" if inbound else "magenta"))


def render_traces(traces: List[ToolTrace]) -> None:
    if not traces:
        console.print("[dim]Sin tool calls en este turno.[/dim]")
        return
    for index, trace in enumerate(traces, start=1):
        code_label = "n/a" if trace.status_code is None else str(trace.status_code)
        body = trace.response_body
        response_text = _dumps(body) if isinstance(body, (dict, list)) else str(body)
        details = f"codigo: {code_label}\n\nargumentos:\n{_dumps(trace.args)}\n\nrespuesta:\n{response_text}"
        console.print(Panel(details, title=f"Tool {index}: {trace.tool_name}", border_style="cyan"))


def render_state(harness: AgentHarness, state: SessionState) -> None:
    snapshot = harness.state_snapshot(state.thread_id)
    if not snapshot:
        console.print("[yellow]Sin estado todavia -- la conversacion no arranco.[/yellow]")
        return
    console.print(f"[bold cyan]current_state:[/bold cyan] {snapshot.get('current_state') or '(ninguno)'}")
    slots = snapshot.get("slots", {})
    if slots:
        console.print_json(data=slots)
    else:
        console.print("[dim]Sin slots capturados todavia.[/dim]")


def ask_first_speaker() -> str:
    """Asks who speaks first in a brand-new thread.

    ``agent`` mirrors an outbound voice call: the graph is seeded with a note that the call connected so its
    "was the call answered?" gate resolves and the greeting plays. ``user`` mirrors an inbound chat: you type the
    opening message, seeded as the first thing the contact said.

    Returns:
        ``"agent"`` or ``"user"``.
    """
    choice = questionary.select(
        "Quien habla primero en esta conversacion?",
        choices=[
            questionary.Choice("El agente (saliente / voz)", value="agent"),
            questionary.Choice("El usuario (entrante / texto)", value="user"),
        ],
        style=STYLE,
    ).ask()
    return choice or "agent"


def render_chat_header(state: SessionState, session_file: Path) -> None:
    console.clear()
    console.print(f"[bold cyan]{state.agent_slug}[/bold cyan] -- agente de {state.agent.company} (backend)")
    console.print(f"Sesion: {session_file}")
    console.print(f"thread_id={state.thread_id}")
    console.print(f"Habla primero: {'el agente (saliente/voz)' if state.first_speaker == 'agent' else 'el usuario (entrante/texto)'}")
    on, off = "[green]ON[/green]", "[red]OFF[/red]"
    console.print(f"Logs: LLM={on if state.log_llm else off}, HTTP={on if state.log_http else off}, TOOLS={on if state.log_tools else off}")
    if state.initial_slots:
        console.print(f"Slots iniciales: {json.dumps(state.initial_slots, ensure_ascii=False)}")
    if state.contact:
        console.print(f"Contacto: {json.dumps(state.contact, ensure_ascii=False)}")
    console.print("Comandos: /help  /history  /traces  /state  /save  /new  /back  /exit\n")


def render_chat_help() -> None:
    table = Table(title="Comandos")
    table.add_column("Comando", style="cyan", no_wrap=True)
    table.add_column("Descripcion")
    rows = [
        ("/help", "Muestra esta ayuda"),
        ("/history", "Muestra el historial actual"),
        ("/traces", "Muestra las tool calls del ultimo turno"),
        ("/state", "Muestra current_state y los slots capturados (estado real del grafo)"),
        ("/slots", "Muestra los slots actuales (runtime) y los iniciales configurados"),
        ("/slots-edit", "Asistente interactivo para agregar/editar slots iniciales"),
        ("/slots-clear", "Limpia todos los slots iniciales configurados en esta sesion"),
        ("/contact", "Muestra los datos de contacto actuales para esta sesion"),
        ("/contact-edit", "Asistente interactivo para editar datos de contacto (contact.*)"),
        ("/contact-clear", "Limpia los datos de contacto configurados en esta sesion"),
        ("/input", "Lista variables de entrada del agente (input_variables.yaml) y sus valores actuales"),
        ("/input-edit", "Asistente interactivo para editar variables de entrada (contact.* y otras)"),
        ("/log-llm", "Prende/apaga el log de prompts y respuestas del LLM"),
        ("/log-http", "Prende/apaga el log de trafico HTTP (tool calls)"),
        ("/log-tools", "Prende/apaga la vista automatica de tool calls en cada turno"),
        ("/save", "Guarda la sesion actual (el historial local -- el estado real ya esta persistido)"),
        ("/new", "Empieza una conversacion nueva (thread_id nuevo)"),
        ("/back", "Guarda y vuelve al selector de agentes"),
        ("/exit", "Guarda y cierra el script"),
    ]
    for command, description in rows:
        table.add_row(command, description)
    console.print(table)


def _parse_slot_input(raw: str) -> Any:
    """Parses what the user typed as JSON, falling back to plain text; an empty string is ``None``.

    Args:
        raw: Text typed.

    Returns:
        The typed value.
    """
    if raw.strip() == "":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _show_slots(harness: AgentHarness, state: SessionState) -> None:
    runtime_slots = harness.state_snapshot(state.thread_id).get("slots", {})
    console.print("[bold cyan]Slots (runtime actual):[/bold cyan]")
    if runtime_slots:
        console.print_json(data=runtime_slots)
    else:
        console.print("[dim]Sin slots en runtime (el hilo puede no haber iniciado).[/dim]")
    console.print("\n[bold cyan]Slots iniciales configurados para este hilo:[/bold cyan]")
    if state.initial_slots:
        console.print_json(data=state.initial_slots)
    else:
        console.print("[dim]Ninguno (se pueden agregar con /slots-edit).[/dim]")


def _show_contact(state: SessionState) -> None:
    console.print("[bold cyan]Contacto (contact.*) para esta sesion:[/bold cyan]")
    if state.contact:
        console.print_json(data=state.contact)
    else:
        console.print("[dim]Ninguno (se pueden agregar con /contact-edit).[/dim]")


def _set_contact_field(harness: AgentHarness, state: SessionState, key: str, value: Optional[str]) -> None:
    if value is None or value.strip() == "":
        state.contact.pop(key, None)
        harness.contact.pop(key, None)
        console.print(f"[cyan]Campo eliminado:[/cyan] contact.{key}")
    else:
        state.contact[key] = value
        harness.contact[key] = value
        console.print(f"[cyan]Campo actualizado:[/cyan] contact.{key} = {value!r}")


def _edit_contact_interactive(harness: AgentHarness, state: SessionState, session_file: Path) -> None:
    discovered = set(harness.discover_contact_fields())
    while True:
        choices = []
        for key in sorted(discovered.union(state.contact.keys())):
            label = f"contact.{key} (actual: {state.contact[key]!r})" if key in state.contact else f"contact.{key} (sin valor)"
            choices.append(questionary.Choice(label, value=("field", key)))
        choices.append(questionary.Choice("Agregar campo nuevo…", value=("add-new", None)))
        choices.append(questionary.Choice("Terminar", value=("done", None)))
        selection = questionary.select("Selecciona un campo de contacto:", choices=choices, style=STYLE).ask()
        if not selection:
            break
        kind, key = selection
        if kind == "done":
            break
        if kind == "add-new":
            remaining = sorted(discovered.difference(state.contact.keys()))
            key = questionary.select(
                "Elige el campo a agregar:",
                choices=[
                    *(questionary.Choice(f"contact.{k}", value=k) for k in remaining),
                    questionary.Choice("Escribir nombre personalizado…", value="__custom__"),
                    questionary.Choice("Cancelar", value=None),
                ],
                style=STYLE,
            ).ask()
            if not key:
                continue
            if key == "__custom__":
                key = questionary.text("Nombre del campo (solo la parte despues de contact.):", style=STYLE).ask()
                if not key:
                    continue
                discovered.add(key)

        action = questionary.select(
            f"contact.{key} — elige una accion:",
            choices=[
                questionary.Choice("Editar valor", value="edit"),
                questionary.Choice("Vaciar / eliminar", value="clear"),
                questionary.Choice("Cancelar", value="cancel"),
            ],
            style=STYLE,
        ).ask()
        if action in (None, "cancel"):
            continue
        if action == "clear":
            _set_contact_field(harness, state, key, None)
        elif key == "language":
            language = questionary.select(
                "Elige idioma o 'Vaciar':",
                choices=[
                    questionary.Choice("Spanish", value="Spanish"),
                    questionary.Choice("English", value="English"),
                    questionary.Choice("Portuguese", value="Portuguese"),
                    questionary.Choice("Vaciar", value="__clear__"),
                ],
                style=STYLE,
            ).ask()
            if language is None:
                continue
            _set_contact_field(harness, state, key, None if language == "__clear__" else language)
        else:
            current = state.contact.get(key)
            value = questionary.text("Valor (texto):", default=str(current) if current is not None else "", style=STYLE).ask()
            if value is None:
                continue
            _set_contact_field(harness, state, key, value)
        save_session(state, session_file)
    save_session(state, session_file)


def _show_input_vars(harness: AgentHarness, state: SessionState) -> None:
    variables = harness.discover_input_variables()
    if not variables:
        console.print("[yellow]Este agente no declara input_variables.yaml o no tiene variables de entrada.[/yellow]")
        return
    table = Table(title="Variables de entrada (input_variables.yaml)")
    table.add_column("Variable", style="cyan", no_wrap=True)
    table.add_column("Valor actual")
    table.add_column("Descripcion", style="dim")
    for item in variables:
        name = item.get("name", "")
        current = state.contact.get(name.split(".", 1)[1]) if name.startswith("contact.") else state.initial_slots.get(name)
        shown = json.dumps(current, ensure_ascii=False) if not isinstance(current, str) else current
        table.add_row(name, str(shown) if shown is not None else "(sin valor)", item.get("description", ""))
    console.print(table)


def _edit_input_vars_interactive(harness: AgentHarness, state: SessionState, session_file: Path) -> None:
    others = [it["name"] for it in harness.discover_input_variables() if it.get("name") and not it["name"].startswith("contact.")]
    while True:
        choice = questionary.select(
            "Variables de entrada — que quieres editar?",
            choices=[
                questionary.Choice("contact.* (datos de contacto)", value="contact"),
                questionary.Choice("Otras variables (se aplican como slots iniciales)", value="other"),
                questionary.Choice("Terminar", value="done"),
            ],
            style=STYLE,
        ).ask()
        if choice in (None, "done"):
            break
        if choice == "contact":
            _edit_contact_interactive(harness, state, session_file)
        else:
            _edit_slots_interactive(harness, state, session_file, extra_candidates=others)


def _edit_slots_interactive(harness: AgentHarness, state: SessionState, session_file: Path, extra_candidates: Optional[List[str]] = None) -> None:
    """Interactive editor of the initial slots (JSON or plain text values; an empty value is null).

    Args:
        harness: Running harness.
        state: Session being edited.
        session_file: Where the session is saved.
        extra_candidates: More slot names to suggest.
    """
    candidates = set(harness.discover_slot_names())
    candidates.update(extra_candidates or [])
    snapshot = harness.state_snapshot(state.thread_id) or {}
    candidates.update((snapshot.get("slots") or {}).keys())
    candidates.update(state.initial_slots.keys())
    names = sorted(candidates)

    while True:
        choice = questionary.select(
            "Slots iniciales — que quieres hacer?",
            choices=[
                questionary.Choice("Agregar/editar un slot", value="set"),
                questionary.Choice("Eliminar un slot", value="del"),
                questionary.Choice("Terminar", value="done"),
            ],
            style=STYLE,
        ).ask()
        if choice in (None, "done"):
            break
        if choice == "set":
            key = questionary.autocomplete("Nombre del slot (puedes escribir uno nuevo):", choices=names, style=STYLE).ask()
            if not key:
                continue
            current = state.initial_slots.get(key)
            raw = questionary.text("Valor (JSON o texto; vacío= null):", default=json.dumps(current, ensure_ascii=False) if current is not None else "", style=STYLE).ask()
            value = _parse_slot_input(raw if raw is not None else "")
            state.initial_slots[key] = value
            if key not in names:
                names = sorted([*names, key])
            console.print(f"[cyan]Slot actualizado:[/cyan] {key} = {value!r}")
        elif choice == "del":
            if not state.initial_slots:
                console.print("[yellow]No hay slots iniciales para eliminar.[/yellow]")
                continue
            key = questionary.select("Elige el slot a eliminar:", choices=sorted(state.initial_slots.keys()), style=STYLE).ask()
            if key:
                state.initial_slots.pop(key, None)
                console.print(f"[cyan]Slot eliminado:[/cyan] {key}")

    save_session(state, session_file)
    if snapshot:
        wants_restart = questionary.confirm("La conversacion ya inició. ¿Reiniciar ahora (/new) para aplicar los slots iniciales?", default=False, style=STYLE).ask()
        if wants_restart:
            _restart_thread(state)
            run_first_turn(harness, state, session_file)


def _restart_thread(state: SessionState) -> None:
    state.thread_id = _new_state(state.agent).thread_id
    state.history = []
    state.last_traces = []
    console.print(f"[cyan]Conversacion nueva. thread_id={state.thread_id}[/cyan]")


def handle_chat_command(raw_text: str, state: SessionState, session_file: Path, harness: AgentHarness) -> bool:
    """Runs a ``/command``.

    Args:
        raw_text: What the user typed.
        state: Current session.
        session_file: Where the session is saved.
        harness: Running harness.

    Returns:
        True when the text was a known command.

    Raises:
        ReturnToLauncher: ``/back``.
        ExitLauncher: ``/exit``.
    """
    command = raw_text.strip().lower()
    simple = {
        "/help": render_chat_help,
        "/history": lambda: render_history(state),
        "/traces": lambda: render_traces(state.last_traces),
        "/state": lambda: render_state(harness, state),
        "/slots": lambda: _show_slots(harness, state),
        "/contact": lambda: _show_contact(state),
        "/input": lambda: _show_input_vars(harness, state),
    }
    if command in simple:
        simple[command]()
        return True
    if command == "/slots-edit":
        _edit_slots_interactive(harness, state, session_file)
    elif command == "/slots-clear":
        state.initial_slots = {}
        save_session(state, session_file)
        console.print("[cyan]Slots iniciales limpiados para este hilo.[/cyan]")
    elif command == "/contact-edit":
        _edit_contact_interactive(harness, state, session_file)
    elif command == "/contact-clear":
        state.contact = {}
        save_session(state, session_file)
        console.print("[cyan]Datos de contacto limpiados para esta sesion.[/cyan]")
    elif command == "/input-edit":
        _edit_input_vars_interactive(harness, state, session_file)
    elif command == "/log-llm":
        state.log_llm = not state.log_llm
        harness.tracing_llm_client.enabled = state.log_llm
        console.print(f"[cyan]Log de LLM {'encendido' if state.log_llm else 'apagado'}[/cyan]")
    elif command == "/log-http":
        state.log_http = not state.log_http
        harness.tracing_http_client.enabled = state.log_http
        console.print(f"[cyan]Log de trafico HTTP {'encendido' if state.log_http else 'apagado'}[/cyan]")
    elif command == "/log-tools":
        state.log_tools = not state.log_tools
        console.print(f"[cyan]Log de tools (vista automatica) {'encendido' if state.log_tools else 'apagado'}[/cyan]")
    elif command == "/save":
        save_session(state, session_file)
        console.print(f"[cyan]Sesion guardada en {session_file}[/cyan]")
    elif command == "/new":
        _restart_thread(state)
        run_first_turn(harness, state, session_file)
    elif command == "/back":
        save_session(state, session_file)
        raise ReturnToLauncher()
    elif command == "/exit":
        save_session(state, session_file)
        raise ExitLauncher(0)
    else:
        return False
    return True


def _show_turn(result: ChatTurnResult, state: SessionState, session_file: Path) -> None:
    for message in result.messages:
        console.print(Panel.fit(message, title=state.agent_slug, border_style="magenta"))
    state.history.extend(_history_entry("outbound", m) for m in result.messages)
    state.last_traces = result.traces
    if state.log_tools:
        render_traces(result.traces)
    if result.conversation_ended:
        console.print("[dim]-- conversacion finalizada (el grafo llego a un nodo terminal) --[/dim]")
    save_session(state, session_file)


def run_first_turn(harness: AgentHarness, state: SessionState, session_file: Path) -> None:
    """Kicks off a brand-new thread: asks who speaks first, offers to set contact and slots, then invokes it.

    Args:
        harness: Running harness.
        state: Session to start.
        session_file: Where the session is saved.
    """
    state.first_speaker = ask_first_speaker()
    render_chat_header(state, session_file)

    try:
        contact_fields = harness.discover_contact_fields()
    except Exception:
        contact_fields = []
    if contact_fields and not state.contact:
        if questionary.confirm(f"Detecte {len(contact_fields)} posibles campos de contacto. ¿Quieres configurarlos ahora?", default=False, style=STYLE).ask():
            _edit_contact_interactive(harness, state, session_file)
            render_chat_header(state, session_file)

    try:
        candidates = harness.discover_slot_names()
    except Exception:
        candidates = []
    if candidates and not state.initial_slots:
        if questionary.confirm(f"Detecte {len(candidates)} posibles slots del grafo. ¿Quieres configurarlos ahora?", default=False, style=STYLE).ask():
            _edit_slots_interactive(harness, state, session_file)
            render_chat_header(state, session_file)

    opening_message: Optional[str] = None
    if state.first_speaker == "user":
        while True:
            opening_message = console.input("\n[bold green]Primer mensaje (usuario)> [/bold green]").strip()
            if not opening_message:
                continue
            if opening_message.startswith("/") and handle_chat_command(opening_message, state, session_file, harness):
                render_chat_header(state, session_file)
                continue
            console.print(Panel.fit(opening_message, title="User", border_style="green"))
            state.history.append(_history_entry("inbound", opening_message))
            break

    try:
        result = harness.start(state.thread_id, state.first_speaker, opening_message, initial_slots=state.initial_slots)
    except Exception as exc:
        console.print(Panel.fit(str(exc), title="Error", border_style="red"))
        return
    _show_turn(result, state, session_file)


def chat_loop(state: SessionState, session_file: Path, contact: Optional[Dict[str, Any]] = None) -> None:
    harness = AgentHarness(
        state.agent,
        contact={**(contact or {}), **(state.contact or {})},
        log_llm=state.log_llm,
        log_http=state.log_http,
    )
    render_chat_header(state, session_file)
    render_chat_help()
    console.print()
    render_history(state)

    if not harness.state_snapshot(state.thread_id):
        run_first_turn(harness, state, session_file)

    while True:
        try:
            raw_text = console.input("\n[bold green]Tu> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            save_session(state, session_file)
            raise ReturnToLauncher()
        if not raw_text:
            continue
        if raw_text.startswith("/") and handle_chat_command(raw_text, state, session_file, harness):
            continue

        console.print(Panel.fit(raw_text, title="User", border_style="green"))
        state.history.append(_history_entry("inbound", raw_text))
        try:
            result = harness.turn(state.thread_id, raw_text)
        except Exception as exc:
            console.print(Panel.fit(str(exc), title="Error", border_style="red"))
            continue
        _show_turn(result, state, session_file)


def choose_agent(agents: List[AgentRef]) -> AgentRef:
    console.clear()
    choice = questionary.select(
        "Selecciona un agente:",
        choices=[*(questionary.Choice(a.label, value=a) for a in agents), questionary.Separator(), "Salir"],
        style=STYLE,
    ).ask()
    if choice in (None, "Salir"):
        raise ExitLauncher(0)
    return choice


def _contact_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """Builds the session's ``contact`` dict (CRM fields ``{{contact.X}}`` resolves against) from the ``--contact-*`` flags."""
    contact = {"name": args.contact_name, "email": args.contact_email, "phone": args.contact_phone, "language": args.contact_language}
    return {k: v for k, v in contact.items() if v is not None}


def load_company_environment(agent: AgentRef) -> None:
    """Puts the company's ``.env`` into ``os.environ`` (the file wins), so the backend code and tools see its settings.

    Args:
        agent: The agent about to run.
    """
    path = COMPANIES_DIR / agent.company / ".env"
    if path.is_file():
        os.environ.update(devenv.read_env_file(path))


def run_launcher(args: argparse.Namespace) -> int:
    agents = discover_agents(args.company)
    if not agents:
        console.print(f"[red]No se encontro ningun agente bajo {COMPANIES_DIR}[/red] (se espera companies/<empresa>/bundles/<slug>/graph.json).")
        return 1

    while True:
        try:
            if args.agent:
                matches = [a for a in agents if a.slug == args.agent]
                if not matches:
                    console.print(f"[red]Agente desconocido: {args.agent!r}. Disponibles: {[a.slug for a in agents]}[/red]")
                    return 1
                agent = matches[0]
            else:
                agent = choose_agent(agents)

            load_company_environment(agent)
            session_file = resolve_session_file(agent.slug, args.session_file)
            if session_file.exists():
                state = load_session(session_file, agents)
            else:
                state = _new_state(agent)
                if args.initial_slots:
                    try:
                        state.initial_slots = json.loads(args.initial_slots)
                    except json.JSONDecodeError as exc:
                        console.print(f"[red]Error parseando --initial-slots: {exc}[/red]")
                        return 1

            # command-line log flags override the saved ones
            state.log_llm = state.log_llm or args.log_llm
            state.log_http = state.log_http or args.log_http
            state.log_tools = state.log_tools or args.log_tools

            chat_loop(state, session_file, contact=_contact_from_args(args))
        except ReturnToLauncher:
            args.agent = None  # always back to the selector, not straight into the same agent again
            continue
        except ExitLauncher as exc:
            return int(exc.code or 0)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI para probar cualquier agente bajo companies/<empresa>/bundles/")
    parser.add_argument("--company", help="Solo los agentes de esta empresa (carpeta bajo companies/).")
    parser.add_argument("--agent", help="Slug del agente a abrir directo (ver --list). Si se omite, muestra el selector.")
    parser.add_argument("--session-file", help="Ruta del JSON de sesion a retomar/guardar")
    parser.add_argument("--list", action="store_true", help="Lista los agentes disponibles y sale")
    parser.add_argument("--initial-slots", help="JSON string con slots iniciales (ej. '{\"name\": \"Tomas\"}')")
    parser.add_argument("--log-llm", action="store_true", help="Habilita el log de LLM (prompts/respuestas) por defecto")
    parser.add_argument("--log-http", action="store_true", help="Habilita el log de trafico HTTP (tool calls) por defecto")
    parser.add_argument("--log-tools", action="store_true", help="Muestra por defecto las tool calls al final de cada turno")
    parser.add_argument("--contact-name", help="Simula un contacto ya conocido por el CRM -- nombre (resuelve {{contact.name}}).")
    parser.add_argument("--contact-email", help="Simula un contacto ya conocido -- email (resuelve {{contact.email}}).")
    parser.add_argument("--contact-phone", help="Simula un contacto ya conocido -- telefono (resuelve {{contact.phone}}).")
    parser.add_argument("--contact-language", help="Simula un contacto ya conocido -- idioma preferido (resuelve {{contact.language}}).")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    sys.path.insert(0, str(BACKEND_ROOT / "src"))
    if args.list:
        agents = discover_agents(args.company)
        if not agents:
            console.print(f"[yellow]Sin agentes bajo {COMPANIES_DIR}[/yellow]")
        for agent in agents:
            console.print(f"- {agent.label}")
        raise SystemExit(0)
    try:
        raise ExitLauncher(run_launcher(args))
    except ExitLauncher as exc:
        raise SystemExit(int(exc.code or 0))


if __name__ == "__main__":
    main()
