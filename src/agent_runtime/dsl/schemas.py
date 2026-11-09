"""
Pydantic v2 schemas for the agent DSL.

    This module defines every typed data model used by the loaders, classifier,
    validators, deduplicator, renderers, and compiler. Schemas are split into:

    - Compilation parameters (``CompilationParams`` and the supporting enums).
    - Channel and compliance profiles (``ChannelProfile``, ``ComplianceProfile``).
    - Manifest and includes (``ManifestConfig``, ``ManifestIncludes``,
      ``SubflowInstanceRef``).
    - Static agent content (constants, input variables, tools, contracts, memory
      slots, identity, objectives, context, policies, flow rules, faq policy).
    - Flow objects (``FlowObjectBase``, ``HandlerModel``, ``FAQModel``,
      ``StateModel``), including ``say_verbatim`` and ``eval``. ``eval``'s
      mechanical-parseability requirement (``dsl/condition_grammar.py`` +
      ``dsl/validators.py``) is enforced for every compile, either target —
      not LangGraph-only (see ``dsl/validators.py``'s module docstring).
    - Subflow templates (``SubflowTemplate``, ``TemplateParamDefinition``,
      ``SubflowExports``).
    - Aggregate ``AgentSpec`` plus the pipeline output dataclasses
      (``CompilationStats``, ``CompilationOutputs``).

    All schemas inherit from ``StrictModel`` which forbids unknown fields and
    trims whitespace from string inputs. ``PoliciesFragmentFile`` is the only
    exception: its section names are dynamic (driven by the active channel
    profile), so it uses ``extra='allow'`` with a ``model_validator`` that vets
    every dynamic section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_runtime.dsl.capture_types import classify_type_expr

if TYPE_CHECKING:
    # Forward references resolved by the type checker only. The runtime
    # classes live in dsl/validators.py and dsl/deduplicator.py and are not
    # imported here in order to avoid an import cycle.
    from agent_runtime.dsl.deduplicator import DeduplicationReport
    from agent_runtime.dsl.validators import OrphanStateReport, ValidationReport


# ---------------------------------------------------------------------------
# Type aliases and regex patterns
# ---------------------------------------------------------------------------

YES_NO = Literal["yes", "no"]
NODE_TYPE = Literal["message", "question", "decision", "action", "registration", "terminal", "start", "subflow_change"]

LOWER_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DOTTED_LOWER_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
UPPER_CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
UPPER_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
RULE_ID_RE = re.compile(r"^[A-Z]+_[0-9]+$")


# ---------------------------------------------------------------------------
# Strict base model and validation helpers
# ---------------------------------------------------------------------------


class StrictModel(BaseModel):
    """
Base model: forbid extra fields, trim string inputs, validate on assignment.
"""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


def validate_pattern(value: str, pattern: re.Pattern[str], label: str) -> str:
    """Return ``value`` if it matches ``pattern``; otherwise raise ``ValueError``.
    """
    if not value or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def validate_non_empty_lines(
    lines: list[str], label: str, *, allow_empty: bool = True
) -> list[str]:
    """Validate that every item in ``lines`` is a non-empty trimmed string.

    If ``allow_empty`` is ``False``, the list itself must be non-empty too.
    """
    if not allow_empty and not lines:
        raise ValueError(f"{label} must not be empty.")
    for item in lines:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} contains an empty or invalid string.")
    return lines


# ---------------------------------------------------------------------------
# Compilation parameters and enums
# ---------------------------------------------------------------------------


class ChannelType(str, Enum):
    """
Delivery channel of the compiled agent.
"""

    VOICE = "voice"
    CHAT = "chat"
    ASYNC_TEXT = "async_text"


class ReferenceAssetFormat(str, Enum):
    """
Output format for the auxiliary Reference Asset.
"""

    MARKDOWN = "markdown"
    JSON = "json"


class ComplianceSeverity(str, Enum):
    """
Severity assigned to a compliance rule violation.
"""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class CompilationParams:
    """
User-facing knobs that drive the compile pipeline.

    Threaded through ``compiler.py``, ``dsl/loaders.py``, and the target
        renderers. Frozen and slotted so it cannot be mutated accidentally
        during compilation.
"""

    channel: ChannelType = ChannelType.VOICE
    include_reference_asset: bool = True
    reference_asset_formats: list[ReferenceAssetFormat] = field(
        default_factory=lambda: [ReferenceAssetFormat.MARKDOWN, ReferenceAssetFormat.JSON]
    )
    compliance_profile: str | None = None
    embed_subflows: bool = True
    """When True, all subflow states are rendered inline in the text prompt
    and no separate subflow reference documents are produced."""
    bilingual_templates: bool = False
    """When True, render with ``system_prompt_bilingual.md.j2`` /
    ``system_prompt_bilingual_mini.md.j2`` instead of the standard pair —
    for an agent whose ``SAY`` content is written once and translated at
    output time per a ``[preferred_language]`` slot (e.g. ``manifest.language:
    "es-CO/en-US"``), rather than authored in a single fixed language.
    Manual, not auto-detected from ``manifest.language``: which template an
    agent compiles with is a deliberate compile-time choice, not inferred
    from a string that also has other uses."""


# ---------------------------------------------------------------------------
# Channel profile
# ---------------------------------------------------------------------------


class PolicySectionDefinition(StrictModel):
    """
One row in a channel profile's ``policy_sections`` list.
"""

    name: str
    label: str
    required: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "policy_section.name")

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        return validate_pattern(v, UPPER_CONST_RE, "policy_section.label")


class ChannelProfile(StrictModel):
    """
Channel-specific compilation profile loaded from ``profiles/channels/*.yaml``.
"""

    channel: ChannelType
    display_name: str
    policy_sections: list[PolicySectionDefinition]

    @field_validator("policy_sections")
    @classmethod
    def validate_unique_section_names(cls, v: list[PolicySectionDefinition]) -> list[PolicySectionDefinition]:
        names = [s.name for s in v]
        if len(names) != len(set(names)):
            raise ValueError("channel_profile.policy_sections contains duplicate names.")
        return v


# ---------------------------------------------------------------------------
# Compliance profile
# ---------------------------------------------------------------------------


class ComplianceRuleDefinition(StrictModel):
    """
One rule entry inside a compliance profile.
"""

    rule_id: str
    description: str
    severity: ComplianceSeverity
    check: str  # identifier of the registered checker function

    @field_validator("rule_id")
    @classmethod
    def validate_rule_id(cls, v: str) -> str:
        return validate_pattern(v, RULE_ID_RE, "rule_id")

    @field_validator("check")
    @classmethod
    def validate_check(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "compliance_rule.check")


class ComplianceProfile(StrictModel):
    """
Compliance profile loaded from ``profiles/compliance/*.yaml``.
"""

    profile_id: str
    display_name: str
    rules: list[ComplianceRuleDefinition]

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "profile_id")

    @field_validator("rules")
    @classmethod
    def validate_unique_rule_ids(cls, v: list[ComplianceRuleDefinition]) -> list[ComplianceRuleDefinition]:
        ids = [r.rule_id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("compliance_profile.rules contains duplicate rule_id values.")
        return v


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class ManifestIncludes(StrictModel):
    """
Lists of relative paths referenced from the agent's ``manifest.yaml``.
"""

    memory_slots: list[str] = Field(default_factory=list)
    flow_rules: list[str] = Field(default_factory=list)
    faq_policy: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    tool_contracts: list[str] = Field(default_factory=list)
    handlers: list[str] = Field(default_factory=list)
    faqs: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    terminal_states: list[str] = Field(default_factory=list)

    @field_validator(
        "memory_slots", "flow_rules", "faq_policy", "policies",
        "tool_contracts", "handlers", "faqs", "states", "terminal_states",
    )
    @classmethod
    def validate_paths(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Each include path must be a non-empty string.")
        return v


class SubflowInstanceRef(StrictModel):
    """
Manifest entry that instantiates a subflow template with optional params.
"""

    template: str
    instance_id: str
    namespace: str | None = None
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "subflow_instance.instance_id")

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_pattern(v, LOWER_SNAKE_RE, "subflow_instance.namespace")

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        if not v:
            raise ValueError("subflow_instance.template must not be empty.")
        return v

    @model_validator(mode="after")
    def set_default_namespace(self) -> SubflowInstanceRef:
        if self.namespace is None:
            # Default the namespace to the instance_id so consumers can rely
            # on a non-null value when generating namespaced state/slot names.
            self.namespace = self.instance_id
        return self


class ManifestConfig(StrictModel):
    """
Top-level config loaded from each agent's ``manifest.yaml``.

    ``channel`` is a ``CompilationParam`` (CLI-level choice), not part of
        the manifest; the output directory is the convention ``dist/{agent_id}/``.
"""

    agent_id: str
    version: str = "1.0.0"
    language: str
    start_at: str
    dynamic_state_slots: list[str] = Field(default_factory=lambda: ["current_state", "resume_state"])
    tools: list[str] = Field(default_factory=list)
    """Every tool this agent is authorized to call — the single source of
    truth (moved 2026-09-16 from a per-agent ``tools.yaml`` plus
    ``includes.tools`` shared fragments, both now gone: a tool name isn't
    language- or context-specific, so splitting it across files bought
    nothing). Each name must also have a matching entry in the agent's
    merged ``tool_contracts``."""
    tool_argument_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    """Per-agent fixed values for specific tool arguments — ``{tool_name:
    {input_name: value}}``. For an argument the agent must never decide
    (a rate, a fixed duration, a language code), declare it here instead
    of leaving it to the LLM to reproduce correctly on every call; the
    value is typically a ``<CONSTANT>`` reference resolved from this
    agent's own ``constants.yaml``, but a literal is legal too. Every
    ``tool_name`` must be in ``tools`` above, and every ``input_name``
    must be a declared input of that tool's contract — both checked by
    ``dsl.validators._validate_tool_argument_overrides`` once contracts
    are loaded (this model alone doesn't know about them). Belongs on the
    manifest, not the shared ``ToolContract``, because the same
    contract's fixed-vs-agent-decided split can differ per agent."""
    includes: ManifestIncludes = Field(default_factory=ManifestIncludes)
    subflow_instances: list[SubflowInstanceRef] = Field(default_factory=list)
    session_timeout_minutes: int | None = None
    """LangGraph target only — the text target ignores this. ``None``
    (default) means a session never goes stale. When set, a gap since the
    contact's last message longer than this many minutes makes the session
    resolver treat the next inbound message as a new conversation (full
    reset) instead of resuming mid-flow."""

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "agent_id")

    @field_validator("start_at")
    @classmethod
    def validate_start_at(cls, v: str) -> str:
        return validate_pattern(v, UPPER_ID_RE, "manifest.start_at")

    @field_validator("tool_argument_overrides")
    @classmethod
    def validate_tool_argument_overrides(cls, v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for tool_name, args in v.items():
            validate_pattern(tool_name, LOWER_SNAKE_RE, "tool_argument_overrides tool name")
            if not args:
                raise ValueError(f"tool_argument_overrides[{tool_name!r}] must not be empty.")
            for input_name, value in args.items():
                validate_pattern(input_name, DOTTED_LOWER_SNAKE_RE, "tool_argument_overrides input name")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"tool_argument_overrides[{tool_name!r}][{input_name!r}] must be a non-empty string."
                    )
        return v

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for item in v:
            validate_pattern(item, LOWER_SNAKE_RE, "manifest.tools")
            if item in seen:
                raise ValueError(f"Duplicate tool name in manifest.tools: {item!r}")
            seen.add(item)
        return v

    @field_validator("dynamic_state_slots")
    @classmethod
    def validate_dynamic_state_slots(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("dynamic_state_slots must not be empty.")
        for item in v:
            validate_pattern(item, LOWER_SNAKE_RE, "dynamic_state_slot")
        return v

    @field_validator("subflow_instances")
    @classmethod
    def validate_subflow_instances(cls, v: list[SubflowInstanceRef]) -> list[SubflowInstanceRef]:
        seen: set[str] = set()
        for item in v:
            if item.instance_id in seen:
                raise ValueError(f"Duplicate instance_id in manifest.subflow_instances: {item.instance_id!r}")
            seen.add(item.instance_id)
        return v


# ---------------------------------------------------------------------------
# Static agent content
# ---------------------------------------------------------------------------


class ConstantItem(StrictModel):
    """
One row in ``constants.yaml``.
"""

    name: str
    description: str
    value: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, UPPER_CONST_RE, "constant.name")


class ConstantsFile(StrictModel):
    """
Schema for ``constants.yaml``.
"""

    constants: list[ConstantItem]

    @field_validator("constants")
    @classmethod
    def validate_constants(cls, v: list[ConstantItem]) -> list[ConstantItem]:
        if not v:
            raise ValueError("constants must not be empty.")
        return v


class InputVariable(StrictModel):
    """
Runtime variable injected by the platform at execution time.
"""

    name: str
    description: str
    allowed_values: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, DOTTED_LOWER_SNAKE_RE, "input_variable.name")


class InputVariablesFile(StrictModel):
    """
Schema for ``input_variables.yaml``.
"""

    input_variables: list[InputVariable]

    @field_validator("input_variables")
    @classmethod
    def validate_input_variables(cls, v: list[InputVariable]) -> list[InputVariable]:
        if not v:
            raise ValueError("input_variables must not be empty.")
        return v


class ToolContractField(StrictModel):
    """
Input or output field declared in a tool contract.

    ``type_expr`` reuses the exact same canonical type grammar as
        ``CaptureField.type_expr`` (``dsl/capture_types.py``) — deliberately:
        a tool argument the agent must fill in, or a tool result the agent
        captures, is the same kind of "what shape is this value" question
        either way, so it gets the same enum construct (``Literal[a, b, c]``)
        for a field that can only return one of a fixed set of categories,
        the same semantic scalars (``email``, ``phone_number``, ...), and the
        same ``list[T]``.

        Unlike ``CaptureField.type_expr``, ``type_expr`` here is **optional**
        (``None`` by default) rather than required — retrofitting a type onto
        every field of every existing tool contract is a real-content
        migration effort, not a mechanical one, so it isn't forced in one
        step. ``dsl/validators.py``'s ``_validate_tool_contract_fields``
        warns on every field still missing one (``TOOL_CONTRACT_FIELD_UNTYPED``)
        but only *errors* when a declared ``type_expr`` is actually invalid —
        same asymmetry as ``eval: "llm"`` (§6 of docs/DSL_REFERENCE.md):
        silence is flagged, a wrong answer is rejected.
"""

    name: str
    required: bool = True
    description: str
    type_expr: str | None = None
    examples: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, DOTTED_LOWER_SNAKE_RE, "tool_contract_field.name")

    @field_validator("type_expr")
    @classmethod
    def validate_type_expr(cls, v: str | None) -> str | None:
        if v is None:
            return v
        result = classify_type_expr(v)
        if result.category == "canonical":
            return v
        if result.category == "synonym":
            return result.canonical_suggestion  # type: ignore[return-value]
        if result.category == "needs_item_type":
            raise ValueError(
                f"tool_contract_field.type_expr {v!r} is a bare 'list' with no item type — "
                f"write 'list[str]', 'list[Literal[...]]', etc."
            )
        raise ValueError(f"tool_contract_field.type_expr {v!r} is not a recognized type: {result.reason}")

    @field_validator("examples")
    @classmethod
    def validate_examples(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "tool_contract_field.examples", allow_empty=True)


class ToolContract(StrictModel):
    """
A complete contract for one tool — agent-facing interface only.

    Deliberately holds no endpoint/transport information (URL, method,
        auth) — that mechanics lives entirely in ``runtime/tool_executor.py``,
        resolved uniformly from ``name`` at call time. See DESIGN_PATTERNS.md
        P05 and CLAUDE.md §5.2.4.
"""

    name: str
    description: str
    inputs: list[ToolContractField] = Field(default_factory=list)
    outputs: list[ToolContractField] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "tool_contract.name")

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "tool_contract.notes", allow_empty=True)


class ToolContractsFragmentFile(StrictModel):
    """
Schema for fragments of tool contract declarations.
"""

    tool_contracts: list[ToolContract] = Field(default_factory=list)


class ToolContractsFile(ToolContractsFragmentFile):
    """
Schema for the merged list of tool contracts — must be non-empty.
"""
    @model_validator(mode="after")
    def validate_contracts(self) -> ToolContractsFile:
        if not self.tool_contracts:
            raise ValueError("tool_contracts must not be empty.")
        return self


class MemorySlot(StrictModel):
    """
A typed memory slot used during the conversation.
"""

    name: str
    description: str
    kind: Literal[
        "dynamic_state", "captured", "derived", "control", "user_data",
        "tool_output", "retry_counter", "other",
    ] = "other"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "memory_slot.name")


class MemorySlotsFile(StrictModel):
    """
Schema for ``memory_slots.yaml``.
"""

    memory_slots: list[MemorySlot] = Field(default_factory=list)


class IdentityFile(StrictModel):
    """
Schema for ``identity.yaml``.
"""

    identity: list[str]

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "identity", allow_empty=False)


class ObjectivesFile(StrictModel):
    """
Schema for ``objectives.yaml``.
"""

    primary_objective: list[str]
    secondary_objectives: list[str]
    success_alternatives: list[str]

    @field_validator("primary_objective", "secondary_objectives", "success_alternatives")
    @classmethod
    def validate_sections(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "objectives section", allow_empty=False)


class SummaryServiceItem(StrictModel):
    """
One entry in ``context.summary_services_library``.
"""

    key: str
    procedure: str
    text: str

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        return validate_pattern(v, UPPER_ID_RE, "summary_service.key")

    @field_validator("procedure")
    @classmethod
    def validate_procedure(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "summary_service.procedure")


class ApprovedProcessStep(StrictModel):
    """
One step in ``context.approved_process_steps``.
"""

    title: str
    text: str


class ContextFile(StrictModel):
    """
Schema for ``context.yaml`` — purely static information about company/services.
"""
    company_context: list[str]
    approved_services: list[str]
    summary_services_library: list[SummaryServiceItem]
    approved_process_intro: str
    approved_process_steps: list[ApprovedProcessStep]
    support_and_trust: list[str]

    @field_validator("company_context", "approved_services", "support_and_trust")
    @classmethod
    def validate_context_lists(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "context section", allow_empty=False)

    @field_validator("summary_services_library")
    @classmethod
    def validate_summaries(cls, v: list[SummaryServiceItem]) -> list[SummaryServiceItem]:
        if not v:
            raise ValueError("summary_services_library must not be empty.")
        return v

    @field_validator("approved_process_steps")
    @classmethod
    def validate_process_steps(cls, v: list[ApprovedProcessStep]) -> list[ApprovedProcessStep]:
        if not v:
            raise ValueError("approved_process_steps must not be empty.")
        return v


# ---------------------------------------------------------------------------
# Policies (dynamic — sections come from the channel profile)
# ---------------------------------------------------------------------------


class PoliciesFragmentFile(StrictModel):
    """
Schema for a policies YAML fragment.

    Section names are dynamic — the loader validates them at merge time
        against the active channel profile. Each section value must be a list
        of non-empty strings.
"""

    model_config = ConfigDict(extra="allow", validate_assignment=True, str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def accept_dynamic_sections(cls, data: Any) -> dict[str, Any]:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("A policies file must be a YAML mapping.")
        for key, value in data.items():
            if not isinstance(value, list):
                raise ValueError(f"Policy section {key!r} must be a list.")
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f"Section {key!r} contains an empty or invalid string.")
        return data

    def get_section(self, name: str) -> list[str]:
        """
        Return the lines of a section, or an empty list if absent.
        """
        value = getattr(self, name, None)
        return list(value) if value else []

    def all_sections(self) -> dict[str, list[str]]:
        """
        Return all sections as a dict, including dynamically declared ones.
        """
        return self.model_dump()


class PoliciesFile(PoliciesFragmentFile):
    """
Final merged policies after channel-profile validation.

    Same shape as ``PoliciesFragmentFile``; subclassed for semantic clarity
        so consumers can type-hint against ``PoliciesFile`` to signal they
        expect the merged result rather than a raw fragment.
"""


# ---------------------------------------------------------------------------
# Flow rules and FAQ policy
# ---------------------------------------------------------------------------


class FlowRulesFile(StrictModel):
    """
Schema for a ``flow_rules.yaml`` fragment.
"""

    flow_rules: list[str]

    @field_validator("flow_rules")
    @classmethod
    def validate_flow_rules(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "flow_rules", allow_empty=False)


class FAQPolicyFile(StrictModel):
    """
Schema for a ``faq_policy.yaml`` fragment.
"""

    faq_policy: list[str]

    @field_validator("faq_policy")
    @classmethod
    def validate_faq_policy(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "faq_policy", allow_empty=False)


# ---------------------------------------------------------------------------
# Flow objects (handlers, FAQs, states)
# ---------------------------------------------------------------------------


class CaptureField(StrictModel):
    """
One slot to capture from a flow object.

    ``type_expr`` is validated against the canonical type grammar
        (``dsl.capture_types.classify_type_expr``) rather than accepted as
        free text: the LLM extracting the value, and any author reading the
        compiled prompt, must see exactly one unambiguous type — ``str``,
        ``bool``, ``int``, a registered semantic scalar (``email``,
        ``phone_number``, ...), an enum (``Literal[a, b, c]``), or
        ``list[T]`` of one of those. A non-canonical but recognized synonym
        (``string``, ``integer``, ``boolean``, ``text``, ``number``) is
        silently normalized to its canonical spelling rather than rejected,
        since it carries no ambiguity of its own. Anything else — free prose,
        a bare unparametrized ``list``, a made-up type name — is a hard
        validation error at load time, not a runtime surprise.
"""

    slot: str
    type_expr: str

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "capture.slot")

    @field_validator("type_expr")
    @classmethod
    def validate_type_expr(cls, v: str) -> str:
        result = classify_type_expr(v)
        if result.category == "canonical":
            return v
        if result.category == "synonym":
            return result.canonical_suggestion  # type: ignore[return-value]
        if result.category == "needs_item_type":
            raise ValueError(
                f"capture.type_expr {v!r} is a bare 'list' with no item type — "
                f"write 'list[str]', 'list[Literal[...]]', etc."
            )
        raise ValueError(f"capture.type_expr {v!r} is not a recognized type: {result.reason}")


class FlowObjectBase(StrictModel):
    """
Common fields and semantics shared by handlers and states.

    ``say_verbatim`` controls how a renderer treats SAY blocks: ``False`` →
        paraphrasable, ``True`` → literal (never paraphrased, never re-languaged
        by the LangGraph runtime). ``eval``'s mechanical-parseability
        requirement (``dsl/condition_grammar.py`` + ``dsl/validators.py``) is
        checked for every agent regardless of target — the text-prompt
        renderer doesn't read ``eval`` to change its own output, but a
        ``route``/``fallback`` line it prints as literal text is exactly as
        much of a hallucination risk there as it would be as an LLM-judged
        LangGraph edge, so the grammar is enforced once, for both.
"""

    type: NODE_TYPE
    goal: list[str] = Field(default_factory=list)
    do: list[str] = Field(default_factory=list)
    say: list[str] = Field(default_factory=list)
    say_verbatim: bool = False
    wait: YES_NO | None = None
    capture: list[CaptureField] = Field(default_factory=list)
    store: list[str] = Field(default_factory=list)
    route: list[str] = Field(default_factory=list)
    faq_resume_to: str | None = None
    fallback: list[str] = Field(default_factory=list)
    execute: str | None = None
    final: YES_NO | None = None
    eval: Literal["code", "llm"] = "code"
    """``"code"`` (default) requires every ``route``/``fallback`` line to be
    mechanically parseable (``dsl/condition_grammar.py``); ``"llm"`` is the
    explicit escape hatch, always flagged with an ``EVAL_LLM_EXPLICIT``
    warning. There used to be a third value, ``"auto"`` — removed
    2026-09-16 because it was a pure synonym for ``"code"`` in every check
    that read ``eval`` (see SPEC.md's decision log): a token with no
    behavioral difference from another token is itself a small
    interpretive-surface bug, the same category of problem this field
    exists to close on ``route``/``fallback`` content."""

    @field_validator("goal", "do", "say", "store", "route", "fallback")
    @classmethod
    def validate_line_lists(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "flow object section", allow_empty=True)

    @field_validator("faq_resume_to")
    @classmethod
    def validate_resume_target(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # "@instance.export" aliases are allowed here; resolved before graph validation.
        if v.startswith("@"):
            return v
        return validate_pattern(v, UPPER_ID_RE, "faq_resume_to")

    @field_validator("execute")
    @classmethod
    def validate_execute(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_pattern(v, LOWER_SNAKE_RE, "execute")

    @model_validator(mode="after")
    def validate_semantics(self) -> FlowObjectBase:
        if self.type == "message":
            if self.wait != "no":
                raise ValueError("type=message objects must have wait='no'.")
            if not self.say:
                raise ValueError("type=message objects must have SAY.")
            if self.execute is not None:
                raise ValueError("type=message objects must not have EXECUTE.")
            if self.final == "yes":
                raise ValueError("type=message objects must not have final='yes'.")
        elif self.type == "question":
            if self.wait != "yes":
                raise ValueError("type=question objects must have wait='yes'.")
            if not self.say:
                raise ValueError("type=question objects must have SAY.")
            if self.execute is not None:
                raise ValueError("type=question objects must not have EXECUTE.")
            if self.final == "yes":
                raise ValueError("type=question objects must not have final='yes'.")
        elif self.type == "decision":
            if self.wait != "no":
                raise ValueError("type=decision objects must have wait='no'.")
            if self.say:
                raise ValueError("type=decision objects must not have SAY.")
            if self.execute is not None:
                raise ValueError("type=decision objects must not have EXECUTE.")
            if self.final == "yes":
                raise ValueError("type=decision objects must not have final='yes'.")
        elif self.type == "action":
            if self.wait != "no":
                raise ValueError("type=action objects must have wait='no'.")
            if not self.execute:
                raise ValueError("type=action objects must declare EXECUTE.")
            if self.say:
                raise ValueError("type=action objects must not have SAY.")
            if self.final == "yes":
                raise ValueError("type=action objects must not have final='yes'.")
        elif self.type == "registration":
            if self.wait != "no":
                raise ValueError("type=registration objects must have wait='no'.")
            if self.say:
                raise ValueError("type=registration objects must not have SAY.")
            if self.execute is not None:
                raise ValueError("type=registration objects must not have EXECUTE.")
            if self.final == "yes":
                raise ValueError("type=registration objects must not have final='yes'.")
        elif self.type == "terminal":
            if self.wait != "no":
                raise ValueError("type=terminal objects must have wait='no'.")
            if self.final != "yes":
                raise ValueError("type=terminal objects must have final='yes'.")
        elif self.type == "start":
            if self.wait != "no":
                raise ValueError("type=start objects must have wait='no'.")
            if self.final == "yes":
                raise ValueError("type=start objects must not have final='yes'.")
            if self.say:
                raise ValueError("type=start objects must not have SAY.")
            if self.execute is not None:
                raise ValueError("type=start objects must not have EXECUTE.")
        elif self.type == "subflow_change":
            if self.wait != "no":
                raise ValueError("type=subflow_change objects must have wait='no'.")
            if self.final == "yes":
                raise ValueError("type=subflow_change objects must not have final='yes'.")
            if self.say:
                raise ValueError("type=subflow_change objects must not have SAY.")
            if self.execute is not None:
                raise ValueError("type=subflow_change objects must not have EXECUTE.")

        if self.type not in ("terminal",) and not self.route and not self.fallback:
            raise ValueError("Non-terminal objects must have ROUTE or FALLBACK.")

        if len(self.fallback) > 1:
            raise ValueError(
                "FALLBACK must be a single unconditional 'GO_TO: X' line — it is the last-resort "
                "catch-all, not a second place for branching logic. A conditional check belongs in "
                "ROUTE (evaluated first, top to bottom); FALLBACK only ever runs when nothing in "
                "ROUTE matched."
            )
        if self.fallback and self.fallback[0].strip().upper().startswith("IF "):
            raise ValueError(
                f"FALLBACK must be an unconditional 'GO_TO: X' line, not a conditional one: "
                f"{self.fallback[0]!r}. Move this 'IF ... -> GO_TO: ...' line into ROUTE instead."
            )

        return self


class HandlerModel(FlowObjectBase):
    """
A global interrupt available from any active state.
"""

    handler_id: str
    trigger: list[str] = Field(default_factory=list)
    disabled_in: list[str] = Field(default_factory=list)

    @field_validator("handler_id")
    @classmethod
    def validate_handler_id(cls, v: str) -> str:
        return validate_pattern(v, UPPER_ID_RE, "handler_id")

    @field_validator("trigger")
    @classmethod
    def validate_trigger(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "handler.trigger", allow_empty=False)

    @field_validator("disabled_in")
    @classmethod
    def validate_disabled_in(cls, v: list[str]) -> list[str]:
        """Subflow ids (`SC`) or namespaced state ids (`SC__SC_HOURS`) where the handler is switched off."""
        return validate_non_empty_lines(v, "handler.disabled_in", allow_empty=True)


class HandlersFile(StrictModel):
    """
Schema for handler files (local or shared).
"""

    handlers: list[HandlerModel]

    @field_validator("handlers")
    @classmethod
    def validate_handlers(cls, v: list[HandlerModel]) -> list[HandlerModel]:
        if not v:
            raise ValueError("handlers must not be empty.")
        return v


class FAQModel(StrictModel):
    """
An approved FAQ card — semantic match phrases plus a SAY payload.

    ``resume_to`` is an optional routing hint (e.g. ``[current_state]``).
        Unlike ``faq_resume_to`` on flow objects it is not validated against
        ``UPPER_ID_RE`` so it can hold slot-style dynamic values.
"""

    faq_id: str
    type: Literal["message"]
    match: list[str]
    say: list[str]
    say_verbatim: bool = False
    resume_to: str | None = None

    @field_validator("faq_id")
    @classmethod
    def validate_faq_id(cls, v: str) -> str:
        return validate_pattern(v, UPPER_ID_RE, "faq_id")

    @field_validator("match")
    @classmethod
    def validate_match(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "faq.match", allow_empty=False)

    @field_validator("say")
    @classmethod
    def validate_say(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "faq.say", allow_empty=False)

    @field_validator("resume_to")
    @classmethod
    def validate_resume_to(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("faq.resume_to must not be an empty string.")
        return v


class FAQsFile(StrictModel):
    """
Schema for FAQ catalog files.
"""

    faqs: list[FAQModel]

    @field_validator("faqs")
    @classmethod
    def validate_faqs(cls, v: list[FAQModel]) -> list[FAQModel]:
        if not v:
            raise ValueError("faqs must not be empty.")
        return v


class StateModel(FlowObjectBase):
    """
A node in the main conversational state machine.
"""

    state_id: str

    @field_validator("state_id")
    @classmethod
    def validate_state_id(cls, v: str) -> str:
        return validate_pattern(v, UPPER_ID_RE, "state_id")


class StatesFile(StrictModel):
    """
Schema for non-terminal state files.
"""

    states: list[StateModel]

    @field_validator("states")
    @classmethod
    def validate_states(cls, v: list[StateModel]) -> list[StateModel]:
        if not v:
            raise ValueError("states must not be empty.")
        return v


class TerminalStatesFile(StrictModel):
    """
Schema for terminal state files. Every entry must have type=terminal and final=yes.
"""

    terminal_states: list[StateModel]

    @field_validator("terminal_states")
    @classmethod
    def validate_terminal_states(cls, v: list[StateModel]) -> list[StateModel]:
        if not v:
            raise ValueError("terminal_states must not be empty.")
        for state in v:
            if state.type != "terminal":
                raise ValueError(
                    f"terminal_states file may only contain type=terminal. "
                    f"Found {state.state_id} with type={state.type!r}."
                )
            if state.final != "yes":
                raise ValueError(f"Terminal state {state.state_id} must have final='yes'.")
        return v


# ---------------------------------------------------------------------------
# Subflow templates
# ---------------------------------------------------------------------------


class TemplateParamDefinition(StrictModel):
    """
Definition of a parameter consumed by a subflow template.
"""

    name: str
    description: str = ""
    required: bool = True
    default: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "template_param.name")


class SubflowExports(StrictModel):
    """
Maps export aliases used by other subflows to local state ids and slot names.
"""

    states: dict[str, str] = Field(default_factory=dict)
    slots: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_exports(self) -> SubflowExports:
        for key, value in self.states.items():
            validate_pattern(key, LOWER_SNAKE_RE, "subflow_exports.states key")
            validate_pattern(value, UPPER_ID_RE, "subflow_exports.states value")
        for key, value in self.slots.items():
            validate_pattern(key, LOWER_SNAKE_RE, "subflow_exports.slots key")
            validate_pattern(value, LOWER_SNAKE_RE, "subflow_exports.slots value")
        return self


class SubflowTemplate(StrictModel):
    """
A reusable subflow template, instantiated from the manifest with parameters.
"""

    template_id: str
    description: str
    params: list[TemplateParamDefinition] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    required_constants: list[str] = Field(default_factory=list)

    # Slots declared here are namespaced per instance during instantiation.
    local_memory_slots: list[MemorySlot] = Field(default_factory=list)

    flow_rules: list[str] = Field(default_factory=list)
    faq_policy: list[str] = Field(default_factory=list)
    handlers: list[HandlerModel] = Field(default_factory=list)
    faqs: list[FAQModel] = Field(default_factory=list)
    states: list[StateModel] = Field(default_factory=list)
    terminal_states: list[StateModel] = Field(default_factory=list)
    exports: SubflowExports = Field(default_factory=SubflowExports)

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        return validate_pattern(v, LOWER_SNAKE_RE, "subflow_template.template_id")

    @field_validator("required_tools")
    @classmethod
    def validate_required_tools(cls, v: list[str]) -> list[str]:
        for item in v:
            validate_pattern(item, LOWER_SNAKE_RE, "subflow_template.required_tool")
        return v

    @field_validator("required_constants")
    @classmethod
    def validate_required_constants(cls, v: list[str]) -> list[str]:
        for item in v:
            validate_pattern(item, UPPER_CONST_RE, "subflow_template.required_constant")
        return v

    @field_validator("flow_rules", "faq_policy")
    @classmethod
    def validate_text_lists(cls, v: list[str]) -> list[str]:
        return validate_non_empty_lines(v, "subflow_template text list", allow_empty=True)

    @model_validator(mode="after")
    def validate_subflow_template(self) -> SubflowTemplate:
        param_names: set[str] = set()
        for item in self.params:
            if item.name in param_names:
                raise ValueError(f"Duplicate parameter in template {self.template_id!r}: {item.name!r}")
            param_names.add(item.name)

        has_content = any(
            [
                self.local_memory_slots, self.flow_rules, self.faq_policy,
                self.handlers, self.faqs, self.states, self.terminal_states,
            ]
        )
        if not has_content:
            raise ValueError(f"Subflow template {self.template_id!r} contributes no content.")

        local_state_ids = {s.state_id for s in self.states} | {s.state_id for s in self.terminal_states}
        for export_name, state_id in self.exports.states.items():
            if state_id not in local_state_ids:
                raise ValueError(
                    f"Export state {export_name!r} of template {self.template_id!r} points to "
                    f"{state_id!r}, but that state does not exist inside the template."
                )

        for export_name, slot_name in self.exports.slots.items():
            if not slot_name:
                raise ValueError(f"Export slot {export_name!r} of template {self.template_id!r} is invalid.")

        for state in self.terminal_states:
            if state.type != "terminal":
                raise ValueError(
                    f"Subflow template {self.template_id!r} has {state.state_id!r} in "
                    f"terminal_states but its type is not terminal."
                )
            if state.final != "yes":
                raise ValueError(
                    f"Terminal state {state.state_id!r} of template {self.template_id!r} must have final='yes'."
                )

        return self


# ---------------------------------------------------------------------------
# Aggregate spec and pipeline outputs
# ---------------------------------------------------------------------------


class AgentSpec(StrictModel):
    """
The fully merged agent specification fed into the rest of the pipeline.

    Built by ``dsl.loaders.load_agent_spec`` from the manifest, shared
        includes and instantiated subflows. Carries provenance metadata
        (``object_sources``) and subflow export maps so downstream stages can
        surface helpful diagnostics.
"""

    manifest: ManifestConfig

    constants: list[ConstantItem]
    input_variables: list[InputVariable]
    tools: list[str]
    tool_contracts: list[ToolContract]
    tool_argument_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    """Copied from ``manifest.tool_argument_overrides`` for convenience —
    same duplication pattern as ``tools`` above."""
    memory_slots: list[MemorySlot]
    identity: list[str]
    objectives: ObjectivesFile
    context: ContextFile
    policies: PoliciesFile

    flow_rules: list[str]
    faq_policy: list[str]
    handlers: list[HandlerModel]
    faqs: list[FAQModel]
    states: list[StateModel]
    terminal_states: list[StateModel]

    object_sources: dict[str, list[str]] = Field(default_factory=dict)
    instance_state_exports: dict[str, dict[str, str]] = Field(default_factory=dict)
    instance_slot_exports: dict[str, dict[str, str]] = Field(default_factory=dict)

    @property
    def all_state_ids(self) -> list[str]:
        return [s.state_id for s in self.states] + [s.state_id for s in self.terminal_states]

    @property
    def main_state_ids(self) -> list[str]:
        return [s.state_id for s in self.states]


@dataclass(frozen=True, slots=True)
class CompilationStats:
    """
Lightweight numerical summary of a compilation run.
"""

    total_states: int
    total_handlers: int
    total_faqs: int
    total_subflows_instantiated: int
    duplicate_rules_found: int
    estimated_text_prompt_chars: int
    estimated_reference_asset_chars: int
    estimated_subflows_chars: int
    estimated_text_prompt_mini_chars: int | None
    estimated_subflows_mini_chars: int


@dataclass(frozen=True, slots=True)
class CompilationOutputs:
    """
Bundle of every artifact produced by ``compile_agent``.

    ``text_prompt_mini`` / ``subflow_documents_mini`` are the compact-
        notation companions to ``text_prompt`` / ``subflow_documents`` (see
        ``targets/text/renderer.py``'s mini renderers). ``text_prompt_mini`` is
        ``None`` when the agent's channel has no mini template companion —
        mini rendering is skipped rather than failing the whole compile.

        The ``validation_report``, ``deduplication_report``, and
        ``orphan_report`` annotations are forward references resolved by the
        type checker via ``TYPE_CHECKING``; the runtime classes live in
        ``dsl/validators.py`` and ``dsl/deduplicator.py`` and are not imported
        here to avoid a cycle. All three combine into one
        ``compilation_report.md`` (``dsl/compilation_report.py``) rather than
        three separate files, each also usable standalone via its own
        ``to_markdown()``.
"""

    agent_id: str
    text_prompt: str
    subflow_documents: dict[str, str]
    text_prompt_mini: str | None
    subflow_documents_mini: dict[str, str]
    reference_asset_markdown: str | None
    reference_asset_json: dict[str, Any] | None
    validation_report: ValidationReport
    deduplication_report: DeduplicationReport
    orphan_report: OrphanStateReport
    stats: CompilationStats
