"""Rendering, slash commands and the chat loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import questionary
    from rich.panel import Panel
    from rich.table import Table
except ImportError as exc:  # pragma: no cover - only without the optional dependencies
    raise SystemExit(f"Missing dependency ({exc.name}). Install it with: pip install -e \".[tui]\"") from exc

from .common import STYLE, console
from .harness import AgentHarness, _dumps
from .models import ChatTurnResult, ExitLauncher, ReturnToLauncher, SessionState, ToolTrace
from .session import _history_entry, _new_state, save_session

# ----------------------------------------------------------------------------------------- rendering


def render_history(state: SessionState) -> None:
    if not state.history:
        console.print("[yellow]No hay historial todavia.[/yellow]")
        return
    for item in state.history:
        inbound = item.get("direction") == "inbound"
        console.print(Panel.fit(str(item.get("body", "")), title="User" if inbound else state.agent_slug, border_style="green" if inbound else "magenta"))


def render_traces(traces: list[ToolTrace]) -> None:
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


def _set_contact_field(harness: AgentHarness, state: SessionState, key: str, value: str | None) -> None:
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


def _edit_slots_interactive(harness: AgentHarness, state: SessionState, session_file: Path, extra_candidates: list[str] | None = None) -> None:
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

    opening_message: str | None = None
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


def chat_loop(state: SessionState, session_file: Path, contact: dict[str, Any] | None = None) -> None:
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
            raise ReturnToLauncher() from None
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
