"""
Unit tests for the global router emitter (agent_runtime.targets.langgraph.graph_renderer)

    and — test-only, not shipped in src/ — a deterministic turn simulation that verifies the
    emitted definition is sufficient for a real runtime to implement resume behavior.

    The simulation below is intentionally NOT part of the shipped package: SPEC.md §6
    principle 2 keeps this compiler an artifact producer, not a runtime service. This
    module proves the artifact (GlobalRouterDefinition + GraphNode) carries everything a
    runtime would need — it does not ship that runtime (that's `runtime/`'s job).
"""

from __future__ import annotations

from agent_runtime.dsl.schemas import FAQModel, HandlerModel
from agent_runtime.dsl.utils import dynamic_target_slot_name, is_dynamic_target
from agent_runtime.targets.langgraph.graph_renderer import render_global_router
from tests.contract.conftest import build_message_state, build_minimal_agent_spec


def _handler(handler_id: str, **overrides) -> HandlerModel:
    data = {
        "handler_id": handler_id,
        "type": "message",
        "wait": "no",
        "say": ["Handled."],
        "trigger": ["some trigger phrase"],
        "route": ["GO_TO: [current_state]"],
    }
    data.update(overrides)
    return HandlerModel.model_validate(data)


def _faq(faq_id: str, **overrides) -> FAQModel:
    data = {
        "faq_id": faq_id,
        "type": "message",
        "match": ["what are your hours"],
        "say": ["We're open 9 to 5."],
        "resume_to": "[current_state]",
    }
    data.update(overrides)
    return FAQModel.model_validate(data)


# ---------------------------------------------------------------------------
# render_global_router
# ---------------------------------------------------------------------------


def test_render_global_router_emits_handler_nodes():
    spec = build_minimal_agent_spec(handlers=[_handler("H_REPEAT")])
    router = render_global_router(spec)
    assert [h.node_id for h in router.handlers] == ["H_REPEAT"]
    assert router.handlers[0].node_type == "message"


def test_render_global_router_handler_carries_trigger():
    """
A runtime's global-router matching needs the trigger phrases to check

    an incoming reply against — GraphNode must carry them.

    Returns:
        None.
"""
    spec = build_minimal_agent_spec(handlers=[_handler("H_REPEAT", trigger=["repeat that", "say again"])])
    router = render_global_router(spec)
    assert router.handlers[0].trigger == ["repeat that", "say again"]


def test_render_global_router_emits_faq_nodes():
    spec = build_minimal_agent_spec(faqs=[_faq("FAQ_HOURS")])
    router = render_global_router(spec)
    assert [f.faq_id for f in router.faqs] == ["FAQ_HOURS"]
    assert router.faqs[0].match == ["what are your hours"]
    assert router.faqs[0].resume_to == "[current_state]"


def test_handler_node_route_is_mechanical_via_dynamic_resume():
    spec = build_minimal_agent_spec(
        handlers=[
            _handler(
                "H_REPEAT",
                route=[
                    "IF [repeat_count] < <MAX_REPEAT_ATTEMPTS> -> GO_TO: [current_state]",
                    "IF [repeat_count] >= <MAX_REPEAT_ATTEMPTS> -> GO_TO: CLOSE",
                ],
            )
        ]
    )
    router = render_global_router(spec)
    handler_node = router.handlers[0]
    targets = {edge.target for edge in handler_node.route}
    assert targets == {"[current_state]", "CLOSE"}
    for edge in handler_node.route:
        assert edge.is_mechanical is True


# ---------------------------------------------------------------------------
# Test-only turn simulation — proves the resume behavior is implementable
# from the emitted data alone (no simulation code is shipped in src/ —
# trigger matching here is exact-substring, a deterministic stand-in for
# whatever a real runtime uses, e.g. an LLM or classifier).
# ---------------------------------------------------------------------------


def test_matching_trigger_mid_flow_resumes_at_original_current_state():
    """
A message matches a HandlerModel.trigger mid-flow, and afterward the

    session resumes at the `current_state` that was active before the
        handler fired.

    Returns:
        None.
"""
    spec = build_minimal_agent_spec(
        states=[build_message_state(state_id="ASKING_NAME", route=["GO_TO: CLOSE"])],
        handlers=[
            _handler(
                "H_REPEAT",
                trigger=["repeat that"],
                route=["IF [repeat_count] < <MAX_REPEAT_ATTEMPTS> -> GO_TO: [current_state]"],
            )
        ],
    )
    router = render_global_router(spec)
    handler_node = router.handlers[0]
    handler_source = spec.handlers[0]

    session = {"current_state": "ASKING_NAME", "repeat_count": 1}
    incoming_message = "Sorry, can you repeat that?"

    # Global router step: does the incoming message match any trigger?
    matched = any(trigger.lower() in incoming_message.lower() for trigger in handler_source.trigger)
    assert matched is True

    # Handler's own route decides where to go, using the emitted mechanical
    # edge (repeat_count=1 < MAX_RETRY_ATTEMPTS -> dynamic GO_TO: [current_state]).
    edge = handler_node.route[0]
    assert edge.is_mechanical is True
    assert edge.target == "[current_state]"
    assert is_dynamic_target(edge.target)
    assert dynamic_target_slot_name(edge.target) == "current_state"

    # Runtime resolves the dynamic target by reading the *session's own*
    # current_state (unchanged by the handler) — this is the resume.
    next_state = session["current_state"] if is_dynamic_target(edge.target) else edge.target
    assert next_state == "ASKING_NAME"
