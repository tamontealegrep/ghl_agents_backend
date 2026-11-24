"""The GHL webhook buffers a contact's messages: a burst becomes one turn, in order, and nothing is lost."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.types import Command

from agent_backend.channels.ghl import endpoint as endpoint_module
from agent_backend.channels.ghl.client import GhlClientConfig
from agent_backend.channels.ghl.config import CompiledAgentGhlConfig
from agent_backend.loader import LoadedAgent
from agent_runtime.targets.langgraph.runtime_artifact import runtime_artifact_from_dict

BUNDLE = (
    Path(__file__).resolve().parents[2] / "companies" / "family_aims" / "bundles" / "family_aims_sam_text"
)
DEBOUNCE = 0.4


class FakeGraph:
    """Records what each turn receives; the first turn starts the conversation, later ones resume it."""

    def __init__(self, turn_seconds: float = 0.0) -> None:
        self.turns: list[str] = []
        self.values: dict = {}
        self.turn_seconds = turn_seconds
        self.running = 0
        self.max_running = 0

    def get_state(self, config):
        return SimpleNamespace(values=self.values, next=("node",) if self.values else (), interrupts=())

    def invoke(self, state, config):
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            text = state.resume if isinstance(state, Command) else state["last_user_message"]
            self.turns.append(text)
            time.sleep(self.turn_seconds)
            self.values = {
                "current_state": "Q__ASK",
                "last_message_at": datetime.now(UTC).isoformat(),
                "contact": {},
                "slots": {},
            }
            return {"__interrupt__": [SimpleNamespace(value={"prompt": [f"answer {len(self.turns)}"]})]}
        finally:
            self.running -= 1


@pytest.fixture
def webhook(monkeypatch):
    graph = FakeGraph()
    sent: list[str] = []

    async def fake_send(**kwargs):
        sent.append(kwargs["message"])

    async def fake_channel(*args, **kwargs):
        return "WHATSAPP"

    monkeypatch.setattr(endpoint_module, "send_ghl_message_async", fake_send)
    monkeypatch.setattr(endpoint_module, "resolve_reply_channel", fake_channel)
    monkeypatch.setattr(endpoint_module, "upsert_conversation", lambda **kwargs: None)
    monkeypatch.setattr(endpoint_module, "postgres_enabled", lambda: False)

    artifact = runtime_artifact_from_dict(json.loads((BUNDLE / "graph.json").read_text(encoding="utf-8")))

    class Registry:
        def get(self, slug):
            return LoadedAgent(artifact=artifact, graph=graph)

    cfg = CompiledAgentGhlConfig(
        slug="agent",
        path="/hook",
        allowed_phones=frozenset(),
        debounce_seconds=DEBOUNCE,
        ghl_client_config=lambda: GhlClientConfig(
            base_url="http://ghl.invalid",
            version="1",
            token="t",
            message_history_page_size=20,
            conversation_search_limit=5,
            history_timeout_seconds=5,
            conversation_search_timeout_seconds=5,
            send_message_timeout_seconds=5,
            default_send_type="Live_Chat",
            channel_type_map={"WHATSAPP": "WhatsApp"},
        ),
        enforce_phone_whitelist=False,
    )
    app = FastAPI()
    app.include_router(endpoint_module.build_compiled_agent_router(cfg, Registry()))
    with TestClient(app) as client:
        client.graph, client.sent = graph, sent
        yield client


def post(client, text, message_id=None, **extra):
    body = {"contactId": "c1", "locationId": "loc", "message": text, **extra}
    if message_id:
        body["messageId"] = message_id
    return client.post("/hook", json=body).json()


def wait_for(condition, seconds=6.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        time.sleep(0.05)
    return condition()


def test_burst_becomes_one_ordered_turn(webhook):
    """A burst of messages becomes a single turn, in order."""
    for i, text in enumerate(["hola", "quiero", "agendar una cita"]):
        assert post(webhook, text, f"m{i}")["status"] == "accepted"
        time.sleep(0.1)

    assert wait_for(lambda: webhook.sent)
    time.sleep(DEBOUNCE + 0.3)  # nothing else must follow

    assert webhook.graph.turns == ["hola\nquiero\nagendar una cita"]
    assert webhook.sent == ["answer 1"]


def test_each_new_message_restarts_the_wait(webhook):
    """Each new message restarts the debounce wait."""
    post(webhook, "uno", "m1")
    time.sleep(DEBOUNCE * 0.7)
    post(webhook, "dos", "m2")  # still inside the first window: the timer starts over
    time.sleep(DEBOUNCE * 0.7)
    assert webhook.graph.turns == []  # 1.4 x debounce since the first message, but only 0.7 x since the last

    assert wait_for(lambda: webhook.graph.turns)
    assert webhook.graph.turns == ["uno\ndos"]


def test_messages_apart_are_separate_turns(webhook):
    """Messages sent far apart are separate turns."""
    post(webhook, "primero", "m1")
    assert wait_for(lambda: len(webhook.sent) == 1)

    post(webhook, "segundo", "m2")
    assert wait_for(lambda: len(webhook.sent) == 2)

    assert webhook.graph.turns == ["primero", "segundo"]


def test_messages_during_answer_merge(webhook):
    """Messages that arrive while the agent answers are merged into the next turn."""
    webhook.graph.turn_seconds = 1.0
    post(webhook, "primero", "m1")
    assert wait_for(lambda: webhook.graph.running == 1)  # the first turn is running now

    post(webhook, "segundo", "m2")
    time.sleep(0.2)
    post(webhook, "tercero", "m3")

    assert wait_for(lambda: len(webhook.sent) == 2, seconds=10)
    assert webhook.graph.turns == ["primero", "segundo\ntercero"]
    assert webhook.graph.max_running == 1  # turns of one conversation never overlap


def test_two_contacts_do_not_share_a_buffer(webhook):
    """Two contacts never share a message buffer."""
    post(webhook, "soy uno", "a1", contactId="c1")
    post(webhook, "soy dos", "b1", contactId="c2")

    assert wait_for(lambda: len(webhook.sent) == 2)
    assert sorted(webhook.graph.turns) == ["soy dos", "soy uno"]


def test_duplicate_delivery_is_ignored(webhook):
    """A repeated delivery of the same message id is not counted twice."""
    assert post(webhook, "hola", "m1")["status"] == "accepted"
    assert post(webhook, "hola", "m1")["status"] == "duplicate"

    assert wait_for(lambda: webhook.graph.turns)
    assert webhook.graph.turns == ["hola"]


def test_different_messages_without_a_message_id_are_all_kept(webhook):
    """GHL payloads that carry the conversation id but no message id must not collapse into one message."""
    first = post(webhook, "hola", None, conversationId="conv1")
    second = post(webhook, "quiero agendar", None, conversationId="conv1")

    assert (first["status"], second["status"]) == ("accepted", "accepted")
    assert wait_for(lambda: webhook.graph.turns)
    assert webhook.graph.turns == ["hola\nquiero agendar"]


def test_request_without_ids_is_ignored(webhook):
    """A request without message and location ids is ignored."""
    assert webhook.post("/hook", json={"contactId": "c1", "message": "hola"}).json() == {
        "status": "ignored",
        "reason": "missing_ids",
    }
    time.sleep(DEBOUNCE + 0.2)
    assert webhook.graph.turns == []


def test_french_is_supported():
    """French is a supported language of the GHL text channel."""
    from agent_backend.channels.ghl.config import CompiledAgentGhlConfig, _closing_message_text
    from agent_runtime import languages
    from agent_backend.channels.ghl.text import normalize_language

    assert [normalize_language(v) for v in ("fr", "FR-fr", "French", "Français", "tlh")] == [
        "fr",
        "fr",
        "fr",
        "fr",
        "en",
    ]
    cfg = CompiledAgentGhlConfig(
        slug="a",
        path="/a",
        allowed_phones=frozenset(),
        debounce_seconds=1,
        ghl_client_config=lambda: None,
        enforce_phone_whitelist=False,
    )
    french_closing = languages.get("fr").messages["closing"]
    assert _closing_message_text(cfg, "French") == french_closing
    assert _closing_message_text(cfg, "fr") == french_closing
