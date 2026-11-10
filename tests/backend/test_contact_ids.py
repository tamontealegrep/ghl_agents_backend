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


def test_the_location_is_filled_from_the_environment_but_the_contact_id_never_is():
    env = {"GHL_LOCATION_ID": "LOC1"}
    assert with_default_ids({"name": "Ana"}, env) == {"name": "Ana", "location_id": "LOC1"}
    assert with_default_ids(None, env) == {"location_id": "LOC1"}
    assert "contact_id" not in with_default_ids({}, env)


def test_a_location_given_by_the_caller_wins_and_an_empty_one_is_replaced():
    env = {"GHL_LOCATION_ID": "LOC1"}
    assert with_default_ids({"location_id": "MINE"}, env)["location_id"] == "MINE"
    assert with_default_ids({"location_id": "  "}, env)["location_id"] == "LOC1"
    assert with_default_ids({"contact_id": "c1"}, {}) == {"contact_id": "c1"}


def test_the_input_is_not_modified():
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


def test_a_chat_started_by_hand_gets_the_location_of_the_company(monkeypatch):
    contact = _chat(monkeypatch, {"contact_id": "c9", "name": "Ana"}, "LOC1")
    assert contact == {"contact_id": "c9", "name": "Ana", "location_id": "LOC1"}


def test_a_chat_without_a_configured_location_leaves_it_out(monkeypatch):
    assert _chat(monkeypatch, {"contact_id": "c9"}, None) == {"contact_id": "c9"}
