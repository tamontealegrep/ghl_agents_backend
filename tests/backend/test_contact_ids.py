"""contact_id comes from the caller; location_id falls back to GHL_LOCATION_ID of the company's .env."""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent_backend.app import create_app
from agent_backend.contact import with_default_ids
from agent_backend.loader import LoadedAgent
from agent_backend.settings import Settings
from agent_runtime.targets.langgraph.runtime_artifact import runtime_artifact_from_dict

BUNDLES = Path(__file__).resolve().parents[2] / "companies" / "babynova" / "bundles"
VOICE = BUNDLES / "babynova_surrogate_questions_voice"


def test_location_from_env_never_contact_id():
    """The location id comes from the environment; the contact id is never invented."""
    env = {"GHL_LOCATION_ID": "LOC1"}
    assert with_default_ids({"name": "Ana"}, env) == {"name": "Ana", "location_id": "LOC1"}
    assert with_default_ids(None, env) == {"location_id": "LOC1"}
    assert "contact_id" not in with_default_ids({}, env)


def test_caller_location_wins_blank_replaced():
    """A location given by the caller wins, and a blank one is replaced."""
    env = {"GHL_LOCATION_ID": "LOC1"}
    assert with_default_ids({"location_id": "MINE"}, env)["location_id"] == "MINE"
    assert with_default_ids({"location_id": "  "}, env)["location_id"] == "LOC1"
    assert with_default_ids({"contact_id": "c1"}, {}) == {"contact_id": "c1"}


def test_the_input_is_not_modified():
    """The contact passed in is not modified."""
    contact = {"name": "Ana"}
    with_default_ids(contact, {"GHL_LOCATION_ID": "LOC1"})
    assert contact == {"name": "Ana"}


class _Graph:
    def __init__(self):
        self.started_with = None

    def get_state(self, config):
        return SimpleNamespace(values={}, next=(), interrupts=())

    def invoke(self, state, config):
        self.started_with = state
        return {}


def _chat(monkeypatch, contact, env_location):
    if env_location:
        monkeypatch.setenv("GHL_LOCATION_ID", env_location)
    else:
        monkeypatch.delenv("GHL_LOCATION_ID", raising=False)
    artifact = runtime_artifact_from_dict(json.loads((VOICE / "graph.json").read_text(encoding="utf-8")))
    graph = _Graph()
    app = create_app(Settings(host="127.0.0.1", port=1, agents_dir=BUNDLES, admin_token=None))
    app.state.registry = SimpleNamespace(get=lambda slug: LoadedAgent(artifact=artifact, graph=graph))
    response = TestClient(app).post(
        "/agents/babynova_surrogate_questions_voice/chat", json={"thread_id": "t", "contact": contact}
    )
    assert response.status_code == 200
    return graph.started_with["contact"]


def test_manual_chat_gets_company_location(monkeypatch):
    """A chat started by hand gets the company's location id."""
    contact = _chat(monkeypatch, {"contact_id": "c9", "name": "Ana"}, "LOC1")
    assert contact == {"contact_id": "c9", "name": "Ana", "location_id": "LOC1"}


def test_chat_without_location_leaves_it_out(monkeypatch):
    """Without a configured location the contact has no location id."""
    assert _chat(monkeypatch, {"contact_id": "c9"}, None) == {"contact_id": "c9"}
