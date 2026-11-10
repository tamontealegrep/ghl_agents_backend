"""
Backend copy of the compiler test builders (trimmed: no loader-dependent fixtures). Hand-maintained.

Cross-suite fixtures and small AgentSpec builders shared by multiple test files.

    Fixtures that are only useful to a single test module live in that module
    instead (per TESTING.md §2). This file holds:

    - ``build_minimal_agent_spec`` — an in-memory ``AgentSpec`` factory with a
      single message state routing to a single terminal state, so unit tests
      for validators/classifier/renderers/deduplicator don't need to touch disk
      or repeat the same ten-field boilerplate.
"""

from __future__ import annotations

from agent_runtime.dsl.schemas import (
    AgentSpec,
    ApprovedProcessStep,
    ConstantItem,
    ContextFile,
    FAQModel,
    HandlerModel,
    InputVariable,
    ManifestConfig,
    ManifestIncludes,
    MemorySlot,
    ObjectivesFile,
    PoliciesFile,
    StateModel,
    SummaryServiceItem,
    ToolContract,
)


def build_minimal_manifest(**overrides) -> ManifestConfig:
    """
    Build a minimal valid ``ManifestConfig`` (start_at='GREETING').

        Parameters:
            overrides: Description.

        Returns:
            The result.
    """
    data = {
        "agent_id": "test_agent",
        "version": "1.0.0",
        "language": "en",
        "start_at": "GREETING",
        "dynamic_state_slots": ["current_state", "resume_state"],
        "includes": ManifestIncludes(),
        "subflow_instances": [],
    }
    data.update(overrides)
    return ManifestConfig.model_validate(data)


def build_minimal_objectives() -> ObjectivesFile:
    return ObjectivesFile(
        primary_objective=["Greet and close."],
        secondary_objectives=["Demonstrate a minimal flow."],
        success_alternatives=["The caller is greeted and the call closes."],
    )


def build_minimal_context() -> ContextFile:
    return ContextFile(
        company_context=["Synthetic test company."],
        approved_services=["Synthetic service."],
        summary_services_library=[
            SummaryServiceItem(
                key="GREETING_SERVICE",
                procedure="greeting_service",
                text="A synthetic service used only for tests.",
            )
        ],
        approved_process_intro="Synthetic approved process.",
        approved_process_steps=[ApprovedProcessStep(title="Step one", text="Greet the caller.")],
        support_and_trust=["This is a test fixture."],
    )


def build_minimal_policies(**sections: list[str]) -> PoliciesFile:
    """
    Build a ``PoliciesFile`` with whatever dynamic sections are passed as kwargs.

        Parameters:
            sections: Description.

        Returns:
            The result.
    """
    return PoliciesFile.model_validate(sections)


def build_message_state(
    state_id: str = "GREETING", *, route: list[str] | None = None, say: list[str] | None = None, **overrides
) -> StateModel:
    """
    Build a minimal valid ``type=message`` state (or another type via overrides).

        Parameters:
            state_id: Description.
            route: Description.
            say: Description.
            overrides: Description.

        Returns:
            The result.
    """
    data = {
        "state_id": state_id,
        "type": "message",
        "say": say if say is not None else ["Hello."],
        "wait": "no",
        "route": route if route is not None else ["GO_TO: CLOSE"],
    }
    data.update(overrides)
    return StateModel.model_validate(data)


def build_terminal_state(state_id: str = "CLOSE", **overrides) -> StateModel:
    """
    Build a minimal valid ``type=terminal`` state.

        Parameters:
            state_id: Description.
            overrides: Description.

        Returns:
            The result.
    """
    data = {"state_id": state_id, "type": "terminal", "say": ["Goodbye."], "wait": "no", "final": "yes"}
    data.update(overrides)
    return StateModel.model_validate(data)


def build_minimal_agent_spec(
    *,
    states: list[StateModel] | None = None,
    terminal_states: list[StateModel] | None = None,
    handlers: list[HandlerModel] | None = None,
    faqs: list[FAQModel] | None = None,
    constants: list[ConstantItem] | None = None,
    input_variables: list[InputVariable] | None = None,
    tools: list[str] | None = None,
    tool_contracts: list[ToolContract] | None = None,
    tool_argument_overrides: dict[str, dict[str, str]] | None = None,
    memory_slots: list[MemorySlot] | None = None,
    flow_rules: list[str] | None = None,
    faq_policy: list[str] | None = None,
    manifest: ManifestConfig | None = None,
    policies: PoliciesFile | None = None,
) -> AgentSpec:
    """
    Build a minimal, schema-valid, in-memory ``AgentSpec``.

        Defaults to a two-node flow (``GREETING`` message -> ``CLOSE`` terminal)
            with the two mandatory dynamic-state memory slots declared. Every
            argument can be overridden to shape the spec for a specific validator
            or renderer test without touching disk.

        Parameters:
            states: Description.
            terminal_states: Description.
            handlers: Description.
            faqs: Description.
            constants: Description.
            input_variables: Description.
            tools: Description.
            tool_contracts: Description.
            tool_argument_overrides: Description.
            memory_slots: Description.
            flow_rules: Description.
            faq_policy: Description.
            manifest: Description.
            policies: Description.

        Returns:
            The result.
    """
    return AgentSpec(
        manifest=manifest if manifest is not None else build_minimal_manifest(),
        constants=constants if constants is not None else [],
        input_variables=input_variables if input_variables is not None else [],
        tools=tools if tools is not None else [],
        tool_contracts=tool_contracts if tool_contracts is not None else [],
        tool_argument_overrides=tool_argument_overrides if tool_argument_overrides is not None else {},
        memory_slots=(
            memory_slots
            if memory_slots is not None
            else [
                MemorySlot(name="current_state", description="Active state id.", kind="dynamic_state"),
                MemorySlot(name="resume_state", description="Resume state id.", kind="dynamic_state"),
            ]
        ),
        identity=["Synthetic test identity."],
        objectives=build_minimal_objectives(),
        context=build_minimal_context(),
        policies=policies if policies is not None else build_minimal_policies(),
        flow_rules=flow_rules if flow_rules is not None else [],
        faq_policy=faq_policy if faq_policy is not None else [],
        handlers=handlers if handlers is not None else [],
        faqs=faqs if faqs is not None else [],
        states=states if states is not None else [build_message_state()],
        terminal_states=terminal_states if terminal_states is not None else [build_terminal_state()],
    )
