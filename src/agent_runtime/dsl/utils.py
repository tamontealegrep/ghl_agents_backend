"""
Regex-driven text helpers and AgentSpec iteration utilities.

    This module concentrates every regex used by the compiler:

    - Placeholder extraction: variables ``{{name}}``, constants ``<NAME>``,
      slots ``[name]``.
    - ``GO_TO`` target extraction (static state ids, dynamic slot targets,
      alias tokens).
    - Assignment detection: ``[slot] = ...`` and ``increment [slot] by 1``.
    - Subflow template parameters ``<<param>>``.
    - Subflow alias tokens: ``@instance.export`` and ``@slot(instance.export)``.

    It also exposes the namespace builders used by the loader when
    instantiating subflow templates, plus iteration helpers used by the
    validators and renderers to walk the ``AgentSpec``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_runtime.dsl.schemas import AgentSpec, FlowObjectBase, ToolContract


# ---------------------------------------------------------------------------
# Compiled regular expressions
# ---------------------------------------------------------------------------

VAR_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_\.]*)\}\}")
CONST_RE = re.compile(r"<([A-Z][A-Z0-9_]*)>")
SLOT_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]")

GOTO_RE = re.compile(
    r"GO_TO:\s*(\[[a-zA-Z_][a-zA-Z0-9_]*\]|[A-Z][A-Z0-9_]*|@[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)"
)
ASSIGN_SLOT_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s*=")
INCREMENT_SLOT_RE = re.compile(r"increment\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+by\s+1", re.IGNORECASE)

PARAM_RE = re.compile(r"<<([a-z][a-z0-9_]*)>>")
SLOT_ALIAS_RE = re.compile(r"@slot\(([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\)")
STATE_ALIAS_TOKEN_RE = re.compile(r"@([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)")
GOTO_ALIAS_RE = re.compile(r"(GO_TO:\s*)(@[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def extract_variables(text: str) -> set[str]:
    """Return all ``{{name}}`` runtime variable references in ``text``.
    """
    return set(VAR_RE.findall(text))


def extract_constants(text: str) -> set[str]:
    """Return all ``<NAME>`` constant references in ``text``.
    """
    return set(CONST_RE.findall(text))


def extract_slots(text: str) -> set[str]:
    """Return all ``[slot]`` memory-slot references in ``text``.
    """
    return set(SLOT_RE.findall(text))


def extract_goto_targets(text: str) -> list[str]:
    """Return all ``GO_TO`` targets found in ``text``.

    Targets can be:

    - Static state ids: ``GO_TO: STATE_ID``.
    - Dynamic slot targets: ``GO_TO: [slot_name]``.
    - Subflow alias tokens: ``GO_TO: @instance.export``.

    Order is preserved for downstream diagnostics.
    """
    return GOTO_RE.findall(text)


def extract_assignment_slots(text: str) -> set[str]:
    """Return all slot names that ``text`` writes to.

    Recognized assignment forms:

    - ``[slot] = ...``
    - ``increment [slot] by 1`` (case-insensitive).
    """
    return set(ASSIGN_SLOT_RE.findall(text)) | set(INCREMENT_SLOT_RE.findall(text))


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_dynamic_target(target: str) -> bool:
    """Return ``True`` if ``target`` is a dynamic GO_TO of the form ``[slot]``.
    """
    return target.startswith("[") and target.endswith("]")


def dynamic_target_slot_name(target: str) -> str:
    """Return the slot name inside a dynamic target.

    ``"[foo]" -> "foo"``.
    """
    return target[1:-1]


def has_unresolved_slot_alias(text: str) -> bool:
    """Return ``True`` if ``text`` still contains an ``@slot(instance.export)`` alias.
    """
    return bool(SLOT_ALIAS_RE.search(text))


def has_unresolved_state_alias_target(text: str) -> bool:
    """Return ``True`` if ``text`` still contains an unresolved ``GO_TO: @...`` alias.
    """
    return "GO_TO: @" in text


# ---------------------------------------------------------------------------
# Normalization and small generic helpers
# ---------------------------------------------------------------------------


def normalize_phrase(text: str) -> str:
    """Return ``text`` lowercased with whitespace collapsed to single spaces.
    """
    return re.sub(r"\s+", " ", text.strip().lower())


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Return ``items`` with duplicates removed, preserving first-occurrence order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Namespacing for subflow instances
# ---------------------------------------------------------------------------


def namespace_state_id(namespace: str, local_id: str) -> str:
    """Build the global state id of a templated state (``NAMESPACE__local_id``).
    """
    return f"{namespace.upper()}__{local_id}"


def namespace_slot_name(namespace: str, local_slot_name: str) -> str:
    """Build the global slot name for a templated memory slot (``namespace__local``).
    """
    return f"{namespace.lower()}__{local_slot_name}"


# ---------------------------------------------------------------------------
# Parameter and alias substitution
# ---------------------------------------------------------------------------


def substitute_params(text: str, params: dict[str, str]) -> str:
    """Replace every ``<<param>>`` in ``text`` with its value from ``params``.

    Raises ``ValueError`` if a parameter referenced in the text is missing
    from the ``params`` dict — substitution is strict by design.
    """

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in params:
            raise ValueError(f"Missing required parameter <<{key}>>")
        return params[key]

    return PARAM_RE.sub(repl, text)


def rewrite_local_slots_in_text(text: str, local_slot_map: dict[str, str]) -> str:
    """Rewrite ``[slot]`` references in ``text`` using ``local_slot_map``.

    Slots not present in the map are left unchanged because they refer to
    globally declared slots in the agent's ``memory_slots.yaml``.
    """

    def repl(match: re.Match[str]) -> str:
        slot_name = match.group(1)
        resolved = local_slot_map.get(slot_name, slot_name)
        return f"[{resolved}]"

    return SLOT_RE.sub(repl, text)


def rewrite_local_goto_targets(text: str, local_state_map: dict[str, str]) -> str:
    """Rewrite ``GO_TO: <ID>`` targets in ``text`` to their namespaced ids.

    Only static state-id targets are rewritten. Dynamic targets ``[slot]``
    and alias targets ``@instance.export`` are left untouched.
    """

    def repl(match: re.Match[str]) -> str:
        original_target = match.group(1)
        if original_target in local_state_map:
            return f"GO_TO: {local_state_map[original_target]}"
        return f"GO_TO: {original_target}"

    return GOTO_RE.sub(repl, text)


def resolve_slot_aliases(text: str, flat_slot_export_map: dict[str, str]) -> str:
    """Replace ``@slot(instance.export)`` aliases in ``text`` with ``[slot_name]``.

    Raises ``ValueError`` for unresolved aliases — every alias must resolve
    to a real exported slot.
    """

    def repl(match: re.Match[str]) -> str:
        instance_id = match.group(1)
        export_name = match.group(2)
        key = f"{instance_id}.{export_name}"
        if key not in flat_slot_export_map:
            raise ValueError(f"Unresolved slot alias: @slot({key})")
        return f"[{flat_slot_export_map[key]}]"

    return SLOT_ALIAS_RE.sub(repl, text)


def resolve_state_alias_targets(text: str, flat_state_export_map: dict[str, str]) -> str:
    """Replace ``GO_TO: @instance.export`` aliases with concrete state ids.
    """

    def repl(match: re.Match[str]) -> str:
        prefix = match.group(1)
        alias_token = match.group(2)
        key = alias_token[1:]  # remove leading @
        if key not in flat_state_export_map:
            raise ValueError(f"Unresolved state alias: {alias_token}")
        return f"{prefix}{flat_state_export_map[key]}"

    return GOTO_ALIAS_RE.sub(repl, text)


def resolve_state_alias_value(value: str, flat_state_export_map: dict[str, str]) -> str:
    """Resolve a standalone ``@instance.export`` value (e.g.

    ``faq_resume_to``).
    """
    if not value.startswith("@"):
        return value
    key = value[1:]
    if key not in flat_state_export_map:
        raise ValueError(f"Unresolved state alias: {value}")
    return flat_state_export_map[key]


# ---------------------------------------------------------------------------
# Iteration helpers over AgentSpec
# ---------------------------------------------------------------------------


def iter_all_flow_objects(spec: AgentSpec) -> Iterator[tuple[str, str, FlowObjectBase]]:
    """Yield ``(category, object_id, object)`` for every handler / state / terminal.
    """
    for handler in spec.handlers:
        yield ("handler", handler.handler_id, handler)
    for state in spec.states:
        yield ("state", state.state_id, state)
    for state in spec.terminal_states:
        yield ("terminal_state", state.state_id, state)


def iter_state_objects(spec: AgentSpec) -> Iterator[FlowObjectBase]:
    """Yield every state — both main and terminal — without category labels.
    """
    for state in spec.states:
        yield state
    for state in spec.terminal_states:
        yield state


def terminal_state_ids(spec: AgentSpec) -> set[str]:
    """Return the set of state ids that close the conversation.

    A state is terminal if ``type == "terminal"`` or ``final == "yes"``.
    Both forms are accepted because they coexist in legacy specs.
    """
    result: set[str] = set()
    for state in list(spec.states) + list(spec.terminal_states):
        if state.type == "terminal" or state.final == "yes":
            result.add(state.state_id)
    return result


def tool_contract_map(spec: AgentSpec) -> dict[str, ToolContract]:
    """Index ``spec.tool_contracts`` by tool name for O(1) lookups.
    """
    return {contract.name: contract for contract in spec.tool_contracts}


def iter_text_fields(spec: AgentSpec) -> Iterator[tuple[str, str]]:
    """Yield ``(location, text)`` for every textual field in ``spec``.

    Used by the placeholder validator to scan every line of the spec for
    references to undeclared variables, constants, or memory slots.
    """
    for item in spec.constants:
        yield (f"constants.{item.name}.description", item.description)
        yield (f"constants.{item.name}.value", item.value)

    for item in spec.input_variables:
        yield (f"input_variables.{item.name}.description", item.description)
        for idx, allowed in enumerate(item.allowed_values, start=1):
            yield (f"input_variables.{item.name}.allowed_values[{idx}]", allowed)

    for contract in spec.tool_contracts:
        yield (f"tool_contracts.{contract.name}.description", contract.description)
        for idx, fld in enumerate(contract.inputs, start=1):
            yield (f"tool_contracts.{contract.name}.inputs[{idx}].description", fld.description)
        for idx, fld in enumerate(contract.outputs, start=1):
            yield (f"tool_contracts.{contract.name}.outputs[{idx}].description", fld.description)
        for idx, note in enumerate(contract.notes, start=1):
            yield (f"tool_contracts.{contract.name}.notes[{idx}]", note)

    for idx, line in enumerate(spec.identity, start=1):
        yield (f"identity[{idx}]", line)

    for idx, line in enumerate(spec.objectives.primary_objective, start=1):
        yield (f"objectives.primary_objective[{idx}]", line)
    for idx, line in enumerate(spec.objectives.secondary_objectives, start=1):
        yield (f"objectives.secondary_objectives[{idx}]", line)
    for idx, line in enumerate(spec.objectives.success_alternatives, start=1):
        yield (f"objectives.success_alternatives[{idx}]", line)

    for idx, line in enumerate(spec.context.company_context, start=1):
        yield (f"context.company_context[{idx}]", line)
    for idx, line in enumerate(spec.context.approved_services, start=1):
        yield (f"context.approved_services[{idx}]", line)
    for idx, item in enumerate(spec.context.summary_services_library, start=1):
        yield (f"context.summary_services_library[{idx}].key", item.key)
        yield (f"context.summary_services_library[{idx}].procedure", item.procedure)
        yield (f"context.summary_services_library[{idx}].text", item.text)
    yield ("context.approved_process_intro", spec.context.approved_process_intro)
    for idx, step in enumerate(spec.context.approved_process_steps, start=1):
        yield (f"context.approved_process_steps[{idx}].title", step.title)
        yield (f"context.approved_process_steps[{idx}].text", step.text)
    for idx, line in enumerate(spec.context.support_and_trust, start=1):
        yield (f"context.support_and_trust[{idx}]", line)

    for section_name, lines in spec.policies.all_sections().items():
        for idx, line in enumerate(lines, start=1):
            yield (f"policies.{section_name}[{idx}]", line)

    for idx, line in enumerate(spec.flow_rules, start=1):
        yield (f"flow_rules[{idx}]", line)

    for idx, line in enumerate(spec.faq_policy, start=1):
        yield (f"faq_policy[{idx}]", line)

    for category, obj_id, obj in iter_all_flow_objects(spec):
        for idx, line in enumerate(obj.goal, start=1):
            yield (f"{category}.{obj_id}.goal[{idx}]", line)
        if hasattr(obj, "trigger"):
            for idx, line in enumerate(obj.trigger, start=1):
                yield (f"{category}.{obj_id}.trigger[{idx}]", line)
        for idx, line in enumerate(obj.do, start=1):
            yield (f"{category}.{obj_id}.do[{idx}]", line)
        for idx, line in enumerate(obj.say, start=1):
            yield (f"{category}.{obj_id}.say[{idx}]", line)
        for idx, line in enumerate(obj.store, start=1):
            yield (f"{category}.{obj_id}.store[{idx}]", line)
        for idx, line in enumerate(obj.route, start=1):
            yield (f"{category}.{obj_id}.route[{idx}]", line)
        for idx, line in enumerate(obj.fallback, start=1):
            yield (f"{category}.{obj_id}.fallback[{idx}]", line)
        if obj.faq_resume_to:
            yield (f"{category}.{obj_id}.faq_resume_to", obj.faq_resume_to)

    for faq in spec.faqs:
        for idx, line in enumerate(faq.match, start=1):
            yield (f"faq.{faq.faq_id}.match[{idx}]", line)
        for idx, line in enumerate(faq.say, start=1):
            yield (f"faq.{faq.faq_id}.say[{idx}]", line)
