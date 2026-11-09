"""
Unit tests for agent_runtime.targets.langgraph.runtime_artifact.

    Proves the round-trip a real backend would do: compile once
    (`render_runtime_artifact`), serialize to plain JSON (`to_dict` +
    `json.dumps`), write/read a file, deserialize (`runtime_artifact_from_dict`
    + `json.loads`), and get back an equivalent artifact — no `AgentSpec`,
    no YAML, no `dsl.loaders` involved in the second half.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_runtime.dsl.schemas import ConstantItem, HandlerModel, ToolContract
from agent_runtime.targets.langgraph.runtime_artifact import (
    POLICY_SECTIONS_BY_CHANNEL,
    render_runtime_artifact,
    runtime_artifact_from_dict,
)
from tests.contract.conftest import build_message_state, build_minimal_agent_spec, build_minimal_policies

_CHANNEL_PROFILES_DIR = Path(__file__).resolve().parents[4] / "profiles" / "channels"


def _spec_with_everything():
    contract = ToolContract.model_validate(
        {
            "name": "book_appointment",
            "description": "Books it.",
            "inputs": [{"name": "slot_start", "description": "d"}],
            "outputs": [{"name": "event_id", "description": "d"}],
        }
    )
    handler = HandlerModel.model_validate(
        {
            "handler_id": "H_REPEAT",
            "type": "message",
            "wait": "no",
            "say": ["Sure."],
            "trigger": ["repeat that"],
            "route": ["GO_TO: [current_state]"],
        }
    )
    return build_minimal_agent_spec(
        constants=[ConstantItem(name="MAX_RETRY_ATTEMPTS", description="d", value="3")],
        tools=["book_appointment"],
        tool_contracts=[contract],
        handlers=[handler],
    )


def test_to_dict_is_plain_json_serializable():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    encoded = json.dumps(artifact.to_dict())  # raises if anything isn't plain JSON
    assert "book_appointment" in encoded


def test_round_trip_preserves_agent_id_and_entry_point():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert reloaded.agent_id == artifact.agent_id == "test_agent"
    assert reloaded.graph.entry_point == artifact.graph.entry_point


def test_round_trip_preserves_node_edges():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    original_node = next(n for n in artifact.graph.nodes if n.node_id == "GREETING")
    reloaded_node = next(n for n in reloaded.graph.nodes if n.node_id == "GREETING")
    assert reloaded_node.route == original_node.route
    assert reloaded_node.route[0].target == "CLOSE"


def test_round_trip_preserves_capture_as_tuples():
    state = build_message_state(
        type="question", wait="yes", say=["Q?"], capture=[{"slot": "name", "type_expr": "str"}]
    )
    spec = build_minimal_agent_spec(states=[state])
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    node = next(n for n in reloaded.graph.nodes if n.node_id == "GREETING")
    assert node.capture == [("name", "str")]
    assert isinstance(node.capture[0], tuple)


def test_round_trip_preserves_global_router_handlers_and_faqs():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert [h.node_id for h in reloaded.global_router.handlers] == ["H_REPEAT"]
    assert reloaded.global_router.handlers[0].trigger == ["repeat that"]


def test_round_trip_preserves_tool_contracts_as_tool_contract_instances():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert isinstance(reloaded.tool_contracts[0], ToolContract)
    assert reloaded.tool_contracts[0].name == "book_appointment"
    assert reloaded.tool_contracts[0].inputs[0].name == "slot_start"


def test_round_trip_preserves_constants():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert reloaded.constants == {"MAX_RETRY_ATTEMPTS": "3"}


def test_round_trip_preserves_none_session_timeout():
    spec = _spec_with_everything()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert reloaded.session_timeout_minutes is None


def test_no_tool_contracts_or_handlers_round_trips_to_empty_lists():
    spec = build_minimal_agent_spec()
    artifact = render_runtime_artifact(spec)
    reloaded = runtime_artifact_from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert reloaded.tool_contracts == []
    assert reloaded.global_router.handlers == []
    assert reloaded.global_router.faqs == []


# ---------------------------------------------------------------------------
# Channel-aware say/judgment policy scoping (2026-09-18)
# ---------------------------------------------------------------------------


def _spec_with_policies(**sections: list[str]):
    return build_minimal_agent_spec(policies=build_minimal_policies(**sections))


def test_async_text_channel_pulls_its_own_style_section_into_say_policies():
    spec = _spec_with_policies(
        style_and_async_rules=["Be warm."],
        response_length_rules=["Keep it short."],
        formatting_rules=["Use bullets."],
        compliance_and_scope_rules=["State you are an AI."],
        data_and_variable_rules=["Never invent availability."],
    )
    artifact = render_runtime_artifact(spec, "async_text")
    assert artifact.say_policies == [
        "Be warm.",
        "Keep it short.",
        "Use bullets.",
        "State you are an AI.",
    ]
    assert artifact.judgment_policies == ["Never invent availability."]


def test_voice_channel_pulls_its_own_style_section_not_the_text_ones():
    spec = _spec_with_policies(
        style_and_vui_rules=["Speak naturally."],
        # A voice-compiled spec never has these — present here only to prove
        # the voice mapping does NOT pull them in even if they exist.
        response_length_rules=["Keep it short."],
        compliance_and_scope_rules=["State you are an AI."],
    )
    artifact = render_runtime_artifact(spec, "voice")
    assert artifact.say_policies == ["Speak naturally.", "State you are an AI."]


def test_generic_channel_pulls_style_rules():
    spec = _spec_with_policies(style_rules=["Be concise."], compliance_and_scope_rules=["Be honest."])
    artifact = render_runtime_artifact(spec, "generic")
    assert artifact.say_policies == ["Be concise.", "Be honest."]


def test_default_channel_profile_name_is_generic():
    spec = _spec_with_policies(style_rules=["Be concise."])
    artifact = render_runtime_artifact(spec)
    assert artifact.say_policies == ["Be concise."]


def test_unmapped_channel_raises_instead_of_silently_returning_no_policies():
    spec = _spec_with_policies(compliance_and_scope_rules=["Be honest."])
    with pytest.raises(ValueError, match="not_a_real_channel"):
        render_runtime_artifact(spec, "not_a_real_channel")


_profiles_dir_required = pytest.mark.skipif(
    not _CHANNEL_PROFILES_DIR.is_dir(),
    reason=(
        "profiles/channels/ is compiler-only content (dsl.loaders/CLI concern) — "
        "scripts/export_runtime.py deliberately excludes it from the standalone "
        "runtime package, so this cross-check against real files only applies "
        "when running from the agent_compiler repo."
    ),
)


@_profiles_dir_required
def test_every_real_channel_profile_has_a_policy_mapping():
    """
Guards the exact failure this mapping exists to prevent: a new

    `profiles/channels/*.yaml` added without a matching entry in
        `POLICY_SECTIONS_BY_CHANNEL` would otherwise silently degrade — no
        error, just fewer policy lines than the new channel's own sections
        declare. This test fails loudly instead, at the moment the profile is
        added, not months later against a real compiled agent.

    Returns:
        None.
"""
    profile_names = {p.stem for p in _CHANNEL_PROFILES_DIR.glob("*.yaml")}
    assert profile_names, "No profiles/channels/*.yaml found — check _CHANNEL_PROFILES_DIR."
    missing = profile_names - set(POLICY_SECTIONS_BY_CHANNEL)
    assert not missing, f"profiles/channels/*.yaml with no POLICY_SECTIONS_BY_CHANNEL entry: {missing}"


@_profiles_dir_required
def test_channel_mapping_only_uses_sections_the_real_profile_declares():
    """
Cross-checks each `ChannelPolicyMapping` against the real channel

    profile's own declared `policy_sections` — catches a typo'd or
        stale section name in the mapping (e.g. referencing a section a
        profile used to have) that `_flatten_policy_sections` would otherwise
        swallow silently (`get_section` returns `[]` for an unknown name,
        it never raises).

    Returns:
        None.
"""
    for profile_path in _CHANNEL_PROFILES_DIR.glob("*.yaml"):
        channel_name = profile_path.stem
        declared = {s["name"] for s in yaml.safe_load(profile_path.read_text(encoding="utf-8"))["policy_sections"]}
        mapping = POLICY_SECTIONS_BY_CHANNEL[channel_name]
        used = set(mapping.say_sections) | set(mapping.judgment_sections)
        unknown = used - declared
        assert not unknown, f"{channel_name}: mapping references undeclared section(s) {unknown}"
