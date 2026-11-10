"""scripts/agent_chat_tui.py: everything that does not need a terminal."""

import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import agent_chat_tui as tui
from chat_tui import session as session_module

COMPANIES = Path(__file__).resolve().parents[2] / "companies"


class FakeLLM:
    def complete(self, prompt, *, temperature=0.0):
        return "NONE"

    def extract_structured(self, prompt, json_schema):
        return {}


@pytest.fixture
def family_aims(tmp_path, monkeypatch):
    """A throw-away copy of Family Aims' bundles, so sessions.db never lands in the real folders."""
    monkeypatch.setenv("AGENT_DEFINITIONS_DIR", str(tmp_path / "no-definitions"))
    shutil.copytree(COMPANIES / "family_aims" / "bundles", tmp_path / "family_aims" / "bundles")
    agents = tui.discover_agents("family_aims", tmp_path)
    return {a.slug: a for a in agents}


def test_agents_are_discovered_per_company_skipping_tool_folders():
    everything = tui.discover_agents()
    slugs = {(a.company, a.slug) for a in everything}
    assert ("family_aims", "family_aims_sam_text") in slugs and (
        "babynova",
        "babynova_triage_obstetrico_text",
    ) in slugs
    assert not any(a.slug.startswith("_") for a in everything)
    assert {a.company for a in tui.discover_agents("babynova")} == {"babynova"}
    assert tui.discover_agents("nope") == []


def test_the_selector_label_names_agent_and_company():
    assert tui.discover_agents("babynova")[0].label.endswith("(babynova)")


def test_session_round_trip_keeps_everything(tmp_path, family_aims):
    state = tui._new_state(family_aims["family_aims_sam_text"])
    state.history.append(tui._history_entry("inbound", "hola"))
    state.first_speaker, state.log_llm, state.log_http, state.log_tools = "user", True, True, True
    state.initial_slots, state.contact = {"a": 1}, {"name": "Ana"}
    file = tmp_path / "s.json"
    tui.save_session(state, file)

    loaded = tui.load_session(file, list(family_aims.values()))

    assert (loaded.thread_id, loaded.first_speaker, loaded.initial_slots, loaded.contact) == (
        state.thread_id,
        "user",
        {"a": 1},
        {"name": "Ana"},
    )
    assert loaded.agent is family_aims["family_aims_sam_text"] and loaded.history[0]["body"] == "hola"
    assert (loaded.log_llm, loaded.log_http, loaded.log_tools) == (True, True, True)


def test_a_session_of_a_missing_agent_is_reported(tmp_path, family_aims):
    state = tui._new_state(family_aims["family_aims_sam_text"])
    tui.save_session(state, tmp_path / "s.json")
    with pytest.raises(KeyError):
        tui.load_session(tmp_path / "s.json", [])


def test_session_files_default_to_a_timestamped_log(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "DEFAULT_SESSION_DIR", tmp_path / "logs")
    path = tui.resolve_session_file("agent_x", None)
    assert path.parent == tmp_path / "logs" and path.name.startswith("agent_x_session_")
    assert tui.resolve_session_file("agent_x", str(tmp_path / "mine.json")) == tmp_path / "mine.json"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", None), ("  ", None), ("true", True), ("12", 12), ('{"a": 1}', {"a": 1}), ("hola", "hola")],
)
def test_slot_values_are_json_when_possible(raw, expected):
    assert tui._parse_slot_input(raw) == expected


def test_the_harness_discovers_slots_and_contact_fields_from_the_graph(family_aims):
    harness = tui.AgentHarness(family_aims["family_aims_sam_text"], llm_client=FakeLLM())
    assert len(harness.discover_slot_names()) > 20
    assert {"name", "email", "phone", "language"} <= set(harness.discover_contact_fields())
    assert harness.discover_input_variables() == []  # no definitions folder


def test_a_turn_runs_the_real_graph_and_leaves_a_checkpoint(family_aims):
    harness = tui.AgentHarness(
        family_aims["family_aims_sam_text"], contact={"name": "Ana", "language": "es"}, llm_client=FakeLLM()
    )
    assert harness.state_snapshot("t1") == {}

    first = harness.start("t1", "user", "hola")

    assert first.current_state and first.messages and first.conversation_ended is False
    snapshot = harness.state_snapshot("t1")
    assert snapshot["current_state"] == first.current_state and snapshot["contact"]["name"] == "Ana"
    assert (family_aims["family_aims_sam_text"].root / "sessions.db").exists()

    second = harness.turn("t1", "quiero agendar")
    assert second.current_state
    with pytest.raises(RuntimeError, match="se necesita un mensaje"):
        harness.turn("t1", None)


def test_initial_slots_are_preset_before_the_graph_runs(family_aims):
    harness = tui.AgentHarness(family_aims["family_aims_sam_text"], llm_client=FakeLLM())
    harness.start("t2", "user", "hola", initial_slots={"mi_slot_de_prueba": "x"})
    assert harness.state_snapshot("t2")["slots"]["mi_slot_de_prueba"] == "x"


def test_tool_calls_are_recorded_and_fall_back_across_routes(family_aims):
    harness = tui.AgentHarness(family_aims["family_aims_sam_text"], llm_client=FakeLLM())

    response = harness.tracing_http_client.post(
        f"{harness.tools_base_url}/check_visa", json={"nationalities": "USA"}
    )

    assert response.status_code == 200  # check-visa-ghl answered 404, check-visa answered
    trace = harness._trace_buffer[-1]
    assert (trace.tool_name, trace.status_code, trace.args) == ("check-visa", 200, {"nationalities": "USA"})
    assert trace.response_body["success"] is True


def test_http_logging_prints_request_and_response_only_when_enabled(family_aims):
    harness = tui.AgentHarness(family_aims["family_aims_sam_text"], llm_client=FakeLLM())
    url = f"{harness.tools_base_url}/check_visa"
    with tui.console.capture() as quiet:
        harness.tracing_http_client.post(url, json={"nationalities": "USA"})
    harness.tracing_http_client.enabled = True
    with tui.console.capture() as loud:
        harness.tracing_http_client.post(url, json={"nationalities": "USA"})
    assert quiet.get() == ""
    assert (
        "HTTP Request Body" in loud.get()
        and "HTTP Response Body" in loud.get()
        and "nationalities" in loud.get()
    )


def test_llm_logging_prints_prompts_only_when_enabled():
    llm = tui.TracingLLMClient(FakeLLM())
    with tui.console.capture() as quiet:
        assert llm.complete("hola") == "NONE"
    llm.enabled = True
    with tui.console.capture() as loud:
        llm.complete("hola")
        llm.extract_structured("extrae", {"type": "object"})
    assert quiet.get() == "" and "LLM Prompt (complete)" in loud.get() and "LLM Response (JSON)" in loud.get()


def test_commands_toggle_logs_and_clear_things(tmp_path, family_aims):
    ref = family_aims["family_aims_sam_text"]
    harness = tui.AgentHarness(ref, llm_client=FakeLLM())
    state = tui._new_state(ref)
    state.initial_slots, state.contact = {"a": 1}, {"name": "Ana"}
    file = tmp_path / "s.json"

    with tui.console.capture():
        assert tui.handle_chat_command("/log-tools", state, file, harness) and state.log_tools is True
        assert (
            tui.handle_chat_command("/log-llm", state, file, harness)
            and harness.tracing_llm_client.enabled is True
        )
        assert (
            tui.handle_chat_command("/log-http", state, file, harness)
            and harness.tracing_http_client.enabled is True
        )
        assert tui.handle_chat_command("/slots-clear", state, file, harness) and state.initial_slots == {}
        assert tui.handle_chat_command("/contact-clear", state, file, harness) and state.contact == {}
        assert tui.handle_chat_command("/save", state, file, harness) and file.exists()
        assert tui.handle_chat_command("/HELP", state, file, harness)
        assert tui.handle_chat_command("/traces", state, file, harness) and tui.handle_chat_command(
            "/history", state, file, harness
        )
        assert tui.handle_chat_command("/state", state, file, harness) and tui.handle_chat_command(
            "/slots", state, file, harness
        )
        assert tui.handle_chat_command("/input", state, file, harness) and tui.handle_chat_command(
            "/contact", state, file, harness
        )
        assert tui.handle_chat_command("/no-existe", state, file, harness) is False
        with pytest.raises(tui.ReturnToLauncher):
            tui.handle_chat_command("/back", state, file, harness)
        with pytest.raises(tui.ExitLauncher):
            tui.handle_chat_command("/exit", state, file, harness)


def test_traces_and_history_are_rendered():
    state = tui.SessionState(agent=tui.AgentRef("c", "slug_x", Path(".")), thread_id="t")
    state.history = [tui._history_entry("inbound", "hola"), tui._history_entry("outbound", "buenas")]
    with tui.console.capture() as out:
        tui.render_history(state)
        tui.render_traces([tui.ToolTrace("book-appointment-ghl", {"a": 1}, 200, {"success": True})])
        tui.render_traces([])
    text = out.get()
    assert (
        "User" in text
        and "slug_x" in text
        and "Tool 1: book-appointment-ghl" in text
        and "Sin tool calls" in text
    )


def test_contact_flags_build_the_simulated_contact():
    args = tui.parse_args(["--contact-name", "Ana", "--contact-language", "es"])
    assert tui._contact_from_args(args) == {"name": "Ana", "language": "es"}
    assert tui._contact_from_args(tui.parse_args([])) == {}
