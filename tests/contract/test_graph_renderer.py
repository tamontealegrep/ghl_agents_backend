"""
Unit tests for agent_runtime.targets.langgraph.graph_renderer — the graph-definition emitter.

    Only synthetic templates are used — no real agent content lives in this
    repo (CLAUDE.md §5.2.11 / SPEC.md §4 non-objectives).
"""

from __future__ import annotations

import pytest

from agent_runtime.dsl.schemas import StateModel, SubflowTemplate
from agent_runtime.targets.langgraph.graph_renderer import render_agent_graph, render_subflow_graph
from tests.contract.conftest import build_message_state, build_minimal_agent_spec, build_terminal_state


def _state(state_id: str, **overrides) -> StateModel:
    data = {
        "state_id": state_id,
        "type": "decision",
        "wait": "no",
        "say": [],
        "route": ["GO_TO: T_END"],
        "fallback": [],
    }
    data.update(overrides)
    return StateModel.model_validate(data)


def _minimal_template(**overrides) -> SubflowTemplate:
    data = {
        "template_id": "test_subflow",
        "description": "d",
        "states": [
            _state("T_S", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state(
                "T_DEC",
                route=["IF [x] IS NULL -> GO_TO: T_END"],
                fallback=["GO_TO: T_END"],
            ),
        ],
        "terminal_states": [
            _state("T_END", type="terminal", say=["Bye."], wait="no", final="yes", route=[])
        ],
        "exports": {"states": {"entry": "T_S"}},
    }
    data.update(overrides)
    return SubflowTemplate.model_validate(data)


# ---------------------------------------------------------------------------
# Synthetic template
# ---------------------------------------------------------------------------


def test_entry_point_and_subflow_id():
    graph = render_subflow_graph(_minimal_template())
    assert graph.entry_point == "T_S"
    assert graph.subflow_id == "test_subflow"


def test_node_count_and_types():
    graph = render_subflow_graph(_minimal_template())
    node_types = {n.node_id: n.node_type for n in graph.nodes}
    assert node_types == {"T_S": "start", "T_DEC": "decision", "T_END": "terminal"}


def test_mechanical_edge_carries_python_expression_and_target():
    graph = render_subflow_graph(_minimal_template())
    dec_node = next(n for n in graph.nodes if n.node_id == "T_DEC")
    edge = dec_node.route[0]
    assert edge.is_mechanical is True
    assert edge.python_expression == "x is None"
    assert edge.target == "T_END"


def test_unconditional_edge_has_no_condition_text():
    graph = render_subflow_graph(_minimal_template())
    dec_node = next(n for n in graph.nodes if n.node_id == "T_DEC")
    fallback_edge = dec_node.fallback[0]
    assert fallback_edge.condition_text is None
    assert fallback_edge.target == "T_END"
    assert fallback_edge.is_mechanical is True


def test_eval_llm_forces_llm_edge_even_if_parseable():
    template = _minimal_template(
        states=[
            _state("T_S", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state(
                "T_DEC",
                route=["IF [x] IS NULL -> GO_TO: T_END"],
                fallback=["GO_TO: T_END"],
                eval="llm",
            ),
        ]
    )
    graph = render_subflow_graph(template)
    dec_node = next(n for n in graph.nodes if n.node_id == "T_DEC")
    assert dec_node.route[0].is_mechanical is False
    assert dec_node.route[0].python_expression is None


def test_missing_entry_export_falls_back_to_the_single_start_state():
    """
Some subflows never declare exports.states.entry, relying instead on the

    convention that there is exactly one type=start state. The emitter must
        tolerate that, not just the explicit-export form.

    Returns:
        None.
"""
    graph = render_subflow_graph(_minimal_template(exports={"states": {}}))
    assert graph.entry_point == "T_S"


def test_missing_entry_export_and_no_start_state_raises():
    template = _minimal_template(
        exports={"states": {}},
        states=[
            _state("T_DEC", route=["GO_TO: T_END"], fallback=["GO_TO: T_END"]),
        ],
    )
    with pytest.raises(ValueError, match="entry"):
        render_subflow_graph(template)


def test_missing_entry_export_and_multiple_start_states_raises():
    template = _minimal_template(
        exports={"states": {}},
        states=[
            _state("T_S", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state("T_S2", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state(
                "T_DEC",
                route=["IF [x] IS NULL -> GO_TO: T_END"],
                fallback=["GO_TO: T_END"],
            ),
        ],
    )
    with pytest.raises(ValueError, match="entry"):
        render_subflow_graph(template)


def test_explicit_entry_export_takes_precedence_over_start_state():
    template = _minimal_template(
        states=[
            _state("T_S", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state("T_OTHER_S", type="start", say=[], route=["GO_TO: T_DEC"]),
            _state(
                "T_DEC",
                route=["IF [x] IS NULL -> GO_TO: T_END"],
                fallback=["GO_TO: T_END"],
            ),
        ],
        exports={"states": {"entry": "T_OTHER_S"}},
    )
    graph = render_subflow_graph(template)
    assert graph.entry_point == "T_OTHER_S"


# ---------------------------------------------------------------------------
# render_agent_graph — the top-level AgentSpec, not one subflow template
# ---------------------------------------------------------------------------


def test_render_agent_graph_entry_point_is_start_at():
    spec = build_minimal_agent_spec()
    graph = render_agent_graph(spec)
    assert graph.entry_point == spec.manifest.start_at == "GREETING"
    assert graph.subflow_id == spec.manifest.agent_id


def test_node_carries_goal_and_do():
    """
A runtime's extraction/decision prompts need the DSL's own normalization

    instructions — without `goal`, an LLM extraction has no way to know two
        normalized values are meant to stay distinct categories, not synonyms.

    Returns:
        None.
"""
    state = _state(
        "T_Q",
        type="question",
        wait="yes",
        say=["What's your name?"],
        route=["GO_TO: T_END"],
        goal=["Capture the caller's name."],
        do=["Normalize nicknames to the formal given name."],
    )
    template = _minimal_template(states=[_state("T_S", type="start", say=[], route=["GO_TO: T_Q"]), state])
    graph = render_subflow_graph(template)
    node = next(n for n in graph.nodes if n.node_id == "T_Q")
    assert node.goal == ["Capture the caller's name."]
    assert node.do == ["Normalize nicknames to the formal given name."]


def test_node_carries_capture_fields():
    """
A runtime needs to know what to extract from a question / populate from a tool call.

    Returns:
        None.
"""
    state = _state(
        "T_Q",
        type="question",
        wait="yes",
        say=["What's your name?"],
        route=["GO_TO: T_END"],
        capture=[{"slot": "x", "type_expr": "str"}],
    )
    template = _minimal_template(
        states=[
            _state("T_S", type="start", say=[], route=["GO_TO: T_Q"]),
            state,
        ]
    )
    graph = render_subflow_graph(template)
    node = next(n for n in graph.nodes if n.node_id == "T_Q")
    assert node.capture == [("x", "str")]


def test_render_agent_graph_includes_states_and_terminal_states():
    spec = build_minimal_agent_spec(
        states=[build_message_state("GREETING", route=["GO_TO: CLOSE"])],
        terminal_states=[build_terminal_state("CLOSE")],
    )
    graph = render_agent_graph(spec)
    node_ids = {n.node_id for n in graph.nodes}
    assert node_ids == {"GREETING", "CLOSE"}
