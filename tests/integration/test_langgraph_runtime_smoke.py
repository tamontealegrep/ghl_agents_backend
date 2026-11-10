"""
End-to-end smoke test: a synthetic AgentSpec compiled and run through a

    REAL langgraph.graph.StateGraph (agent_runtime.runtime.graph_builder),
    with every LLM call faked (no API key, no network for the model) and the
    tool executor hitting a stubbed HTTP endpoint (httpx.MockTransport, no
    real network either).

    Exercises, per the approved plan's Verification section:
      - the session resolver's new/continuing resolution against a real
        graph.get_state(config) snapshot;
      - the global router's resume-in-place path (dynamic GO_TO target ->
        the question re-asks) and its Command(goto=...) jump path (static
        target -> the conversation jumps straight to another state);
      - the generic tool executor calling a stub HTTP endpoint from inside a
        real `action` node.

    `_build_artifact` also proves the file-replaceable-artifact story end to
    end: it serializes the compiled `RuntimeArtifact` to a JSON string and
    reloads it via `runtime_artifact_from_dict` before `build_graph` ever
    sees it — exactly what a backend loading `agent.json` off disk would do.
    `build_graph`/`fresh_state` never touch the original `AgentSpec`.

    No real agent/business content — a fully synthetic three-state flow with
    one handler and one tool.
"""

from __future__ import annotations

import json

import httpx
from langgraph.types import Command

from agent_runtime.dsl.schemas import ToolContract
from agent_runtime.runtime.graph_builder import build_graph, fresh_state
from agent_runtime.runtime.session_resolver import resolve_session
from agent_runtime.targets.langgraph.runtime_artifact import (
    RuntimeArtifact,
    render_runtime_artifact,
    runtime_artifact_from_dict,
)
from tests.contract.conftest import (
    build_message_state,
    build_minimal_agent_spec,
    build_terminal_state,
)


def _build_artifact(spec) -> RuntimeArtifact:
    """
    Compile `spec`, round-trip it through JSON, and return the reloaded artifact.

        Parameters:
            spec: Description.

        Returns:
            The result.
    """
    artifact = render_runtime_artifact(spec)
    json_text = json.dumps(artifact.to_dict())
    return runtime_artifact_from_dict(json.loads(json_text))


class _FakeLLMClient:
    """
    Canned responses queued in the order the test expects them to be consumed.

        The two-stage global router (2026-09-17) makes up to two `complete()`
            calls per check: Stage 1 (`router_stage1_replies`, CONTINUE/INTERRUPT)
            always runs; Stage 2 (`router_replies`, candidate index/NONE) only runs
            when Stage 1 says INTERRUPT.
    """

    def __init__(self):
        self.router_stage1_replies: list[str] = []
        self.router_replies: list[str] = []
        self.captures: list[dict] = []

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        if "Global interrupts:" in prompt:
            return self.router_stage1_replies.pop(0)
        if "mid-question" in prompt:
            return self.router_replies.pop(0)
        if "genuine question or request for specific" in prompt:
            return "NO"
        if "Rephrase this agent message" in prompt:
            # SAY rendering (say_verbatim=false) now always paraphrases via the
            # LLM — echo the raw text back unchanged so this scenario's own
            # assertions about exact SAY content stay meaningful.
            return prompt.rsplit("\n\n", 1)[-1]
        raise AssertionError(f"Unexpected complete() call in this scenario: {prompt[:100]}")

    def extract_structured(self, prompt: str, json_schema: dict) -> dict:
        return self.captures.pop(0)


def _stub_tools_client(response_json: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _build_spec():
    greeting = build_message_state("GREETING", say=["Hello!"], route=["GO_TO: ASK_NAME"])
    ask_name = build_message_state(
        "ASK_NAME",
        type="question",
        wait="yes",
        say=["What is your name?"],
        capture=[{"slot": "name", "type_expr": "str"}],
        route=["GO_TO: BOOK"],
    )
    book = build_message_state(
        "BOOK",
        type="action",
        say=[],
        execute="book_appointment",
        capture=[{"slot": "event_id", "type_expr": "str"}],
        store=["[booked_id] = [event_id]"],
        route=["GO_TO: CLOSE"],
    )
    close = build_terminal_state("CLOSE", say=["Goodbye."])

    handler = {
        "handler_id": "H_REPEAT",
        "type": "message",
        "wait": "no",
        "say": ["Sure, let me repeat that."],
        "trigger": ["repeat that"],
        "route": ["GO_TO: [current_state]"],
    }
    handoff_handler = {
        "handler_id": "H_HUMAN",
        "type": "message",
        "wait": "no",
        "say": ["Transferring you to a human."],
        "trigger": ["talk to a human"],
        "route": ["GO_TO: CLOSE"],
    }

    from agent_runtime.dsl.schemas import HandlerModel, MemorySlot

    contract = ToolContract.model_validate(
        {
            "name": "book_appointment",
            "description": "Books an appointment.",
            "inputs": [],
            "outputs": [{"name": "event_id", "description": "The created event id."}],
        }
    )

    return build_minimal_agent_spec(
        states=[greeting, ask_name, book],
        terminal_states=[close],
        handlers=[HandlerModel.model_validate(handler), HandlerModel.model_validate(handoff_handler)],
        tools=["book_appointment"],
        tool_contracts=[contract],
        memory_slots=[
            MemorySlot(name="current_state", description="d", kind="dynamic_state"),
            MemorySlot(name="resume_state", description="d", kind="dynamic_state"),
            MemorySlot(name="name", description="d", kind="captured"),
            MemorySlot(name="event_id", description="d", kind="tool_output"),
            MemorySlot(name="booked_id", description="d", kind="captured"),
        ],
    )


def test_build_graph_defaults_to_an_in_memory_checkpointer():
    from langgraph.checkpoint.memory import InMemorySaver

    spec = _build_spec()
    artifact = _build_artifact(spec)
    graph = build_graph(artifact, _FakeLLMClient())
    assert isinstance(graph.checkpointer, InMemorySaver)


def test_build_graph_accepts_an_injected_checkpointer():
    from langgraph.checkpoint.memory import InMemorySaver

    spec = _build_spec()
    artifact = _build_artifact(spec)
    custom_checkpointer = InMemorySaver()
    graph = build_graph(artifact, _FakeLLMClient(), checkpointer=custom_checkpointer)
    assert graph.checkpointer is custom_checkpointer


def test_full_conversation_with_repeat_handler_then_capture_then_tool_call_then_close():
    spec = _build_spec()
    artifact = _build_artifact(spec)  # JSON round-trip — see module docstring
    llm_client = _FakeLLMClient()
    said: list[str] = []
    graph = build_graph(
        artifact,
        llm_client,
        tools_base_url="https://tools.example.com",
        tool_http_client=_stub_tools_client({"event_id": "evt_1"}),
        say_callback=said.append,
    )
    config = {"configurable": {"thread_id": "smoke-thread"}}

    # Session resolver: no checkpoint yet for this thread_id -> "new".
    snapshot = graph.get_state(config)
    assert resolve_session(snapshot.values, timeout_minutes=None) == "new"

    result = graph.invoke(fresh_state(artifact), config)
    assert said == ["Hello!"]
    assert result["__interrupt__"][0].value["prompt"] == ["What is your name?"]

    # Session resolver: a checkpoint now exists -> "continuing".
    snapshot = graph.get_state(config)
    assert resolve_session(snapshot.values, timeout_minutes=None) == "continuing"

    # Global router: "repeat that" matches H_REPEAT (index 0), whose route
    # targets the dynamic [current_state] -> resume in place (re-ask).
    # Stage 1 says INTERRUPT, so Stage 2 runs and picks candidate 0.
    llm_client.router_stage1_replies.append("INTERRUPT")
    llm_client.router_replies.append("0")
    result = graph.invoke(Command(resume="repeat that"), config)
    assert said[-1] == "Sure, let me repeat that."
    assert result["__interrupt__"][0].value["prompt"] == ["What is your name?"]

    # Global router: the real answer doesn't match anything -> captured as
    # the answer to the pending question, extraction populates `name`.
    #
    # Two full router checks happen here, not one: LangGraph replays the
    # node function from the top on every resume, so the FIRST interrupt()
    # call (already resumed once, with "repeat that") replays and re-issues
    # its global-router check before reaching the second, still-pending
    # interrupt() call that actually receives this new "Alex" resume. This
    # is the documented trade-off in DESIGN_PATTERNS.md P04 — extra calls,
    # not an incorrect final state. The replayed "repeat that" check needs
    # both stages again (INTERRUPT -> "0"); "Alex" is a normal continuation,
    # so its check is Stage 1 only (CONTINUE, no Stage 2 call at all).
    llm_client.router_stage1_replies.append("INTERRUPT")  # replay of "repeat that", stage 1
    llm_client.router_replies.append("0")  # replay of "repeat that", stage 2
    llm_client.router_stage1_replies.append("CONTINUE")  # the new "Alex" reply, stage 1 only
    llm_client.captures.append({"name": "Alex"})
    result = graph.invoke(Command(resume="Alex"), config)

    # BOOK ran the tool executor against the stub endpoint and captured
    # its output; CLOSE said goodbye; the graph reached END (no interrupt).
    assert "__interrupt__" not in result or not result["__interrupt__"]
    assert said[-1] == "Goodbye."

    final_slots = graph.get_state(config).values["slots"]
    assert final_slots["name"] == "Alex"
    assert final_slots["event_id"] == "evt_1"
    assert final_slots["booked_id"] == "evt_1"  # action node's `store` runs after the tool call


def test_global_router_command_goto_jumps_straight_to_the_handoff_target():
    spec = _build_spec()
    artifact = _build_artifact(spec)
    llm_client = _FakeLLMClient()
    said: list[str] = []
    graph = build_graph(
        artifact,
        llm_client,
        tools_base_url="https://tools.example.com",
        tool_http_client=_stub_tools_client({"event_id": "evt_1"}),
        say_callback=said.append,
    )
    config = {"configurable": {"thread_id": "smoke-thread-handoff"}}

    graph.invoke(fresh_state(artifact), config)

    # "talk to a human" matches H_HUMAN (index 1: handler H_REPEAT is 0,
    # H_HUMAN is 1), whose route is a static GO_TO: CLOSE -> Command(goto=...)
    # jumps straight there instead of resuming the pending question.
    llm_client.router_stage1_replies.append("INTERRUPT")
    llm_client.router_replies.append("1")
    result = graph.invoke(Command(resume="talk to a human"), config)

    assert said[-1] == "Goodbye."
    assert "__interrupt__" not in result or not result["__interrupt__"]
    assert graph.get_state(config).values["current_state"] == "CLOSE"
