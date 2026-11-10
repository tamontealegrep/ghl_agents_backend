"""HTTP side of the playground: sessions that run an agent in this process and record everything that happens.

A session wraps one ``AgentHarness`` (a real LangGraph graph, real OpenAI calls, tool calls answered by the
company's own backend app in this process) and keeps a *timeline*: the user's messages, what the agent says, every
LLM call, every tool (HTTP) call, the state after each turn and the manual edits. The page reads the timeline and
shows each call compressed; the detail is in the event itself.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import devenv
from chat_tui.common import COMPANIES_DIR, DEFAULT_SESSION_DIR
from chat_tui.harness import AgentHarness, discover_agents
from chat_tui.models import AgentRef
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from agent_backend.contact import with_default_ids

STATIC_DIR = Path(__file__).resolve().parent / "static"
SAVE_DIR = DEFAULT_SESSION_DIR / "playground"
HarnessFactory = Callable[..., AgentHarness]


class NoLLM:
    """LLM stand-in used to read an agent's metadata without an OpenAI key."""

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Always fails: the metadata harness never runs the graph.

        Args:
            prompt: Ignored.
            temperature: Ignored.
        """
        raise RuntimeError("This harness only reads metadata.")

    def extract_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """Always fails: the metadata harness never runs the graph.

        Args:
            prompt: Ignored.
            json_schema: Ignored.
        """
        raise RuntimeError("This harness only reads metadata.")


class NewSession(BaseModel):
    """Body of ``POST /api/sessions``."""

    company: str
    slug: str
    first_speaker: str = "user"
    contact: dict[str, Any] = Field(default_factory=dict)
    initial_slots: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """Body of ``POST /api/sessions/{id}/messages``."""

    text: str


class StateEdit(BaseModel):
    """Body of ``PATCH /api/sessions/{id}/state``; a null value removes the entry."""

    slots: dict[str, Any] = Field(default_factory=dict)
    contact: dict[str, Any] = Field(default_factory=dict)


class StartConfig(BaseModel):
    """Body of ``PUT /api/sessions/{id}/config``: what a conversation that has not started begins with."""

    contact: dict[str, Any] = Field(default_factory=dict)
    initial_slots: dict[str, Any] = Field(default_factory=dict)


class Resume(BaseModel):
    """Body of ``POST /api/sessions/resume``."""

    file: str


def _json_safe(value: Any) -> Any:
    """Turns anything the graph state can hold into JSON data.

    Args:
        value: Any value.

    Returns:
        The same value with unknown objects replaced by their text.
    """
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _slots_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compares two slot dictionaries.

    Args:
        before: Slots before the turn.
        after: Slots after the turn.

    Returns:
        ``{"added": {...}, "changed": {name: {"from", "to"}}, "removed": [...]}``.
    """
    return {
        "added": {k: v for k, v in after.items() if k not in before},
        "changed": {
            k: {"from": before[k], "to": v} for k, v in after.items() if k in before and before[k] != v
        },
        "removed": [k for k in before if k not in after],
    }


def _default_first_speaker(slug: str) -> str:
    """Guesses who speaks first: voice agents call out, text agents wait for the contact.

    Args:
        slug: Agent slug.

    Returns:
        ``"agent"`` or ``"user"``.
    """
    return "agent" if "voice" in slug else "user"


class Session:
    """One conversation under test.

    Attributes:
        id: Public id used in the URLs.
        agent: The bundle being tested.
        harness: Runs the graph.
        thread_id: LangGraph thread (the checkpoint lives in the bundle's ``sessions.db``).
        first_speaker: ``"agent"`` or ``"user"``.
        contact: Contact fields of the simulated lead.
        initial_slots: Slots preset before the graph runs.
        timeline: Everything that happened, in order.
        started: Whether the graph already ran.
        ended: Whether the last turn finished the conversation.
        turn_count: Number of turns run.
    """

    def __init__(
        self,
        agent: AgentRef,
        harness: AgentHarness,
        *,
        thread_id: str | None = None,
        first_speaker: str = "user",
        contact: dict[str, Any] | None = None,
        initial_slots: dict[str, Any] | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.agent = agent
        self.harness = harness
        self.thread_id = thread_id or f"pg-{uuid.uuid4().hex[:12]}"
        self.first_speaker = first_speaker
        self.contact = dict(contact or {})
        self.initial_slots = dict(initial_slots or {})
        self.timeline: list[dict[str, Any]] = []
        self.started = False
        self.ended = False
        self.turn_count = 0
        self.created_at = time.time()
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ state
    def snapshot(self) -> dict[str, Any]:
        """Reads the live graph state.

        Returns:
            ``current_state``, ``slots``, ``contact`` and the whole checkpoint as ``raw``.
        """
        values = _json_safe(self.harness.state_snapshot(self.thread_id)) if self.started else {}
        return {
            "current_state": values.get("current_state"),
            "slots": values.get("slots") or {},
            "contact": values.get("contact") or {},
            "raw": values,
        }

    def public(self) -> dict[str, Any]:
        """The session as the page needs it.

        Returns:
            Identity, settings, state and the timeline.
        """
        return {
            "id": self.id,
            "company": self.agent.company,
            "slug": self.agent.slug,
            "thread_id": self.thread_id,
            "first_speaker": self.first_speaker,
            "started": self.started,
            "ended": self.ended,
            "turns": self.turn_count,
            "contact": self.contact,
            "initial_slots": self.initial_slots,
            "state": self.snapshot(),
            "timeline": self.timeline,
        }

    # ------------------------------------------------------------------ turns
    def _load_company_environment(self) -> None:
        path = COMPANIES_DIR / self.agent.company / ".env"
        if path.is_file():
            os.environ.update(devenv.read_env_file(path))

    def _record(self, events: list[dict[str, Any]], *, error: str | None = None) -> None:
        for event in events:
            self.timeline.append({**_json_safe(event), "turn": self.turn_count})
        if error:
            self.timeline.append({"kind": "error", "turn": self.turn_count, "at": time.time(), "text": error})

    def _run_turn(self, runner: Callable[[], Any]) -> None:
        """Runs one graph turn and appends what it produced to the timeline.

        Args:
            runner: Calls the harness (``start`` or ``turn``).
        """
        self._load_company_environment()
        before = self.snapshot()["slots"] if self.started else {}
        self.turn_count += 1
        began = time.perf_counter()
        error: str | None = None
        result = None
        try:
            result = runner()
        except Exception as exc:  # the page shows the failure in the conversation
            error = f"{type(exc).__name__}: {exc}"
        self.started = True
        self._record(list(self.harness.events), error=error)
        after = self.snapshot()
        if result is not None:
            self.ended = bool(result.conversation_ended)
        self.timeline.append(
            {
                "kind": "state",
                "turn": self.turn_count,
                "at": time.time(),
                "current_state": after["current_state"],
                "ended": self.ended,
                "ms": round((time.perf_counter() - began) * 1000),
                "diff": _slots_diff(before, after["slots"]),
            }
        )
        self.save()

    def start(self) -> None:
        """Runs the first turn of an agent that speaks first (outbound calls, voice)."""
        self._run_turn(lambda: self.harness.start(self.thread_id, "agent", None, self.initial_slots or None))

    def say(self, text: str) -> None:
        """Sends the contact's message, starting the conversation if needed.

        Args:
            text: What the contact says.
        """
        self.timeline.append({"kind": "user", "turn": self.turn_count + 1, "at": time.time(), "text": text})
        if not self.started:
            self._run_turn(
                lambda: self.harness.start(self.thread_id, "user", text, self.initial_slots or None)
            )
        else:
            self._run_turn(lambda: self.harness.turn(self.thread_id, text))

    def edit(self, slots: dict[str, Any], contact: dict[str, Any]) -> None:
        """Edits the variables of the conversation (before or after it starts).

        Args:
            slots: Flow variables to set (null removes).
            contact: Contact fields to set (null removes).
        """
        if self.started:
            self.harness.update_state(self.thread_id, slots=slots, contact=contact)
            self.harness.contact = {
                **self.harness.contact,
                **{k: v for k, v in contact.items() if v is not None},
            }
        else:
            for target, changes in ((self.initial_slots, slots), (self.contact, contact)):
                for name, value in changes.items():
                    if value is None:
                        target.pop(name, None)
                    else:
                        target[name] = value
            self.harness.contact = dict(self.contact)
        self.timeline.append(
            {
                "kind": "edit",
                "turn": self.turn_count,
                "at": time.time(),
                "slots": _json_safe(slots),
                "contact": _json_safe(contact),
                "live": self.started,
            }
        )
        self.save()

    # ------------------------------------------------------------------ persistence
    def file(self) -> Path:
        """Where this session is saved.

        Returns:
            ``tui_sessions/playground/<agent>__<thread>.json``.
        """
        return SAVE_DIR / f"{self.agent.slug}__{self.thread_id}.json"

    def save(self) -> None:
        """Writes the session (settings and timeline) so it can be reopened."""
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "company": self.agent.company,
            "slug": self.agent.slug,
            "thread_id": self.thread_id,
            "first_speaker": self.first_speaker,
            "contact": self.contact,
            "initial_slots": self.initial_slots,
            "started": self.started,
            "ended": self.ended,
            "turns": self.turn_count,
            "created_at": self.created_at,
            "saved_at": time.time(),
            "timeline": self.timeline,
        }
        self.file().write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )


def create_app(
    harness_factory: HarnessFactory = AgentHarness,
    companies_dir: Path = COMPANIES_DIR,
    only_company: str | None = None,
) -> FastAPI:
    """Builds the playground application.

    Args:
        harness_factory: Builds an ``AgentHarness``; tests pass one with a fake LLM.
        companies_dir: Where the companies' bundles are.
        only_company: Lists only this company's agents.

    Returns:
        The FastAPI app.
    """
    app = FastAPI(title="Agent playground")
    sessions: dict[str, Session] = {}
    app.state.sessions = sessions
    meta_cache: dict[tuple[str, str], AgentHarness] = {}

    def load_company_environment(root: Path, company: str) -> None:
        path = root / company / ".env"
        if path.is_file():
            os.environ.update(devenv.read_env_file(path))

    def find_agent(company: str, slug: str) -> AgentRef:
        for agent in discover_agents(company, companies_dir):
            if agent.slug == slug:
                return agent
        raise HTTPException(404, f"No agent {slug!r} in company {company!r}.")

    def get_session(session_id: str) -> Session:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Unknown session (the server restarted? reopen it from the saved list).")
        return session

    def meta_harness(agent: AgentRef) -> AgentHarness:
        key = (agent.company, agent.slug)
        if key not in meta_cache:
            meta_cache[key] = harness_factory(agent, llm_client=NoLLM())
        return meta_cache[key]

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/agents")
    def list_agents() -> list[dict[str, Any]]:
        """Every agent of every company."""
        return [
            {
                "company": a.company,
                "slug": a.slug,
                "label": a.label,
                "first_speaker": _default_first_speaker(a.slug),
            }
            for a in discover_agents(only_company, companies_dir)
        ]

    @app.get("/api/agents/{company}/{slug}/meta")
    def agent_meta(company: str, slug: str) -> dict[str, Any]:
        """Input variables, contact fields and slot names of an agent."""
        harness = meta_harness(find_agent(company, slug))
        variables = harness.discover_input_variables()
        env_file = companies_dir / company / ".env"
        env = devenv.read_env_file(env_file) if env_file.is_file() else {}
        return {
            "default_location_id": with_default_ids({}, {**os.environ, **env}).get("location_id", ""),
            "input_variables": variables,
            "contact_fields": harness.discover_contact_fields(),
            "slot_names": harness.discover_slot_names(),
            "first_speaker": _default_first_speaker(slug),
        }

    @app.post("/api/sessions")
    def new_session(body: NewSession) -> dict[str, Any]:
        """Creates a conversation; an agent that speaks first runs its first turn now."""
        agent = find_agent(body.company, body.slug)
        load_company_environment(companies_dir, agent.company)
        contact = with_default_ids(body.contact)
        harness = harness_factory(agent, contact=contact)
        session = Session(
            agent,
            harness,
            first_speaker=body.first_speaker,
            contact=contact,
            initial_slots=body.initial_slots,
        )
        sessions[session.id] = session
        session.save()
        return session.public()

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str) -> dict[str, Any]:
        """The whole session: settings, state and timeline."""
        return get_session(session_id).public()

    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, body: Message) -> dict[str, Any]:
        """Runs a turn with the contact's message."""
        session = get_session(session_id)
        if not body.text.strip():
            raise HTTPException(422, "Empty message.")
        with session.lock:
            session.say(body.text.strip())
        return session.public()

    @app.get("/api/sessions/{session_id}/live")
    def live_events(session_id: str) -> list[dict[str, Any]]:
        """What the running turn has done so far (LLM and tool calls, spoken messages)."""
        return [_json_safe(e) for e in list(get_session(session_id).harness.events)]

    @app.post("/api/sessions/{session_id}/start")
    def start_session(session_id: str) -> dict[str, Any]:
        """Runs the first turn of an agent that speaks first, if it did not run yet."""
        session = get_session(session_id)
        with session.lock:
            if not session.started:
                session.start()
        return session.public()

    @app.patch("/api/sessions/{session_id}/state")
    def edit_state(session_id: str, body: StateEdit) -> dict[str, Any]:
        """Edits flow variables and contact fields of the conversation."""
        session = get_session(session_id)
        with session.lock:
            try:
                session.edit(body.slots, body.contact)
            except RuntimeError as exc:
                raise HTTPException(409, str(exc)) from exc
        return session.public()

    @app.get("/api/sessions/{session_id}/export")
    def export_session(session_id: str) -> Response:
        """Downloads the session as JSON."""
        session = get_session(session_id)
        return Response(
            session.file().read_bytes() if session.file().is_file() else b"{}",
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{session.file().name}"'},
        )

    @app.get("/api/saved")
    def saved_sessions() -> list[dict[str, Any]]:
        """Conversations saved by earlier runs, newest first."""
        found = []
        for path in sorted(SAVE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            first = next((e.get("text") for e in data.get("timeline", []) if e.get("kind") == "user"), None)
            found.append(
                {
                    "file": path.name,
                    "company": data.get("company"),
                    "slug": data.get("slug"),
                    "thread_id": data.get("thread_id"),
                    "turns": data.get("turns", 0),
                    "saved_at": data.get("saved_at"),
                    "preview": (first or "")[:60],
                }
            )
        return found

    @app.post("/api/sessions/resume")
    def resume_session(body: Resume) -> dict[str, Any]:
        """Reopens a saved conversation; the graph continues from its checkpoint."""
        name = Path(body.file).name
        if not re.fullmatch(r"[\w.\-]+\.json", name):
            raise HTTPException(422, "Invalid file name.")
        path = SAVE_DIR / name
        if not path.is_file():
            raise HTTPException(404, "No such saved session.")
        data = json.loads(path.read_text(encoding="utf-8"))
        agent = find_agent(data["company"], data["slug"])
        load_company_environment(companies_dir, agent.company)
        harness = harness_factory(agent, contact=data.get("contact"))
        session = Session(
            agent,
            harness,
            thread_id=data["thread_id"],
            first_speaker=data.get("first_speaker", "user"),
            contact=data.get("contact"),
            initial_slots=data.get("initial_slots"),
        )
        session.timeline = data.get("timeline", [])
        session.started = bool(data.get("started"))
        session.ended = bool(data.get("ended"))
        session.turn_count = int(data.get("turns", 0))
        session.created_at = data.get("created_at", time.time())
        sessions[session.id] = session
        return session.public()

    @app.exception_handler(Exception)
    async def unexpected(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

    return app
