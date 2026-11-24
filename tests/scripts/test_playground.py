"""scripts/playground: the browser playground's server, on a throw-away copy of a real bundle."""

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from chat_tui.harness import AgentHarness
from playground import server

COMPANIES = Path(__file__).resolve().parents[2] / "companies"
SLUG = "family_aims_sam_text"


class FakeLLM:
    def complete(self, prompt, *, temperature=0.0):
        return "NONE"

    def extract_structured(self, prompt, json_schema):
        return {}


class BrokenLLM(FakeLLM):
    def extract_structured(self, prompt, json_schema):
        raise RuntimeError("boom")

    def complete(self, prompt, *, temperature=0.0):
        raise RuntimeError("boom")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DEFINITIONS_DIR", str(tmp_path / "no-definitions"))
    monkeypatch.setattr(server, "SAVE_DIR", tmp_path / "saved")
    monkeypatch.delenv(
        "GHL_LOCATION_ID", raising=False
    )  # other tests load company .env files into os.environ
    shutil.copytree(COMPANIES / "family_aims" / "bundles", tmp_path / "family_aims" / "bundles")
    llm = {"client": FakeLLM()}

    def factory(agent, contact=None, llm_client=None):
        return AgentHarness(agent, contact=contact, llm_client=llm_client or llm["client"])

    test_client = TestClient(server.create_app(factory, companies_dir=tmp_path))
    test_client.llm = llm
    return test_client


def _new(client, **extra):
    body = {"company": "family_aims", "slug": SLUG, "first_speaker": "user", **extra}
    return client.post("/api/sessions", json=body).json()


def test_page_and_agents_served(client):
    """The page and the agent list are served."""
    page = client.get("/")
    assert page.status_code == 200 and "Agent playground" in page.text
    agents = client.get("/api/agents").json()
    assert {
        "company": "family_aims",
        "slug": SLUG,
        "label": f"{SLUG}  (family_aims)",
        "first_speaker": "user",
    } in agents
    voice = next(a for a in agents if a["slug"].endswith("_es_voice"))
    assert voice["first_speaker"] == "agent"


def test_meta_lists_fields_and_slots(client):
    """Meta lists the contact fields and slot names."""
    meta = client.get(f"/api/agents/family_aims/{SLUG}/meta").json()
    assert {"name", "email", "language"} <= set(meta["contact_fields"])
    assert len(meta["slot_names"]) > 20


def test_new_conversation_not_started(client):
    """A new conversation has not started yet."""
    session = _new(client)
    assert (session["started"], session["timeline"], session["state"]["slots"]) == (False, [], {})


def test_turn_records_events(client):
    """A turn records the message, the LLM calls and the state."""
    session = _new(client, contact={"name": "Ana"})

    done = client.post(f"/api/sessions/{session['id']}/messages", json={"text": "hola"}).json()

    kinds = [e["kind"] for e in done["timeline"]]
    assert kinds[0] == "user" and "say" in kinds and kinds[-1] == "state"
    llm_calls = [e for e in done["timeline"] if e["kind"] == "llm"]
    assert llm_calls and all(e["prompt"] and "ms" in e for e in llm_calls)
    assert done["started"] and done["state"]["contact"]["name"] == "Ana"
    assert done["state"]["current_state"] == done["timeline"][-1]["current_state"]


def test_tool_calls_are_events(client):
    """Tool calls are events with request, response and routes tried."""
    session = _new(client)
    harness = server_session(client, session).harness

    harness.tracing_http_client.post(f"{harness.tools_base_url}/check_visa", json={"nationalities": "USA"})

    tool = next(e for e in harness.events if e["kind"] == "tool")
    assert (tool["name"], tool["status"], tool["request"]) == ("check-visa", 200, {"nationalities": "USA"})
    assert (
        tool["response"]["success"] is True and len(tool["attempts"]) >= 2
    )  # check-visa-ghl answered 404 first


def server_session(client, session):
    return client.app.state.sessions[session["id"]]


def test_variables_editable_any_time(client):
    """Flow variables can be edited before and after the conversation starts."""
    session = _new(client)
    before = client.patch(
        f"/api/sessions/{session['id']}/state", json={"slots": {"mi_slot": "x"}, "contact": {"name": "Luis"}}
    ).json()
    assert before["initial_slots"] == {"mi_slot": "x"} and before["contact"] == {"name": "Luis"}

    client.post(f"/api/sessions/{session['id']}/messages", json={"text": "hola"})
    live = client.patch(f"/api/sessions/{session['id']}/state", json={"slots": {"otro": 5}}).json()
    assert live["state"]["slots"]["mi_slot"] == "x" and live["state"]["slots"]["otro"] == 5

    removed = client.patch(f"/api/sessions/{session['id']}/state", json={"slots": {"otro": None}}).json()
    assert "otro" not in removed["state"]["slots"]
    assert [e["kind"] for e in removed["timeline"]].count(
        "edit"
    ) == 3  # before the start, after it, and the removal


def test_failing_turn_shown_in_chat(client):
    """A failing turn is shown in the conversation, not as an HTTP error."""
    client.llm["client"] = BrokenLLM()
    session = _new(client)

    done = client.post(f"/api/sessions/{session['id']}/messages", json={"text": "hola"})

    assert done.status_code == 200
    errors = [e for e in done.json()["timeline"] if e["kind"] == "error"]
    assert errors and "boom" in errors[0]["text"]
    assert any(e["kind"] == "llm" and "boom" in e.get("error", "") for e in done.json()["timeline"])


def test_saved_sessions_resume(client):
    """Saved conversations are listed and reopened where they stopped."""
    session = _new(client)
    client.post(f"/api/sessions/{session['id']}/messages", json={"text": "hola"})

    saved = client.get("/api/saved").json()
    assert saved[0]["slug"] == SLUG and saved[0]["turns"] == 1 and saved[0]["preview"] == "hola"

    reopened = client.post("/api/sessions/resume", json={"file": saved[0]["file"]}).json()
    assert reopened["thread_id"] == session["thread_id"] and reopened["id"] != session["id"]
    assert [e["kind"] for e in reopened["timeline"]][0] == "user"
    assert reopened["state"]["current_state"]  # read back from the checkpoint

    again = client.post(f"/api/sessions/{reopened['id']}/messages", json={"text": "quiero agendar"}).json()
    assert again["turns"] == 2


def test_resume_refuses_bad_sessions(client):
    """Resume refuses file paths and unknown sessions."""
    assert client.post("/api/sessions/resume", json={"file": "../x.json"}).status_code in (404, 422)
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/messages", json={"text": "x"}).status_code == 404


def test_live_events_and_export(client):
    """Live events and the export are available."""
    session = _new(client)
    assert client.get(f"/api/sessions/{session['id']}/live").json() == []
    client.post(f"/api/sessions/{session['id']}/messages", json={"text": "hola"})
    export = client.get(f"/api/sessions/{session['id']}/export")
    assert export.status_code == 200 and export.json()["thread_id"] == session["thread_id"]
    assert client.post(f"/api/sessions/{session['id']}/messages", json={"text": "  "}).status_code == 422


def test_location_default_contact_manual(client, monkeypatch, tmp_path):
    """The location id defaults to the company env; the contact id is left to the user."""
    monkeypatch.setenv("GHL_LOCATION_ID", "LOC-FROM-ENV")
    meta = client.get(f"/api/agents/family_aims/{SLUG}/meta").json()
    assert meta["default_location_id"] == "LOC-FROM-ENV"

    session = _new(client, contact={"contact_id": "c-123"})

    assert session["contact"] == {"contact_id": "c-123", "location_id": "LOC-FROM-ENV"}
