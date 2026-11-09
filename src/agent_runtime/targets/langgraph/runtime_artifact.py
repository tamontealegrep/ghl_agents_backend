"""
Bundles everything `runtime/` needs into one self-contained, file-shaped artifact.

    This is the answer to "can the compiled graph be a replaceable file in my
    backend?" — yes, specifically this one. `RuntimeArtifact.to_dict()` is a
    plain, JSON-serializable dict with zero Pydantic objects and zero
    `langgraph` types; `runtime_artifact_from_dict()` reconstructs it. A
    backend that only ever *runs* compiled agents needs:

    - `runtime/*.py` (the LangGraph-executing engine)
    - `targets/langgraph/{condition_parser,type_parser,graph_renderer,runtime_artifact}.py`
      (dataclass definitions + this loader — none of them touch disk or import
      `langgraph`/`openai`)
    - `dsl/schemas.py` + `dsl/utils.py` (just the Pydantic models the artifact's
      `tool_contracts` are typed with, and the GO_TO regexes — no YAML I/O)

    It does NOT need `dsl/loaders.py`, `dsl/validators.py`, `dsl/classifier.py`,
    `dsl/deduplicator.py`, `targets/text/`, `diagrams/`, `compiler.py`, or
    `cli.py` — none of that is "the engine," it's "the compiler," and the
    compiler's job ends the moment `artifact.json` is written. Swapping an
    agent in production means replacing that one file and reloading it —
    never touching or redeploying the engine code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.dsl.schemas import AgentSpec, ToolContract
from agent_runtime.targets.langgraph.graph_renderer import (
    FaqNode,
    GlobalRouterDefinition,
    GraphDefinition,
    GraphEdge,
    GraphNode,
    render_agent_graph,
    render_global_router,
)

# Which `policies.yaml` sections reach which LangGraph LLM call sites
# (2026-09-18). `policies.yaml` itself is never carried into the
# `RuntimeArtifact` — only two pre-filtered, flattened line lists
# (`say_policies`/`judgment_policies`) are. This keeps
# `runtime/graph_builder.py` "dumb": it interpolates whatever text it is
# given, with zero knowledge of policy section names or channels.
#
# The split is by call *purpose*, not by node type: `say_sections` reach
# every call that generates text the user actually reads (`render_say`,
# for `message`/`terminal`/`question` phrasing and the global router's
# matched-handler/FAQ `say`). `judgment_sections` reach every call that
# interprets or decides something without saying it
# (`_llm_extract_capture`, `_apply_conditional_mutations`,
# `_llm_compute_store_value`, `_llm_pick_condition`, `_llm_bind_tool_inputs`
# — see `LLMContext.policies` in `runtime/llm_client.py`, which is how the
# judgment side actually reaches each call without a parameter threaded
# through all five).
#
# Section *names* are channel-specific (`style_and_async_rules` vs.
# `style_and_vui_rules` vs. `style_rules` — three different real names for
# "tone", one per `profiles/channels/*.yaml`; confirmed by reading all
# three files, not assumed), so a flat, channel-agnostic list silently
# drops tone/length/format for every channel but the one whose section
# names happen to match. `POLICY_SECTIONS_BY_CHANNEL` fixes that: one
# `ChannelPolicyMapping` per channel *profile name* (not per `ChannelType`
# — several profiles could in principle share the same coarse
# `ChannelType`, but each profile is its own independent set of section
# names), keyed the same way `compile_agent`/`load_channel_profile`
# already key a profile — its filename stem under `profiles/channels/`.
#
# Adding a new channel profile is one new dict entry here, nothing else —
# `_policy_mapping_for_channel` below refuses to silently fall through for
# an unmapped one (see its docstring) instead of quietly returning less
# content than the caller expects, the same failure mode a flat list had
# for every channel but `async_text`.
_UNIVERSAL_SAY_SECTIONS: tuple[str, ...] = ("compliance_and_scope_rules",)
_UNIVERSAL_JUDGMENT_SECTIONS: tuple[str, ...] = ("data_and_variable_rules",)


@dataclass(frozen=True)
class ChannelPolicyMapping:
    """
One channel profile's full say/judgment section mapping, grouped together.

    Deliberately one object per channel rather than two separate
        channel-keyed dicts (one for say, one for judgment) — everything a
        given channel gets lives in one place you can read top to bottom,
        and a new channel is one entry instead of two lookups that could
        silently drift apart from each other over time.
"""

    say_sections: tuple[str, ...]
    judgment_sections: tuple[str, ...] = _UNIVERSAL_JUDGMENT_SECTIONS


POLICY_SECTIONS_BY_CHANNEL: dict[str, ChannelPolicyMapping] = {
    "async_text": ChannelPolicyMapping(
        say_sections=("style_and_async_rules", "response_length_rules", "formatting_rules")
        + _UNIVERSAL_SAY_SECTIONS,
    ),
    "voice": ChannelPolicyMapping(
        say_sections=("style_and_vui_rules",) + _UNIVERSAL_SAY_SECTIONS,
    ),
    "generic": ChannelPolicyMapping(
        say_sections=("style_rules",) + _UNIVERSAL_SAY_SECTIONS,
    ),
}


def _policy_mapping_for_channel(channel_profile_name: str) -> ChannelPolicyMapping:
    """Look up `channel_profile_name`'s `ChannelPolicyMapping`.

    Raises rather than falling back to something channel-agnostic: a
    channel profile with no entry here is exactly the silent-content-gap
    failure mode this mapping exists to prevent (see this module's
    docstring above `POLICY_SECTIONS_BY_CHANNEL`) — better to fail loud at
    compile time, pointing at the one line to add, than to ship a
    `RuntimeArtifact` quietly missing tone/format guidance for that
    channel. `render_runtime_artifact`'s own `channel_profile_name`
    default ("generic") is always present in the dict below, so the
    default path itself can never hit this.
    """
    mapping = POLICY_SECTIONS_BY_CHANNEL.get(channel_profile_name)
    if mapping is None:
        known = sorted(POLICY_SECTIONS_BY_CHANNEL)
        raise ValueError(
            f"No ChannelPolicyMapping for channel profile {channel_profile_name!r} in "
            f"POLICY_SECTIONS_BY_CHANNEL (targets/langgraph/runtime_artifact.py). "
            f"Known channels: {known}. Add an entry for this channel before compiling "
            "the LangGraph artifact against it."
        )
    return mapping


def _flatten_policy_sections(spec: AgentSpec, section_names: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for name in section_names:
        lines.extend(spec.policies.get_section(name))
    return lines


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    """
Everything `runtime.graph_builder.build_graph()` needs, and nothing else.
"""

    agent_id: str
    graph: GraphDefinition
    global_router: GlobalRouterDefinition
    tool_contracts: list[ToolContract] = field(default_factory=list)
    constants: dict[str, str] = field(default_factory=dict)
    session_timeout_minutes: int | None = None
    say_policies: list[str] = field(default_factory=list)
    judgment_policies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict, JSON-serializable form — write this with `json.dump`.
        """
        return {
            "agent_id": self.agent_id,
            "graph": asdict(self.graph),
            "global_router": asdict(self.global_router),
            "tool_contracts": [c.model_dump() for c in self.tool_contracts],
            "constants": dict(self.constants),
            "session_timeout_minutes": self.session_timeout_minutes,
            "say_policies": list(self.say_policies),
            "judgment_policies": list(self.judgment_policies),
        }


def render_runtime_artifact(spec: AgentSpec, channel_profile_name: str = "generic") -> RuntimeArtifact:
    """Compile-time step: bundle an `AgentSpec` into a `RuntimeArtifact`.

    Args:
        spec: The fully merged agent specification.
        channel_profile_name: Which `profiles/channels/*.yaml` `spec`
            was loaded against — the same name passed to
            `load_channel_profile`/`compile_agent`. `AgentSpec` itself
            never stores this (`ManifestConfig`'s own docstring: channel is
            a compile-time parameter, not manifest content), so a caller
            compiling against a real channel must pass its real name here
            explicitly — the "generic" default matches `compile_agent`'s
            own default and exists for callers (tests, fixtures) that
            don't care about channel-specific say policies, not as
            something a production caller should rely on silently.

    Returns:
        RuntimeArtifact: Ready to `.to_dict()` and write to a `.json` file.
    """
    policy_mapping = _policy_mapping_for_channel(channel_profile_name)
    return RuntimeArtifact(
        agent_id=spec.manifest.agent_id,
        graph=render_agent_graph(spec),
        global_router=render_global_router(spec),
        tool_contracts=list(spec.tool_contracts),
        constants={c.name: c.value for c in spec.constants},
        session_timeout_minutes=spec.manifest.session_timeout_minutes,
        say_policies=_flatten_policy_sections(spec, policy_mapping.say_sections),
        judgment_policies=_flatten_policy_sections(spec, policy_mapping.judgment_sections),
    )


def _graph_edge_from_dict(data: dict[str, Any]) -> GraphEdge:
    return GraphEdge(**data)


def _graph_node_from_dict(data: dict[str, Any]) -> GraphNode:
    fields = dict(data)
    fields["route"] = [_graph_edge_from_dict(e) for e in fields.get("route", [])]
    fields["fallback"] = [_graph_edge_from_dict(e) for e in fields.get("fallback", [])]
    fields["capture"] = [tuple(c) for c in fields.get("capture", [])]
    return GraphNode(**fields)


def _graph_definition_from_dict(data: dict[str, Any]) -> GraphDefinition:
    return GraphDefinition(
        subflow_id=data["subflow_id"],
        entry_point=data["entry_point"],
        nodes=[_graph_node_from_dict(n) for n in data["nodes"]],
    )


def _global_router_from_dict(data: dict[str, Any]) -> GlobalRouterDefinition:
    return GlobalRouterDefinition(
        handlers=[_graph_node_from_dict(h) for h in data["handlers"]],
        faqs=[FaqNode(**f) for f in data["faqs"]],
    )


def runtime_artifact_from_dict(data: dict[str, Any]) -> RuntimeArtifact:
    """Load-time step: reconstruct a `RuntimeArtifact` from its `to_dict()` form.

    This is the one function a backend needs to load a compiled agent from
    a plain `.json` file it read off disk (or fetched from wherever it
    keeps swappable agent files) — no YAML, no `dsl.loaders`, no
    filesystem convention to match.
    """
    return RuntimeArtifact(
        agent_id=data["agent_id"],
        graph=_graph_definition_from_dict(data["graph"]),
        global_router=_global_router_from_dict(data["global_router"]),
        tool_contracts=[ToolContract.model_validate(c) for c in data.get("tool_contracts", [])],
        constants=dict(data.get("constants", {})),
        session_timeout_minutes=data.get("session_timeout_minutes"),
        say_policies=list(data.get("say_policies", [])),
        judgment_policies=list(data.get("judgment_policies", [])),
    )
