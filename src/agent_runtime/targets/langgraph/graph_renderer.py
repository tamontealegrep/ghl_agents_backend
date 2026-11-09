"""
Graph-definition emitter for the LangGraph target.

    This module emits a declarative, ``dataclasses.asdict``-serializable graph
    definition per SPEC.md §2.4's strategic direction — it does not import or
    depend on the ``langgraph`` package, and it does not execute anything.
    Whatever runs the emitted graph against a real LangGraph runtime is
    ``runtime/`` (a separate, optional consumer); this module only produces the
    artifact, the same way ``targets/text/renderer.py`` produces the System
    Prompt.

    ``render_subflow_graph`` operates on one ``SubflowTemplate`` at a time
    (local, pre-instantiation state ids); ``render_agent_graph`` operates on a
    whole merged ``AgentSpec``. Node types map 1:1 to ``FlowObjectBase.type`` —
    no renaming, since the DSL's own ``validate_semantics`` already constrains
    what each type may carry (DESIGN_PATTERNS.md P02).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.dsl.schemas import AgentSpec, FAQModel, FlowObjectBase, SubflowTemplate
from agent_runtime.dsl.utils import extract_goto_targets
from agent_runtime.targets.langgraph.condition_parser import classify_rule


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """
One outgoing edge from a node — from a single `route`/`fallback` line.
"""
    target: str
    condition_text: str | None
    is_mechanical: bool
    python_expression: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GraphNode:
    """
One node — a handler, state, or terminal_state.

    Carries `capture`/`goal`/`do`/`trigger` from its first version
        (DESIGN_PATTERNS.md P02) rather than being retrofitted per consumer.
"""

    node_id: str
    node_type: str
    goal: list[str] = field(default_factory=list)
    do: list[str] = field(default_factory=list)
    trigger: list[str] = field(default_factory=list)
    disabled_in: list[str] = field(default_factory=list)
    say: list[str] = field(default_factory=list)
    say_verbatim: bool = False
    execute: str | None = None
    store: list[str] = field(default_factory=list)
    capture: list[tuple[str, str]] = field(default_factory=list)
    eval: str = "code"
    route: list[GraphEdge] = field(default_factory=list)
    fallback: list[GraphEdge] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GraphDefinition:
    """
The full emitted artifact for one subflow (or one whole agent).
"""

    subflow_id: str
    entry_point: str
    nodes: list[GraphNode]

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation — no `langgraph` types involved.
        """
        return asdict(self)


def render_subflow_graph(template: SubflowTemplate) -> GraphDefinition:
    """Build a `GraphDefinition` from a `SubflowTemplate`'s local states.

    Args:
        template: The subflow template to render, with
            local (pre-instantiation) state ids.

    Returns:
        GraphDefinition: One node per handler/state/terminal_state, edges
        derived from `route`/`fallback` via `condition_parser`.

    Raises:
        ValueError: If `template.exports.states` has no `"entry"` key and
            the template doesn't have exactly one `type=start` state either.
    """
    entry_point = template.exports.states.get("entry")
    if entry_point is None:
        entry_point = _infer_entry_from_start_state(template)

    nodes = [
        _render_node(state, state.state_id)
        for state in list(template.states) + list(template.terminal_states)
    ]
    return GraphDefinition(subflow_id=template.template_id, entry_point=entry_point, nodes=nodes)


def _infer_entry_from_start_state(template: SubflowTemplate) -> str:
    """Fall back to the template's single `type=start` state as entry point.

    Several subflow templates never declare `exports.states.entry`,
    relying instead on there being exactly one `type=start` state by
    convention — the same convention an author-drawn Mermaid diagram for a
    subflow already shows as the entry node.
    """
    start_states = [state for state in template.states if state.type == "start"]
    if len(start_states) != 1:
        raise ValueError(
            f"Subflow template {template.template_id!r} has no exports.states.entry, "
            f"and does not have exactly one type=start state to fall back to "
            f"(found {len(start_states)}) — the LangGraph emitter needs an explicit entry point."
        )
    return start_states[0].state_id


def _render_node(obj: FlowObjectBase, node_id: str) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=obj.type,
        goal=list(obj.goal),
        do=list(obj.do),
        trigger=list(getattr(obj, "trigger", [])),
        disabled_in=list(getattr(obj, "disabled_in", [])),
        say=list(obj.say),
        say_verbatim=obj.say_verbatim,
        execute=obj.execute,
        store=list(obj.store),
        capture=[(c.slot, c.type_expr) for c in obj.capture],
        eval=obj.eval,
        route=[_render_edge(line, obj.eval) for line in obj.route],
        fallback=[_render_edge(line, obj.eval) for line in obj.fallback],
    )


def _render_edge(line: str, eval_mode: str) -> GraphEdge:
    result = classify_rule(line)
    is_mechanical = result.eval_class == "code" and eval_mode != "llm"

    target = result.target
    if target is None:
        # `classify_rule` only sets a target for lines matching its strict
        # "GO_TO:" / "IF ... -> GO_TO:" shape. Fall back to the lenient
        # GO_TO extractor (dsl.utils) so a still-routable-but-non-canonical
        # line (e.g. missing "->") keeps a usable edge target.
        fallback_targets = extract_goto_targets(line)
        target = fallback_targets[0] if fallback_targets else ""

    return GraphEdge(
        target=target,
        condition_text=None if result.kind == "unconditional" else line,
        is_mechanical=is_mechanical,
        python_expression=result.python_expression if is_mechanical else None,
        reason=None if is_mechanical else (result.reason or "eval='llm' forces an LLM-evaluated edge"),
    )


def render_agent_graph(spec: AgentSpec) -> GraphDefinition:
    """Build a `GraphDefinition` for an entire `AgentSpec`'s main flow.

    Unlike `render_subflow_graph` (one `SubflowTemplate`, local ids), this
    operates on `spec.states`/`spec.terminal_states` directly — by the time
    an `AgentSpec` exists, every subflow instance is already merged in with
    namespaced ids (`dsl/loaders.py`), so no separate subflow pass is
    needed here.

    Args:
        spec: The fully merged agent specification.

    Returns:
        GraphDefinition: `entry_point` is `spec.manifest.start_at`;
        `subflow_id` is `spec.manifest.agent_id` (reusing the same
        field — this is the whole agent's graph, not one subflow).
    """
    nodes = [
        _render_node(state, state.state_id)
        for state in list(spec.states) + list(spec.terminal_states)
    ]
    return GraphDefinition(
        subflow_id=spec.manifest.agent_id,
        entry_point=spec.manifest.start_at,
        nodes=nodes,
    )


@dataclass(frozen=True, slots=True)
class FaqNode:
    """
A FAQ entry — simpler than `GraphNode` since FAQs have no `route`/

    `eval`: answering one is always a single say-and-resume.
"""

    faq_id: str
    match: list[str] = field(default_factory=list)
    say: list[str] = field(default_factory=list)
    say_verbatim: bool = False
    resume_to: str | None = None


@dataclass(frozen=True, slots=True)
class GlobalRouterDefinition:
    """
Declarative definition of every global handler and FAQ.

    A real runtime checks these — handler `trigger` phrases and FAQ `match`
        phrases — before dispatching to the active state's own node, on every
        turn of a continuing session (DESIGN_PATTERNS.md P04). This module only
        emits the data; the trigger/match evaluation itself is `runtime/`'s job.
"""

    handlers: list[GraphNode]
    faqs: list[FaqNode]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def render_global_router(spec: AgentSpec) -> GlobalRouterDefinition:
    """Build the `GlobalRouterDefinition` for an `AgentSpec`'s handlers and FAQs.

    Args:
        spec: The fully merged agent specification.

    Returns:
        GlobalRouterDefinition: One `GraphNode` per handler (reusing the
        same node/edge shape as `render_subflow_graph`, since
        `HandlerModel` is a `FlowObjectBase` too) and one `FaqNode` per
        FAQ.
    """
    handler_nodes = [_render_node(handler, handler.handler_id) for handler in spec.handlers]
    faq_nodes = [_render_faq_node(faq) for faq in spec.faqs]
    return GlobalRouterDefinition(handlers=handler_nodes, faqs=faq_nodes)


def _render_faq_node(faq: FAQModel) -> FaqNode:
    return FaqNode(
        faq_id=faq.faq_id,
        match=list(faq.match),
        say=list(faq.say),
        say_verbatim=faq.say_verbatim,
        resume_to=faq.resume_to,
    )
