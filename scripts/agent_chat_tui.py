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
import sys
from pathlib import Path
from typing import Any

import questionary

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devenv
from chat_tui.common import (  # noqa: F401  (re-exported for the tests)
    BACKEND_ROOT,
    COMPANIES_DIR,
    STYLE,
    console,
)
from chat_tui.harness import (  # noqa: F401  (re-exported for the tests)
    AgentHarness,
    TracingLLMClient,
    discover_agents,
)
from chat_tui.models import (  # noqa: F401  (re-exported for the tests)
    AgentRef,
    ExitLauncher,
    ReturnToLauncher,
    SessionState,
    ToolTrace,
)
from chat_tui.session import (  # noqa: F401  (re-exported for the tests)
    _history_entry,
    _new_state,
    load_session,
    resolve_session_file,
    save_session,
)
from chat_tui.ui import (  # noqa: F401  (re-exported for the tests)
    _parse_slot_input,
    chat_loop,
    handle_chat_command,
    render_history,
    render_traces,
)


def choose_agent(agents: list[AgentRef]) -> AgentRef:
    console.clear()
    choice = questionary.select(
        "Selecciona un agente:",
        choices=[*(questionary.Choice(a.label, value=a) for a in agents), questionary.Separator(), "Salir"],
        style=STYLE,
    ).ask()
    if choice in (None, "Salir"):
        raise ExitLauncher(0)
    return choice


def _contact_from_args(args: argparse.Namespace) -> dict[str, Any]:
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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


def main(argv: list[str] | None = None) -> None:
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
        raise SystemExit(int(exc.code or 0)) from exc


if __name__ == "__main__":
    main()
