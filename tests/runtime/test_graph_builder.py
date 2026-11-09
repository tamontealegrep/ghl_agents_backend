"""
Unit tests for the pure helper functions in agent_runtime.runtime.graph_builder.

    The full StateGraph wiring (interrupt/Command mechanics, tool executor
    against a stub endpoint) is exercised as an integration smoke test —
    see tests/integration/test_langgraph_runtime_smoke.py.
"""

from __future__ import annotations

from agent_runtime.dsl.schemas import ConstantItem, ToolContractField
from agent_runtime.runtime.graph_builder import (
    _apply_conditional_mutations,
    _append_history,
    _apply_store_line,
    _bind_tool_inputs,
    _capture_json_schema,
    _coerce_constant,
    _extract_mechanical_arg_bindings,
    _interpolate_slots,
    _llm_extract_capture,
    _make_node_fn,
    _coerce_value,
    _json_schema_type,
    _make_render_say,
    _sync_language_change,
    _make_resolve_edges,
    _matches,
    fresh_state,
    initial_slots,
)
from agent_runtime.runtime.llm_client import LLMContext
from agent_runtime.targets.langgraph.graph_renderer import GlobalRouterDefinition, GraphEdge, GraphNode
from agent_runtime.targets.langgraph.runtime_artifact import render_runtime_artifact
from tests.contract.conftest import build_minimal_agent_spec


class _FakeLLMClient:
    def __init__(self, reply: str = "", structured_reply: dict | None = None):
        self.reply = reply
        self.structured_reply = structured_reply
        self.prompts: list[str] = []
        self.structured_prompts: list[str] = []
        self.temperatures: list[float] = []

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        self.temperatures.append(temperature)
        return self.reply

    def extract_structured(self, prompt, json_schema):
        self.structured_prompts.append(prompt)
        if self.structured_reply is None:
            raise NotImplementedError
        return self.structured_reply


def _ctx(
    slots: dict | None = None,
    *,
    history: list[str] | None = None,
    last_user_message: str = "",
    goal: list[str] | None = None,
    do: list[str] | None = None,
    pending_question: str = "",
    contact: dict | None = None,
) -> LLMContext:
    """
Build the `LLMContext` every runtime LLM decision call now takes (2026-09-17)

    instead of its own hand-picked parameter list. Passes `slots` through by
        reference (not a copy) — tests that mutate a slot via `_apply_store_line`/
        `_apply_conditional_mutations` assert on the same dict they built.

    Parameters:
        slots: Description.
        history: Description.
        last_user_message: Description.
        goal: Description.
        do: Description.
        pending_question: Description.
        contact: Description.

    Returns:
        The result.
"""
    return LLMContext(
        slots=slots if slots is not None else {},
        history=history or [],
        last_user_message=last_user_message,
        goal=goal or [],
        do=do or [],
        pending_question=pending_question,
        contact=contact or {},
    )


# ---------------------------------------------------------------------------
# LLMContext.block() — contact rendering (2026-09-21)
# ---------------------------------------------------------------------------


def test_block_omits_contact_section_when_contact_is_empty():
    assert "Contact info" not in _ctx({}).block()


def test_block_renders_known_contact_fields():
    block = _ctx({}, contact={"name": "Ana Gomez", "email": None}).block()
    assert "Contact info" in block
    assert "Ana Gomez" in block


# ---------------------------------------------------------------------------
# _apply_store_line
# ---------------------------------------------------------------------------


def test_store_increment():
    slots = {"retry_count": 1}
    _apply_store_line("increment [retry_count] by 1", _ctx(slots), _FakeLLMClient())
    assert slots["retry_count"] == 2


def test_store_increment_defaults_missing_slot_to_zero():
    slots: dict = {}
    _apply_store_line("increment [retry_count] by 1", _ctx(slots), _FakeLLMClient())
    assert slots["retry_count"] == 1


def test_store_slot_to_slot_copy():
    slots = {"raw_name": "Alex", "name": None}
    _apply_store_line("[name] = [raw_name]", _ctx(slots), _FakeLLMClient())
    assert slots["name"] == "Alex"


def test_store_integer_literal():
    slots: dict = {}
    _apply_store_line("[max_tries] = 3", _ctx(slots), _FakeLLMClient())
    assert slots["max_tries"] == 3


def test_store_boolean_literal():
    slots: dict = {}
    _apply_store_line("[confirmed] = true", _ctx(slots), _FakeLLMClient())
    assert slots["confirmed"] is True


def test_store_quoted_string_literal():
    slots: dict = {}
    _apply_store_line("[status] = 'pending'", _ctx(slots), _FakeLLMClient())
    assert slots["status"] == "pending"


def test_store_unquoted_prose_delegates_to_llm():
    client = _FakeLLMClient(reply="America/Bogota")
    slots = {"city": "Bogota"}
    _apply_store_line("[tz] = the IANA timezone for the reported city", _ctx(slots), client)
    assert slots["tz"] == "America/Bogota"
    assert len(client.prompts) == 1


def test_store_unquoted_prose_prompt_includes_history():
    """
`_llm_compute_store_value` (2026-09-17) — one more decision call

    migrated onto the shared `LLMContext`, closing a gap it previously had
        alongside `_llm_extract_capture`'s: no visibility into recent turns.

    Returns:
        None.
"""
    client = _FakeLLMClient(reply="America/Bogota")
    history = ["agent: ¿En qué ciudad estás?", "user: Bogota"]
    _apply_store_line(
        "[tz] = the IANA timezone for the reported city",
        _ctx({"city": "Bogota"}, history=history),
        client,
    )
    assert "agent: ¿En qué ciudad estás?" in client.prompts[0]


# ---------------------------------------------------------------------------
# _extract_mechanical_arg_bindings / _bind_tool_inputs — tool-argument
# binding: an `action` node's DO line mapping a captured/namespaced slot
# to a tool contract's differently-named input, mechanical before LLM.
# ---------------------------------------------------------------------------


def test_mechanical_arg_binding_resolves_slot_reference():
    bindings = _extract_mechanical_arg_bindings(["nationalities = [cl__nat]"], {"cl__nat": "Venezuela"})
    assert bindings == {"nationalities": "Venezuela"}


def test_mechanical_arg_binding_resolves_constant_reference():
    bindings = _extract_mechanical_arg_bindings(
        ["duration = <APPOINTMENT_DURATION_MINUTES>"], {"APPOINTMENT_DURATION_MINUTES": 30}
    )
    assert bindings == {"duration": 30}


def test_mechanical_arg_binding_resolves_quoted_literal():
    bindings = _extract_mechanical_arg_bindings(["calendar_type = 'IVF'"], {})
    assert bindings == {"calendar_type": "IVF"}


def test_mechanical_arg_binding_splits_multiple_assignments_in_one_line():
    bindings = _extract_mechanical_arg_bindings(
        ["contact_name = [c_name], contact_email = [c_email], contact_phone = [c_phone]."],
        {"c_name": "Alex", "c_email": "alex@example.com", "c_phone": "+15551234567"},
    )
    assert bindings == {
        "contact_name": "Alex",
        "contact_email": "alex@example.com",
        "contact_phone": "+15551234567",
    }


def test_mechanical_arg_binding_resolves_a_dot_field_access_on_a_captured_object():
    """
Regression test, found live: `AM_DO_CANCEL`'s real DO line —

    `"event_id = [app].event_id"` (`[app]` is a captured appointment
        *object*, `[app] = [appointments][0]`) — used to be chopped by the old
        period-only split into `"event_id = [app]"` + `"event_id"`, so the
        first segment mechanically bound `event_id` to the *entire* `[app]`
        dict instead of its `event_id` field. A dot immediately followed by an
        identifier (no space) must stay part of the same segment.

    Returns:
        None.
"""
    bindings = _extract_mechanical_arg_bindings(
        ["event_id = [app].event_id", "calendar_type = [app].calendar_type"],
        {"app": {"event_id": "evt_real_id_123", "calendar_type": "SUR"}},
    )
    assert bindings == {"event_id": "evt_real_id_123", "calendar_type": "SUR"}


def test_mechanical_arg_binding_defers_dot_access_on_a_non_object_slot_to_the_llm():
    """
A `[slot].field` reference against a slot that isn't (yet) a dict

    (e.g. `[app]` still `None` before the lookup ran) must never crash or
        guess — it stays unresolved, same as any other unresolvable RHS.

    Returns:
        None.
"""
    bindings = _extract_mechanical_arg_bindings(["event_id = [app].event_id"], {"app": None})
    assert bindings == {}


def test_mechanical_arg_binding_still_splits_a_trailing_sentence_period():
    """
The split fix must not stop splitting genuine sentence-ending

    periods — only ones immediately followed by an identifier character.

    Returns:
        None.
"""
    bindings = _extract_mechanical_arg_bindings(
        ["calendar_type = 'BOTH'."],
        {},
    )
    assert bindings == {"calendar_type": "BOTH"}


def test_mechanical_arg_binding_skips_a_described_transformation():
    """
A DO line describing a transform, not a bare copy, is left for the

    LLM fallback — the mechanical pass never guesses at it.

    Returns:
        None.
"""
    bindings = _extract_mechanical_arg_bindings(["language = the contact's language written in uppercase"], {"preferred_language": "es"})
    assert bindings == {}


def test_mechanical_arg_binding_skips_the_nationality_derivation_line():
    """
Regression test: `check_visa`'s real DO line used to be a bare copy

    (`nationalities = [nat]`), which sent the lead's raw wording (e.g.
        "venezolana", a demonym, not a country name) straight to the tool — the
        real backend's country table only matches a country name or ISO
        alpha-3 code, so every unrecognized demonym silently resolved as
        "requires visa". Now shaped as a described derivation, which the
        mechanical pass must leave for the LLM fallback rather than bind
        `[nat]`'s raw value verbatim.

    Returns:
        None.
"""
    bindings = _extract_mechanical_arg_bindings(
        ["nationalities = the country name or ISO 3166-1 alpha-3 code for [nat]"], {"nat": "venezolana"}
    )
    assert bindings == {}


def test_bind_tool_inputs_prefers_exact_slot_name_match():
    fields = [ToolContractField(name="nationalities", required=True, description="d")]
    bound = _bind_tool_inputs(fields, _ctx({"nationalities": "USA"}), _FakeLLMClient())
    assert bound == {"nationalities": "USA"}


def test_bind_tool_inputs_fills_a_declared_history_input_from_the_conversation():
    fields = [
        ToolContractField(name="question", required=True, description="d"),
        ToolContractField(name="history", required=False, description="d"),
    ]
    ctx = _ctx({"question": "and how long?"}, history=["agent: Which service?", "user: IVF"])
    bound = _bind_tool_inputs(fields, ctx, _FakeLLMClient())
    assert bound == {"question": "and how long?", "history": "agent: Which service?\nuser: IVF"}


def test_bind_tool_inputs_leaves_history_out_when_the_tool_does_not_declare_it():
    fields = [ToolContractField(name="question", required=True, description="d")]
    bound = _bind_tool_inputs(fields, _ctx({"question": "q"}, history=["user: hi"]), _FakeLLMClient())
    assert bound == {"question": "q"}


def test_bind_tool_inputs_uses_mechanical_do_binding_when_no_exact_slot():
    fields = [ToolContractField(name="nationalities", required=True, description="d")]
    bound = _bind_tool_inputs(
        fields, _ctx({"cl__nat": "Venezuela"}, do=["Send nationalities = [cl__nat]."]), _FakeLLMClient()
    )
    assert bound == {"nationalities": "Venezuela"}


def test_bind_tool_inputs_coerces_a_mechanically_bound_value_to_its_contract_type():
    """
Regression test, found live: `book_appointment`'s `duration` input is

    declared `type_expr: "str"` in its real contract, bound mechanically from
        `<APPOINTMENT_DURATION_MINUTES>` — a compile-time constant `initial_slots()`
        coerces to a real Python `int` — via the DO line `"duration = <APPOINTMENT_
        DURATION_MINUTES>"`. The mechanical pass copied the raw int straight
        through with no type check at all, so the backend received a JSON
        integer where its Pydantic schema required a string and rejected the
        call with HTTP 422. Unlike the LLM-fallback path (JSON-schema-typed by
        construction), mechanical binding needs this coercion explicitly.

    Returns:
        None.
"""
    fields = [ToolContractField(name="duration", required=True, description="d", type_expr="str")]
    bound = _bind_tool_inputs(
        fields, _ctx({"APPOINTMENT_DURATION_MINUTES": 30}, do=["duration = <APPOINTMENT_DURATION_MINUTES>."]),
        _FakeLLMClient(),
    )
    assert bound == {"duration": "30"}


def test_bind_tool_inputs_falls_back_to_one_batched_llm_call():
    fields = [
        ToolContractField(name="start_date", required=True, description="d", type_expr="str"),
        ToolContractField(name="duration", required=True, description="d", type_expr="int"),
    ]
    client = _FakeLLMClient(structured_reply={"start_date": "2026-06-04T08:00:00-05:00", "duration": 30})
    bound = _bind_tool_inputs(
        fields,
        _ctx(
            {},
            do=["start_date = the literal start_co field of the chosen slot.", "duration = the requested minutes."],
        ),
        client,
    )
    assert bound == {"start_date": "2026-06-04T08:00:00-05:00", "duration": 30}
    assert len(client.structured_prompts) == 1  # one batched call, not one per argument


def test_bind_tool_inputs_llm_fallback_includes_the_field_s_own_contract_description():
    """
Regression test: the DO line's own wording is often vague about the

    target *format* ("the country name or code for [nat]") — the field's
        own contract description/examples (e.g. "'USA', 'China, India'") is
        what actually tells the model what that format looks like. Missing
        this was a real, measured reliability gap: without it, deriving a
        country form from a reported nationality (e.g. "venezolana" -> "VEN")
        sometimes just echoed the raw captured wording back unchanged.

    Returns:
        None.
"""
    fields = [
        ToolContractField(
            name="nationalities",
            required=True,
            description="Una o más nacionalidades a revisar.",
            type_expr="str",
            examples=["USA", "China, India"],
        )
    ]
    client = _FakeLLMClient(structured_reply={"nationalities": "VEN"})
    _bind_tool_inputs(
        fields, _ctx({"nat": "venezolana"}, do=["nationalities = the ISO code for [nat]."]), client
    )
    (prompt,) = client.structured_prompts
    assert "Una o más nacionalidades a revisar." in prompt
    assert "USA, China, India" in prompt


def test_bind_tool_inputs_never_calls_llm_when_everything_resolves_mechanically():
    fields = [ToolContractField(name="nationalities", required=True, description="d")]
    client = _FakeLLMClient()  # extract_structured raises if called
    bound = _bind_tool_inputs(fields, _ctx({"cl__nat": "USA"}, do=["nationalities = [cl__nat]"]), client)
    assert bound == {"nationalities": "USA"}
    assert client.structured_prompts == []


def test_bind_tool_inputs_omits_unresolved_optional_field_without_calling_llm():
    fields = [
        ToolContractField(name="calendar_type", required=True, description="d"),
        ToolContractField(name="notes", required=False, description="d"),
    ]
    client = _FakeLLMClient()  # extract_structured raises if called
    bound = _bind_tool_inputs(fields, _ctx({"calendar_type": "IVF"}), client)
    assert bound == {"calendar_type": "IVF"}
    assert "notes" not in bound
    assert client.structured_prompts == []


def test_bind_tool_inputs_tries_llm_fallback_for_optional_field_named_in_do():
    """
2026-09-21 regression: `find_appointment`'s `contact_name`/`contact_email`

    are optional, bound via `"contact_name = [name] ?? {{contact.name}}"` — a
        compound RHS the mechanical pass can't resolve. Before this, an optional
        field with an unresolved DO line was silently dropped, never even tried
        against the LLM fallback — the author's explicit DO instruction for it was
        just ignored, and the tool call went out missing the argument entirely.

    Returns:
        None.
"""
    fields = [
        ToolContractField(name="calendar_type", required=True, description="d"),
        ToolContractField(name="contact_name", required=False, description="d"),
    ]
    client = _FakeLLMClient(structured_reply={"contact_name": "Ana Gomez"})
    bound = _bind_tool_inputs(
        fields,
        _ctx({"calendar_type": "IVF"}, do=["contact_name = [name] ?? {{contact.name}}"], contact={"name": "Ana Gomez"}),
        client,
    )
    assert bound == {"calendar_type": "IVF", "contact_name": "Ana Gomez"}
    assert len(client.structured_prompts) == 1


def test_bind_tool_inputs_drops_unresolvable_optional_field_from_llm_fallback():
    """
An optional field the LLM genuinely can't resolve comes back as an

    explicit `None` (the JSON schema requires *a* value) — dropped here,
        same as if it had never reached the LLM fallback at all, rather than
        sent on as a literal `null` a plain `str`-typed backend field may reject.

    Returns:
        None.
"""
    fields = [
        ToolContractField(name="calendar_type", required=True, description="d"),
        ToolContractField(name="contact_email", required=False, description="d"),
    ]
    client = _FakeLLMClient(structured_reply={"contact_email": None})
    bound = _bind_tool_inputs(
        fields,
        _ctx({"calendar_type": "IVF"}, do=["contact_email = [email] ?? {{contact.email}}"]),
        client,
    )
    assert bound == {"calendar_type": "IVF"}
    assert "contact_email" not in bound


def test_bind_tool_inputs_keeps_none_for_unresolvable_required_field():
    fields = [ToolContractField(name="start_date", required=True, description="d")]
    client = _FakeLLMClient(structured_reply={"start_date": None})
    bound = _bind_tool_inputs(fields, _ctx({}, do=["start_date = the chosen slot's start."]), client)
    assert bound == {"start_date": None}


# ---------------------------------------------------------------------------
# _matches / resolve_edges — the MATCHES operator's runtime counterpart
# ---------------------------------------------------------------------------


def test_matches_true_for_registered_predicate():
    assert _matches("America/Bogota", "iana_timezone_format") is True


def test_matches_true_for_three_segment_iana_identifier():
    assert _matches("America/Argentina/Buenos_Aires", "iana_timezone_format") is True


def test_matches_false_for_non_matching_value():
    assert _matches("not-a-timezone", "iana_timezone_format") is False


def test_matches_false_for_unregistered_predicate():
    assert _matches("anything", "not_a_real_predicate") is False


def test_matches_false_for_none_value():
    assert _matches(None, "iana_timezone_format") is False


def test_matches_scheduling_state_id_true_for_scheduling_states():
    assert _matches("SC__SC_ASK_E", "scheduling_state_id") is True
    assert _matches("SC__SC_DEC_OK", "scheduling_state_id") is True


def test_store_copies_a_contact_field_mechanically():
    ctx = _ctx({}, contact={"name": " Laura Gómez ", "email": "", "phone": "{{contact.phone}}", "service": "null"})
    for field in ("name", "email", "phone", "service", "missing"):
        _apply_store_line("[crm_" + field + "] = {{contact." + field + "}}", ctx, _FakeLLMClient())
    assert ctx.slots == {
        "crm_name": "Laura Gómez", "crm_email": None, "crm_phone": None, "crm_service": None, "crm_missing": None,
    }


def test_store_replaces_constants_written_inside_a_quoted_text():
    ctx = _ctx({"SUR_MINUTES": "30", "IVF_MINUTES": "40"})
    _apply_store_line("[range] = '<SUR_MINUTES> to <IVF_MINUTES>'", ctx, _FakeLLMClient())
    _apply_store_line("[unknown] = 'keeps <NOT_A_CONSTANT> as written'", ctx, _FakeLLMClient())
    assert ctx.slots["range"] == "30 to 40"
    assert ctx.slots["unknown"] == "keeps <NOT_A_CONSTANT> as written"


def test_store_first_word_takes_the_first_name_and_is_empty_without_one():
    ctx = _ctx({"full": "  Laura  Gómez ", "none": None, "blank": "  "})
    for source in ("full", "none", "blank"):
        _apply_store_line("[first_" + source + "] = FIRST_WORD [" + source + "]", ctx, _FakeLLMClient())
    assert ctx.slots["first_full"] == "Laura"
    assert ctx.slots["first_none"] is None and ctx.slots["first_blank"] is None


def test_store_replaces_slots_written_inside_a_quoted_text():
    ctx = _ctx({"first_name": "Laura"})
    _apply_store_line("[hello] = 'Hi [first_name]!'", ctx, _FakeLLMClient())
    _apply_store_line("[other] = 'Hi [nobody]!'", ctx, _FakeLLMClient())
    assert ctx.slots["hello"] == "Hi Laura!"
    assert ctx.slots["other"] == "Hi [nobody]!"


def test_store_language_name_maps_codes_and_names_and_defaults_to_english():
    ctx = _ctx({"code": "es"})
    for code, expected in (("es", "Spanish"), ("pt", "Portuguese"), ("EN", "English"), ("Spanish", "Spanish"), (None, "English"), ("fr", "English")):
        ctx.slots["code"] = code
        _apply_store_line("[preferred_language] = LANGUAGE_NAME [code]", ctx, _FakeLLMClient())
        assert ctx.slots["preferred_language"] == expected


def test_store_find_day_returns_the_day_only_when_it_is_offered():
    offered = [{"start_local": "2026-11-05T09:00:00-05:00"}, {"start_local": "2026-11-09T10:30:00-05:00"}]
    ctx = _ctx({"day": "2026-11-09", "available_slots": offered})
    _apply_store_line("[day_ok] = FIND_DAY [day] IN [available_slots]", ctx, _FakeLLMClient())
    assert ctx.slots["day_ok"] == "2026-11-09"
    ctx.slots["day"] = "2026-11-06"
    _apply_store_line("[day_ok] = FIND_DAY [day] IN [available_slots]", ctx, _FakeLLMClient())
    assert ctx.slots["day_ok"] is None
    ctx.slots["day"] = None
    _apply_store_line("[day_ok] = FIND_DAY [day] IN [available_slots]", ctx, _FakeLLMClient())
    assert ctx.slots["day_ok"] is None


def test_matches_knowledge_state_id_only_for_knowledge_states():
    assert _matches("KQ__KQ_ASK_DOUBT", "knowledge_state_id") is True
    assert _matches("KQ__KQ_MORE", "knowledge_state_id") is True
    assert _matches("SC__SC_ASK_E", "knowledge_state_id") is False
    assert _matches("O__OP_ASK", "knowledge_state_id") is False
    assert _matches("KQ__", "knowledge_state_id") is False
    assert _matches(None, "knowledge_state_id") is False


def test_matches_scheduling_state_id_false_for_other_states():
    assert _matches("AH__AH_ASK", "scheduling_state_id") is False
    assert _matches("O__OP_S", "scheduling_state_id") is False
    assert _matches("SC__", "scheduling_state_id") is False
    assert _matches(None, "scheduling_state_id") is False


def test_resolve_edges_evaluates_matches_condition_mechanically():
    """
Regression test: `_EVAL_BUILTINS` used to be `{"len": len}` only —

    a condition_parser-classified-as-mechanical `MATCHES` edge (real
        content: `[document_number] MATCHES numeric_string_without_spaces_
        or_punctuation`) raised NameError inside `eval()`, silently swallowed
        by resolve_edges's `except Exception: continue`, so the edge could
        never actually match at runtime despite being classified as "code".

    Returns:
        None.
"""
    resolve_edges = _make_resolve_edges(_FakeLLMClient())
    edges = [
        GraphEdge(
            target="VALID",
            condition_text="[tz] MATCHES iana_timezone_format",
            is_mechanical=True,
            python_expression="_matches(tz, 'iana_timezone_format')",
        )
    ]
    target = resolve_edges(edges, _ctx({"tz": "America/Bogota"}))
    assert target == "VALID"


def test_resolve_edges_matches_condition_no_match_falls_through():
    resolve_edges = _make_resolve_edges(_FakeLLMClient())
    edges = [
        GraphEdge(
            target="VALID",
            condition_text="[tz] MATCHES iana_timezone_format",
            is_mechanical=True,
            python_expression="_matches(tz, 'iana_timezone_format')",
        )
    ]
    target = resolve_edges(edges, _ctx({"tz": "not-a-timezone"}))
    assert target is None


def test_resolve_edges_llm_prompt_includes_history():
    """
`_llm_pick_condition` (2026-09-17) — migrated onto the shared

    `LLMContext`, which now threads `history` through even for non-question
        nodes (`_make_router_fn`'s dispatch previously dropped it entirely).

    Returns:
        None.
"""
    client = _FakeLLMClient(reply="0")
    resolve_edges = _make_resolve_edges(client)
    edges = [GraphEdge(target="VALID", condition_text="the user confirmed", is_mechanical=False)]
    history = ["agent: ¿Confirmas la cita?", "user: sí"]
    resolve_edges(edges, _ctx({}, history=history))
    assert "agent: ¿Confirmas la cita?" in client.prompts[0]


def test_store_null_reset():
    slots = {"available_slots": ["stale"]}
    _apply_store_line("[available_slots] = NULL", _ctx(slots), _FakeLLMClient())
    assert slots["available_slots"] is None


def test_store_self_referential_increment():
    """
The DSL's own documented `[x] = [x] + 1` form (NUMERIC_AND_RETRY_

    COUNTER_SEMANTICS) — distinct from the `increment [x] by 1` phrase
        above, and the one real agent content actually uses.

    Returns:
        None.
"""
    slots = {"tz_try": 1}
    _apply_store_line("[tz_try] = [tz_try] + 1", _ctx(slots), _FakeLLMClient())
    assert slots["tz_try"] == 2


def test_store_self_referential_increment_defaults_missing_slot_to_zero():
    slots: dict = {}
    _apply_store_line("[tz_try] = [tz_try] + 1", _ctx(slots), _FakeLLMClient())
    assert slots["tz_try"] == 1


def test_store_self_referential_decrement():
    slots = {"budget": 5}
    _apply_store_line("[budget] = [budget] - 2", _ctx(slots), _FakeLLMClient())
    assert slots["budget"] == 3


# ---------------------------------------------------------------------------
# _apply_conditional_mutations — DO/STORE lines shaped "If X, update [slot]":
# a third DO/STORE convention, distinct from `[slot] = value` and
# `input_name = [slot]`, that branches on free text and so gets no
# mechanical pass at all — straight to one batched LLM call per node.
# ---------------------------------------------------------------------------


def test_conditional_mutations_never_calls_llm_without_a_bracket_reference():
    """
A narrative DO line with no `[slot]` reference is not a mutation at

    all — left untouched, same as `_apply_store_line`'s existing no-op.

    Returns:
        None.
"""
    client = _FakeLLMClient()  # extract_structured raises if called
    slots = {"svc": None}
    _apply_conditional_mutations(
        ["TOOL CALL ONLY: call check_visa now."], _ctx(slots, last_user_message="Hola"), client
    )
    assert slots == {"svc": None}
    assert client.structured_prompts == []


def test_conditional_mutations_skips_lines_already_recognized_as_assignments():
    """
A plain `[x] = 1` line is `_apply_store_line`'s own job — it must

    not also be dragged into the conditional LLM call's target-slot set.

    Returns:
        None.
"""
    client = _FakeLLMClient(structured_reply={"svc": {"applies": True, "value": "surrogacy"}})
    slots = {"svc_try": 0, "svc": None}
    _apply_conditional_mutations(
        ["[svc_try] = [svc_try] + 1", "If [svc] is still NULL, infer it from the user's latest message."],
        _ctx(slots, last_user_message="quiero alguien que lleve a mi bebé"),
        client,
    )
    assert slots["svc"] == "surrogacy"
    assert slots["svc_try"] == 0  # untouched by the conditional-mutation call
    (prompt,) = client.structured_prompts
    assert "svc_try" not in prompt.split("Instructions:")[1].split("Known slot values:")[0]


def test_conditional_mutations_resolves_free_text_intent_via_llm():
    """
The motivating case: a mechanical parser can never match "quiero

    alguien que lleve a mi bebé" to 'surrogacy' — only an LLM call can.

    Returns:
        None.
"""
    client = _FakeLLMClient(structured_reply={"svc": {"applies": True, "value": "surrogacy"}})
    slots = {"svc": None}
    _apply_conditional_mutations(
        ["If [svc] is still NULL, infer it from the user's latest message using the approved service labels."],
        _ctx(
            slots,
            goal=["Validate that the service was captured and route to classification."],
            last_user_message="quiero alguien que lleve a mi bebé",
        ),
        client,
    )
    assert slots["svc"] == "surrogacy"
    assert len(client.structured_prompts) == 1


def test_conditional_mutations_gates_independently_per_slot_within_one_line():
    """
SC_FIX's real shape: one DO line bundles three independent per-slot

    conditions ("the name, X; the phone, Y; the email, Z"), not one shared
        condition — only the slot whose own condition actually fired may
        change; the others, including the non-scalar `available_slots` (a
        list), must be left completely untouched even though they're named on
        the very same line.

    Returns:
        None.
"""
    client = _FakeLLMClient(
        structured_reply={
            "c_name": {"applies": False, "value": None},
            "c_phone": {"applies": False, "value": None},
            "c_email": {"applies": True, "value": "alex@nuevo.com"},
        }
    )
    slots = {"c_name": "Alex", "c_phone": "+15551234567", "c_email": "alex@old.com"}
    _apply_conditional_mutations(
        ["If the correction is the name, update [c_name]; the phone, [c_phone]; the email, [c_email]."],
        _ctx(slots, last_user_message="mi correo está mal, es alex@nuevo.com"),
        client,
    )
    assert slots == {"c_name": "Alex", "c_phone": "+15551234567", "c_email": "alex@nuevo.com"}


def test_conditional_mutations_batches_multiple_lines_into_one_call():
    """
Several DO lines, resolved together against one user message — never

    one LLM call per line. The line whose condition didn't fire (including
        the non-scalar `available_slots`, a list) is left completely untouched.

    Returns:
        None.
"""
    client = _FakeLLMClient(
        structured_reply={
            "c_name": {"applies": True, "value": "Alex"},
            "c_phone": {"applies": False, "value": None},
            "c_email": {"applies": False, "value": None},
            "day": {"applies": False, "value": None},
            "slot": {"applies": False, "value": None},
            "available_slots": {"applies": False, "value": None},
        }
    )
    slots = {"c_name": "Old Name", "c_phone": "+15551234567", "c_email": "alex@example.com",
              "day": "2026-06-04", "slot": "09:00", "available_slots": ["09:00"]}
    _apply_conditional_mutations(
        [
            "If the correction is the name, update [c_name]; the phone, [c_phone]; the email, [c_email].",
            "If the correction affects the date, day, time, or timezone, set [day], [slot], and [available_slots] to NULL to force a new selection from the tool.",
        ],
        _ctx(slots, last_user_message="mi nombre está mal, es Alex"),
        client,
    )
    assert slots["c_name"] == "Alex"
    assert slots["available_slots"] == ["09:00"]  # untouched — its condition didn't apply
    assert len(client.structured_prompts) == 1  # one batched call, not one per line


def test_conditional_mutations_applies_null_returned_by_llm():
    """
An instruction that says to clear a slot must actually reset it —

    a returned `null` is a real value here, not "no update".

    Returns:
        None.
"""
    client = _FakeLLMClient(
        structured_reply={
            "day": {"applies": True, "value": None},
            "slot": {"applies": True, "value": None},
            "available_slots": {"applies": True, "value": None},
        }
    )
    slots = {"day": "2026-06-04", "slot": "09:00", "available_slots": ["09:00"]}
    _apply_conditional_mutations(
        ["If the correction affects the date, set [day], [slot], and [available_slots] to NULL."],
        _ctx(slots, last_user_message="mejor otro día"),
        client,
    )
    assert slots == {"day": None, "slot": None, "available_slots": None}


def test_conditional_mutations_ignores_slot_whose_gate_is_false():
    """
A slot whose `applies` gate is false must never be written, regardless

    of what junk sits in its `value` field.

    Returns:
        None.
"""
    client = _FakeLLMClient(structured_reply={"svc": {"applies": False, "value": "ivf"}})
    slots = {"svc": None}
    _apply_conditional_mutations(
        ["If [svc] is still NULL, infer it from the user's latest message."],
        _ctx(slots, last_user_message="Hola"),
        client,
    )
    assert slots["svc"] is None


def test_conditional_mutations_noop_when_only_recognized_assignments_present():
    client = _FakeLLMClient()  # extract_structured raises if called
    slots = {"svc_try": 0}
    _apply_conditional_mutations(["[svc_try] = [svc_try] + 1"], _ctx(slots, last_user_message="Hola"), client)
    assert client.structured_prompts == []


def test_conditional_mutations_never_touches_slots_named_only_in_a_comparison_line():
    """
Regression test: SC_DEC_D's real DO line — "Compare [day] only against

    the start_local dates in [available_slots]. Do not accept approximate,
        inferred, or unlisted days." — exists purely as context for a sibling
        `eval: "llm"` ROUTE condition, not an instruction to change [day]/
        [available_slots]. Fed to _apply_conditional_mutations anyway (it
        references brackets and isn't a recognized assignment), the LLM
        fallback obliged and overwrote available_slots (a list of real
        appointment objects) with an arbitrary string — corrupting state a
        sibling node then rendered straight into a user-facing message. Must
        never even reach the LLM: client raises if extract_structured is
        called.

    Returns:
        None.
"""
    client = _FakeLLMClient()  # extract_structured raises if called
    slots = {"day": None, "available_slots": [{"start_local": "09:00", "end_local": "09:30"}]}
    _apply_conditional_mutations(
        ["Compare [day] only against the start_local dates in [available_slots]. Do not accept approximate, inferred, or unlisted days."],
        _ctx(slots, last_user_message="el 22"),
        client,
    )
    assert client.structured_prompts == []
    assert slots["day"] is None
    assert slots["available_slots"] == [{"start_local": "09:00", "end_local": "09:30"}]


def test_conditional_mutations_prompt_includes_history():
    """
`_apply_conditional_mutations` (2026-09-17) — migrated onto the shared

    `LLMContext`; previously the one node-scoped decision call that still
        lacked `history` after `_llm_extract_capture` and `match_global_router`
        already had it.

    Returns:
        None.
"""
    client = _FakeLLMClient(structured_reply={"svc": {"applies": True, "value": "surrogacy"}})
    slots = {"svc": None}
    history = ["agent: ¿Qué servicio buscas?", "user: no sé todavía"]
    _apply_conditional_mutations(
        ["If [svc] is still NULL, infer it from the user's latest message."],
        _ctx(slots, history=history, last_user_message="quiero alguien que lleve a mi bebé"),
        client,
    )
    assert "agent: ¿Qué servicio buscas?" in client.structured_prompts[0]


# ---------------------------------------------------------------------------
# _make_node_fn — DO mutations
# ---------------------------------------------------------------------------


def _decision_node(do: list[str]) -> GraphNode:
    return GraphNode(node_id="DEC", node_type="decision", do=do)


def _build_node_fn(node: GraphNode, llm_client: _FakeLLMClient):
    return _make_node_fn(
        node,
        llm_client,
        router=GlobalRouterDefinition(handlers=[], faqs=[]),
        node_by_id={},
        render_say=lambda *args: "",
        resolve_edges=lambda *args: None,
        tool_executors={},
        tool_input_fields={},
        say_callback=lambda text: None,
    )


def test_decision_node_do_increments_retry_counter():
    """
Regression test: `DO` used to be fed to the LLM only as route-

    decision context and never applied to `slots`, so every retry counter
        silently never incremented in the compiled LangGraph runtime — see
        DESIGN_PATTERNS.md. `[x_try] = [x_try] + 1` lives in `DO`, never
        `STORE`, across the real agent corpus.

    Returns:
        None.
"""
    node = _decision_node(do=["[tz_try] = [tz_try] + 1"])
    node_fn = _build_node_fn(node, _FakeLLMClient())
    result = node_fn({"slots": {"tz_try": 2}, "current_state": "", "last_user_message": ""})
    assert result["slots"]["tz_try"] == 3


def test_decision_node_do_resets_slot_to_null():
    node = _decision_node(do=["[available_slots] = NULL"])
    node_fn = _build_node_fn(node, _FakeLLMClient())
    result = node_fn({"slots": {"available_slots": ["stale"]}, "current_state": "", "last_user_message": ""})
    assert result["slots"]["available_slots"] is None


def test_registration_node_do_and_store_duplicate_not_double_applied():
    """
Real content often repeats the same assignment in both `DO` and

    `STORE` on `registration` nodes — the `DO` pass must skip a line
        already present in `STORE` so it isn't (mechanically or via an LLM
        call) applied twice.

    Returns:
        None.
"""
    node = GraphNode(
        node_id="REG",
        node_type="registration",
        do=["[c_name] = [raw_name]"],
        store=["[c_name] = [raw_name]"],
    )
    node_fn = _build_node_fn(node, _FakeLLMClient())
    result = node_fn(
        {"slots": {"raw_name": "Alex", "c_name": None}, "current_state": "", "last_user_message": ""}
    )
    assert result["slots"]["c_name"] == "Alex"


def test_decision_node_do_resolves_conditional_line_via_llm():
    """
Live-piloting regression: `opening.yaml`'s `OP_DEC` has

    `"If [svc] is still NULL, infer it from the user's latest message."` in
        its DO block — a real second-chance inference, previously a total
        no-op (didn't match `[slot] = value`, so `_apply_store_line` silently
        dropped it), now resolved via the same batched-LLM-call path.

    Returns:
        None.
"""
    node = _decision_node(
        do=["If [svc] is still NULL, infer it from the user's latest message using the approved service labels."]
    )
    client = _FakeLLMClient(structured_reply={"svc": {"applies": True, "value": "surrogacy"}})
    node_fn = _build_node_fn(node, client)
    result = node_fn(
        {"slots": {"svc": None}, "current_state": "", "last_user_message": "quiero alguien que lleve a mi bebé"}
    )
    assert result["slots"]["svc"] == "surrogacy"


def test_registration_node_store_resolves_conditional_line_via_llm():
    """
Live-piloting regression: `scheduling.yaml`'s `SC_FIX` exists purely

    to apply a name/phone/email/date correction and did nothing — its DO
        lines were conditional prose, never a recognized STORE assignment.

    Returns:
        None.
"""
    node = GraphNode(
        node_id="SC_FIX",
        node_type="registration",
        do=["If the correction is the name, update [c_name]; the phone, [c_phone]; the email, [c_email]."],
        store=["[success] = NULL"],
    )
    client = _FakeLLMClient(
        structured_reply={
            "c_name": {"applies": True, "value": "Alex Nuevo"},
            "c_phone": {"applies": False, "value": None},
            "c_email": {"applies": False, "value": None},
        }
    )
    node_fn = _build_node_fn(node, client)
    result = node_fn(
        {
            "slots": {"c_name": "Alex", "c_phone": "+15551234567", "c_email": "alex@example.com", "success": True},
            "current_state": "",
            "last_user_message": "mi nombre está mal, es Alex Nuevo",
        }
    )
    assert result["slots"]["c_name"] == "Alex Nuevo"
    assert result["slots"]["success"] is None  # the ordinary STORE line still applies too


def test_action_node_do_lines_excluded_from_conditional_mutations():
    """
`action` node DO lines are entirely owned by `_bind_tool_inputs` —

    a tool-argument hint like `nationalities = [nat]` must never also be
        treated as a conditional slot mutation, or every tool call would fire
        an extra, unnecessary LLM call.

    Returns:
        None.
"""
    node = GraphNode(node_id="RUN", node_type="action", do=["Send nationalities = [nat]."], execute=None)
    client = _FakeLLMClient()  # extract_structured raises if called
    node_fn = _build_node_fn(node, client)
    result = node_fn({"slots": {"nat": "Venezuela"}, "current_state": "", "last_user_message": "Venezuela"})
    assert client.structured_prompts == []
    assert "nationalities" not in result["slots"]


def test_eval_llm_decision_node_do_lines_excluded_from_conditional_mutations():
    """
Regression test, found live: SC_DEC_S's real DO line — "Map [slot] to

    the exact object in [available_slots]. It is valid only if that object
        has start_co and end_co." — isn't a compare/validate/check/ensure/
        verify/confirm-prefixed line, so the narrower verb-list guard
        (`_is_comparison_only_line`) let it through. The model "applied" it,
        nulling out `available_slots` (a list of real appointment objects) and
        silently derailing a real booking into objections. Every real `eval:
        "llm"` decision node's DO lines in this agent are validation prose for
        its own route judgment, never a mutation instruction — checking the
        node's own `eval` field is the structural fix a verb blacklist can
        never be complete enough to replace.

    Returns:
        None.
"""
    node = GraphNode(
        node_id="SC_DEC_S",
        node_type="decision",
        eval="llm",
        do=["Map [slot] to the exact object in [available_slots]. It is valid only if that object has start_co and end_co."],
    )
    client = _FakeLLMClient()  # extract_structured raises if called
    node_fn = _build_node_fn(node, client)
    slots = {"slot": "16:00", "available_slots": [{"start_co": "2026-09-22T10:00:00-05:00"}]}
    result = node_fn({"slots": slots, "current_state": "", "last_user_message": "a las 16"})
    assert client.structured_prompts == []
    assert result["slots"]["available_slots"] == [{"start_co": "2026-09-22T10:00:00-05:00"}]


def test_eval_llm_exclusion_applies_to_any_node_type_not_only_decision():
    """
`eval` is a route-evaluation property of any node type, not

    decision-exclusive — real content has `eval: "llm"` on `registration`
        (`AM_INIT`) and `question` (`AM_ASK_NAME`) nodes too. The first version
        of this fix only checked `node_type == "decision"`, leaving those node
        types exposed to the exact same corruption if a future validation-only
        DO line ever landed on one of them.

    Returns:
        None.
"""
    node = GraphNode(
        node_id="AM_INIT",
        node_type="registration",
        eval="llm",
        do=["Map [name] to the exact contact record. It is valid only if the record has an email."],
        store=[],
    )
    client = _FakeLLMClient()  # extract_structured raises if called
    node_fn = _build_node_fn(node, client)
    slots = {"name": "Alex", "contact_record": {"id": 1}}
    result = node_fn({"slots": slots, "current_state": "", "last_user_message": "Alex"})
    assert client.structured_prompts == []
    assert result["slots"]["contact_record"] == {"id": 1}


# ---------------------------------------------------------------------------
# _make_render_say — say_verbatim=false blocks are paraphrased naturally via
# the LLM on every render, never cached (requested directly, 2026-09-16:
# real content read as scripted/repetitive, especially a question re-asked
# verbatim byte-for-byte after a failed capture).
# ---------------------------------------------------------------------------


def test_render_say_verbatim_block_returns_raw_text_without_calling_llm():
    client = _FakeLLMClient()  # complete() would return "" by default; assert no call at all
    render_say = _make_render_say(client)
    result = render_say("N", ["Exact legal copy."], True, "es", {})
    assert result == "Exact legal copy."
    assert client.prompts == []


def test_render_say_non_verbatim_block_calls_llm_even_without_a_language_code():
    client = _FakeLLMClient(reply="Rephrased greeting.")
    render_say = _make_render_say(client)
    result = render_say("N", ["Hola, bienvenido."], False, None, {})
    assert result == "Rephrased greeting."
    assert len(client.prompts) == 1


def test_render_say_interpolates_slots_before_sending_to_llm():
    client = _FakeLLMClient(reply="Rephrased with name.")
    render_say = _make_render_say(client)
    render_say("N", ["Hola [name]."], False, "es", {"name": "Alex"})
    assert "Hola Alex." in client.prompts[0]


def test_render_say_never_caches_across_repeated_calls():
    """
Regression test: the old cache keyed on (node_id, language_code, raw

    text) meant the exact same node re-rendered on a retry loop always
        returned the identical text — which is precisely the case where the
        scripted-repeat feel was most noticeable (a fallback re-asking the same
        pending question). Each render is now its own LLM call.

    Returns:
        None.
"""
    client = _FakeLLMClient(reply="Rephrased.")
    render_say = _make_render_say(client)
    render_say("SAME_NODE", ["Same question?"], False, "es", {})
    render_say("SAME_NODE", ["Same question?"], False, "es", {})
    assert len(client.prompts) == 2


def test_render_say_falls_back_to_raw_when_llm_returns_empty():
    client = _FakeLLMClient(reply="")
    render_say = _make_render_say(client)
    result = render_say("N", ["Hola."], False, "es", {})
    assert result == "Hola."


def test_render_say_prompt_forbids_a_meta_commentary_preamble():
    """
Regression test: live-testing occasionally caught the model prefacing

    a paraphrase with something like "Claro, aquí tienes una versión más
        conversacional del mensaje:" instead of just the rephrased text — a
        real, user-visible defect. Only checks the prompt carries the explicit
        rule against it; the model's actual compliance is a live-testing
        concern, not something a fake-client unit test can assert on.

    Returns:
        None.
"""
    client = _FakeLLMClient(reply="Hola, ¿cómo estás?")
    render_say = _make_render_say(client)
    render_say("N", ["Hola."], False, "es", {})
    assert "no preamble" in client.prompts[0]


def test_render_say_requests_a_non_deterministic_temperature():
    """
`complete()` now defaults to `temperature=0.0` (2026-09-17) — correct

    for every other caller's factual judgment call, but wrong here: a
        paraphrase at temperature 0 tends toward the single most-likely
        rewording, defeating the point of the 2026-09-16 naturalization fix.
        This is the one caller that must opt out of the new default.

    Returns:
        None.
"""
    client = _FakeLLMClient(reply="Buenas, ¿qué tal?")
    render_say = _make_render_say(client)
    render_say("N", ["Hola?"], False, "es", {})
    assert client.temperatures == [1.0]


def test_render_say_retries_a_discarded_rewording_before_sending_the_original():
    """A rewording that adds a question is discarded; the original is in the template's language, so one retry comes first."""

    class _Client(_FakeLLMClient):
        def complete(self, prompt, temperature=0.0):
            self.temperatures.append(temperature)
            return "Hola, ¿cómo estás?" if temperature == 1.0 else "Hola, buenas."

    client = _Client()
    render_say = _make_render_say(client)
    assert render_say("N", ["Hello."], False, "es", {}) == "Hola, buenas."
    assert client.temperatures == [1.0, 0.0]


def test_render_say_sends_the_original_when_both_rewordings_are_discarded():
    client = _FakeLLMClient(reply="Hola, ¿cómo estás?")
    render_say = _make_render_say(client)
    assert render_say("N", ["Hello."], False, "es", {}) == "Hello."


def test_apply_store_line_pick_resolves_the_start_co_of_the_day_and_time_in_start_local():
    slots = {
        "available_slots": [
            {"start_co": "2026-10-30T07:00:00-05:00", "start_local": "2026-10-30T19:00:00+07:00"},
            {"start_co": "2026-10-30T09:00:00-05:00", "start_local": "2026-10-30T21:00:00+07:00"},
            {"start_co": "2026-10-31T09:00:00-05:00", "start_local": "2026-10-31T21:00:00+07:00"},
        ],
        "day": "2026-10-30",
        "slot": "21:00",
    }
    _apply_store_line("[start_date] = PICK [available_slots].start_co AT [day] [slot]", _ctx(slots), _FakeLLMClient())
    assert slots["start_date"] == "2026-10-30T09:00:00-05:00"


def test_apply_store_line_pick_is_empty_when_nothing_matches_exactly():
    slots = {
        "available_slots": [{"start_co": "2026-10-30T09:00:00-05:00", "start_local": "2026-10-30T21:00:00+07:00"}],
        "day": "2026-10-30",
        "slot": "21:10",
    }
    _apply_store_line("[start_date] = PICK [available_slots].start_co AT [day] [slot]", _ctx(slots), _FakeLLMClient())
    assert slots["start_date"] is None


# ---------------------------------------------------------------------------
# _interpolate_slots
# ---------------------------------------------------------------------------


def test_interpolate_slots_substitutes_known_value():
    assert _interpolate_slots("Hello [name]!", {"name": "Alex"}) == "Hello Alex!"


def test_interpolate_slots_leaves_unknown_slot_as_bracket_token():
    assert _interpolate_slots("Hello [name]!", {}) == "Hello [name]!"


def test_interpolate_slots_leaves_none_valued_slot_as_bracket_token():
    assert _interpolate_slots("Hello [name]!", {"name": None}) == "Hello [name]!"


def test_interpolate_slots_formats_list_of_appointment_dicts_without_a_parseable_date_as_the_old_raw_dump():
    """
Safety net, not the common case: real `[available_slots]` objects always

    carry a full ISO `start_local`/`start_co` (`"2026-09-22T09:00:00-05:00"`) —
        a bare time with no date part is a shape `_format_appointment_list` can't
        apply its day/time logic to at all, so it falls back to the pre-2026-09-17
        raw dump rather than silently showing nothing.

    Returns:
        None.
"""
    slots = {
        "slots_list": [
            {"start_local": "09:00", "end_local": "09:30"},
            {"start_local": "13:00", "end_local": "13:30"},
        ]
    }
    result = _interpolate_slots("Available: [slots_list]", slots)
    assert result == "Available: 09:00 - 09:30; 13:00 - 13:30"


# ---------------------------------------------------------------------------
# _interpolate_slots — [available_slots] day/time display (2026-09-17): the
# root-cause fix for SC_DAYS/SC_HOURS dumping raw "start - end; ..." text
# regardless of what their say_verbatim: true goal: actually asked for.
# Mechanical, zero-LLM, auto-detecting which transformation applies from
# slots already captured — no new DSL syntax, no hardcoded slot names.
# ---------------------------------------------------------------------------


def _appointment(date: str, time: str) -> dict:
    return {
        "start_local": f"{date}T{time}:00-05:00",
        "end_local": f"{date}T{time}:00-05:00",
        "start_co": f"{date}T{time}:00-05:00",
        "end_co": f"{date}T{time}:00-05:00",
    }


def test_interpolate_slots_shows_unique_dates_when_no_slot_names_one_of_them():
    """
SC_DAYS's shape: [available_slots] interpolated before [day] is ever

    captured — no other slot could possibly name one of the dates, so the
        only sensible display is the list of distinct days on offer.

    Returns:
        None.
"""
    slots = {
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-22", "10:00"),
            _appointment("2026-09-23", "14:00"),
        ]
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "🗓️ Martes 22 de septiembre\n └─ Mañana\n🗓️ Miércoles 23 de septiembre\n └─ Tarde"


def test_interpolate_slots_filters_to_times_when_a_slot_names_the_exact_iso_date():
    slots = {
        "day": "2026-09-22",
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-22", "10:00"),
            _appointment("2026-09-23", "14:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "Mañana\n🕐 09:00 a 10:00"


def test_interpolate_slots_filters_to_times_via_day_of_month_heuristic_when_unambiguous():
    """
SC_HOURS's real shape: [day] is `free_text`-captured ("el 22"), never

    guaranteed to be an ISO date — the fallback must still find it, as long
        as the day-of-month it names is unambiguous among the dates on offer.

    Returns:
        None.
"""
    slots = {
        "day": "el 22, por favor",
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-23", "14:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "Mañana\n🕐 09:00"


def test_interpolate_slots_day_of_month_heuristic_never_misfires_on_an_unrelated_number():
    """
A retry counter or phone-number slot must never accidentally filter

    the list — the heuristic only fires when a candidate slot's number
        uniquely identifies one date; here "22" doesn't appear standalone in
        any slot at all (the phone number is one contiguous digit run, matched
        by `\b\d{1,2}\b` never crossing into it), so this must fall through
        to showing every distinct date, not a wrong single-day filter.

    Returns:
        None.
"""
    slots = {
        "c_phone": "+15551234522",
        "svc_try": 3,
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-23", "14:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "🗓️ Martes 22 de septiembre\n └─ Mañana\n🗓️ Miércoles 23 de septiembre\n └─ Tarde"


def test_interpolate_slots_day_of_month_heuristic_never_misfires_on_a_compile_time_constant():
    """
Regression test, found live: `PROCESS_DURATION_MONTHS` (a compile-time

    constant, value `"24"`) was picked up by the day-of-month heuristic as if
        the user had already chosen the 24th — before `[day]` was ever asked —
        because one of the dates on offer happened to fall on the 24th too.
        SC_DAYS's very first display silently filtered down to just that one
        day's times instead of showing every date. A constant never represents
        something the user said, so it must never be treated as a candidate
        match, regardless of its value; the fix is name-based (constants are
        UPPER_SNAKE_CASE, real slots are lower_snake_case, an existing hard DSL
        rule), not specific to this one constant.

    Returns:
        None.
"""
    slots = {
        "PROCESS_DURATION_MONTHS": "24",
        "c_phone": "+573001234567",
        "c_name": "Tomas M",
        "available_slots": [
            _appointment("2026-09-22", "22:00"),
            _appointment("2026-09-23", "01:00"),
            _appointment("2026-09-24", "21:30"),
            _appointment("2026-09-25", "19:00"),
            _appointment("2026-09-26", "01:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == (
        "🗓️ Martes 22 de septiembre\n └─ Noche\n"
        "🗓️ Miércoles 23 de septiembre\n └─ Madrugada\n"
        "🗓️ Jueves 24 de septiembre\n └─ Noche\n"
        "🗓️ Viernes 25 de septiembre\n └─ Noche\n"
        "🗓️ Sábado 26 de septiembre\n └─ Madrugada"
    )


def test_interpolate_slots_day_of_month_heuristic_skips_ambiguous_matches():
    """
Two different offered dates share day-of-month 22 (a 22nd next month) —

    a bare "22" can't disambiguate between them, so this must not guess.

    Returns:
        None.
"""
    slots = {
        "day": "22",
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-10-22", "14:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "🗓️ Martes 22 de septiembre\n └─ Mañana\n🗓️ Jueves 22 de octubre\n └─ Tarde"


def test_interpolate_slots_date_reference_slots_do_not_pick_a_day():
    """
A `now` timestamp and a `calendar` list of dates are references, not the

    day the contact chose, so the day list must still show the dates on offer.

    Returns:
        None.
"""
    slots = {
        "now": "2026-10-27T10:56:57-06:00",
        "calendar": "2026-10-27 Tuesday, 2026-10-28 Wednesday, 2026-10-29 Thursday, 2026-10-30 Friday",
        "available_slots": [
            _appointment("2026-10-27", "09:00"),
            _appointment("2026-10-29", "14:00"),
            _appointment("2026-10-30", "10:00"),
        ],
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "🗓️ Martes 27 de octubre\n └─ Mañana\n🗓️ Jueves 29 de octubre\n └─ Tarde\n🗓️ Viernes 30 de octubre\n └─ Mañana"


def test_interpolate_slots_appointment_list_skips_the_matching_date_when_only_one_date_is_offered():
    """
When `get_available_slots` already returned only one day's worth of

    slots, there's nothing to filter — go straight to times without needing
        any other slot to name the date.

    Returns:
        None.
"""
    slots = {
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-22", "10:00"),
        ]
    }
    result = _interpolate_slots("[available_slots]", slots)
    assert result == "Mañana\n🕐 09:00 a 10:00"


def test_interpolate_slots_formats_dates_in_english_when_language_code_is_en():
    slots = {
        "available_slots": [
            _appointment("2026-09-22", "09:00"),
            _appointment("2026-09-23", "14:00"),
        ]
    }
    result = _interpolate_slots("[available_slots]", slots, "en")
    assert result == "🗓️ Tuesday, September 22\n └─ Morning\n🗓️ Wednesday, September 23\n └─ Afternoon"


def test_interpolate_slots_substitutes_a_constant_reference():
    """
Regression test: `<AGENT_NAME>`/`<COMPANY_NAME>`-style constant

    references (`initial_slots()` already seeds every `RuntimeArtifact.
        constants` entry into `slots` under its exact uppercase name) showed
        up literally, unresolved, in every real conversation this whole
        session — `_interpolate_slots` only ever matched `[lower_snake]`
        slot references, never `<UPPER_SNAKE>` constant ones, even though the
        value was one dict lookup away the entire time.

    Returns:
        None.
"""
    assert _interpolate_slots("Soy <AGENT_NAME>.", {"AGENT_NAME": "Sam"}) == "Soy Sam."


def test_interpolate_slots_leaves_unknown_constant_as_angle_bracket_token():
    assert _interpolate_slots("Soy <AGENT_NAME>.", {}) == "Soy <AGENT_NAME>."


def test_interpolate_slots_substitutes_both_forms_in_the_same_text():
    slots = {"AGENT_NAME": "Sam", "name": "Alex"}
    result = _interpolate_slots("Soy <AGENT_NAME>, hablando con [name].", slots)
    assert result == "Soy Sam, hablando con Alex."


# ---------------------------------------------------------------------------
# _coerce_value / _json_schema_type / _capture_json_schema
# ---------------------------------------------------------------------------


def test_coerce_value_none_stays_none():
    assert _coerce_value(None, "str") is None


def test_coerce_value_bool_type():
    assert _coerce_value("true", "bool") is True


def test_coerce_value_int_type():
    assert _coerce_value("3", "int") == 3


def test_coerce_value_int_type_uncoercible_falls_back_to_raw():
    assert _coerce_value("not a number", "int") == "not a number"


def test_coerce_value_str_type_passthrough():
    assert _coerce_value("Alex", "str") == "Alex"


def test_json_schema_type_for_literal():
    schema = _json_schema_type("Literal[yes, no]")
    assert schema == {"type": ["string", "null"], "enum": ["yes", "no", None]}


def test_json_schema_type_for_bool():
    assert _json_schema_type("bool") == {"type": ["boolean", "null"]}


def test_json_schema_type_for_int():
    assert _json_schema_type("int") == {"type": ["integer", "null"]}


def test_json_schema_type_default_is_nullable_string():
    assert _json_schema_type("free_text") == {"type": ["string", "null"]}


def test_capture_json_schema_marks_every_slot_required():
    schema = _capture_json_schema([("name", "str"), ("age", "int")])
    assert schema["required"] == ["name", "age"]
    assert set(schema["properties"]) == {"name", "age"}


# ---------------------------------------------------------------------------
# _llm_extract_capture — history (2026-09-17, requested directly: extend the
# same context-grounding already given to match_global_router to capture
# nodes too) and slots (2026-09-17, found live: a `free_text` capture like
# `[day]` has no way to normalize "el 22" against the real dates in
# `[available_slots]` without seeing it — this call site was the one
# decision function that never received known slot values at all).
# ---------------------------------------------------------------------------


def test_llm_extract_capture_omits_history_block_when_not_given():
    client = _FakeLLMClient(structured_reply={"profile": "couple"})
    _llm_extract_capture(
        client, [("profile", "str")], _ctx(goal=["Goal."], last_user_message="en pareja", pending_question="Ask?")
    )
    assert "Recent conversation" not in client.structured_prompts[0]


def test_llm_extract_capture_includes_history_when_given():
    client = _FakeLLMClient(structured_reply={"profile": "couple"})
    history = ["agent: ¿Deseas hacer el proceso en pareja?", "user: en pareja"]
    _llm_extract_capture(
        client,
        [("profile", "str")],
        _ctx(goal=["Goal."], history=history, last_user_message="en pareja", pending_question="Ask?"),
    )
    prompt = client.structured_prompts[0]
    assert "agent: ¿Deseas hacer el proceso en pareja?" in prompt


def test_llm_extract_capture_includes_known_slots():
    """
The gap found live while designing the `[available_slots]` day/time

    display fix: without `slots`, a `free_text` capture of `[day]` (e.g. the
        user says "el 22") has no way to normalize against the real dates
        actually on offer in `[available_slots]` — it can only echo the user's
        raw wording back.

    Returns:
        None.
"""
    client = _FakeLLMClient(structured_reply={"day": "2026-09-22"})
    slots = {"available_slots": [{"start_local": "2026-09-22T09:00:00-05:00"}]}
    _llm_extract_capture(
        client, [("day", "str")], _ctx(slots, last_user_message="el 22", pending_question="¿Qué día prefieres?")
    )
    prompt = client.structured_prompts[0]
    assert "2026-09-22T09:00:00-05:00" in prompt


# ---------------------------------------------------------------------------
# _coerce_constant / initial_slots / fresh_state
# ---------------------------------------------------------------------------


def test_coerce_constant_numeric_string_becomes_int():
    assert _coerce_constant("3") == 3


def test_coerce_constant_non_numeric_stays_string():
    assert _coerce_constant("America/Bogota") == "America/Bogota"


def test_initial_slots_seeds_every_constant():
    spec = build_minimal_agent_spec(
        constants=[ConstantItem(name="MAX_RETRY_ATTEMPTS", description="d", value="3")]
    )
    artifact = render_runtime_artifact(spec)
    slots = initial_slots(artifact)
    assert slots == {"MAX_RETRY_ATTEMPTS": 3, "current_state": ""}


def test_fresh_state_has_empty_current_state_and_seeded_slots():
    spec = build_minimal_agent_spec(
        constants=[ConstantItem(name="MAX_RETRY_ATTEMPTS", description="d", value="3")]
    )
    artifact = render_runtime_artifact(spec)
    state = fresh_state(artifact)
    assert state["current_state"] == ""
    assert state["last_user_message"] == ""
    assert state["slots"] == {"MAX_RETRY_ATTEMPTS": 3, "current_state": ""}
    assert state["last_message_at"]


# ---------------------------------------------------------------------------
# _sync_language_change — pushes a router-driven language change to the CRM
# ---------------------------------------------------------------------------


def test_sync_language_change_calls_update_custom_field_when_language_changed():
    calls = []
    executors = {"update_custom_field": lambda **kw: calls.append(kw) or {"success": True}}
    _sync_language_change(
        "English", {"preferred_language": "Spanish"}, {"contact_id": "c1", "location_id": "l1"}, executors
    )
    assert calls == [{"name": "language", "value": "Spanish", "contact_id": "c1", "location_id": "l1"}]


def test_sync_language_change_skips_when_unchanged_or_no_contact_or_no_tool():
    calls = []
    executors = {"update_custom_field": lambda **kw: calls.append(kw)}
    contact = {"contact_id": "c1"}
    _sync_language_change("Spanish", {"preferred_language": "es"}, contact, executors)
    _sync_language_change("English", {"preferred_language": "Spanish"}, contact, {})
    assert calls == []


def test_sync_language_change_still_calls_tool_without_contact_ids():
    calls = []
    executors = {"update_custom_field": lambda **kw: calls.append(kw)}
    _sync_language_change("English", {"preferred_language": "Spanish"}, {}, executors)
    assert calls == [{"name": "language", "value": "Spanish"}]


def test_sync_language_change_swallows_tool_failure():
    def boom(**kw):
        raise RuntimeError("ghl down")

    _sync_language_change("English", {"preferred_language": "Spanish"}, {"contact_id": "c1"}, {"update_custom_field": boom})


# ---------------------------------------------------------------------------
# list[...] type_exprs — schema shape and text-to-list coercion
# ---------------------------------------------------------------------------

_DOC_LIST_TYPE = "list[Literal[cedula_ciudadania, ppt, pasaporte]]"


def test_json_schema_type_maps_list_of_literal_to_an_enum_array():
    schema = _json_schema_type(_DOC_LIST_TYPE)
    assert schema == {
        "type": ["array", "null"],
        "items": {"type": "string", "enum": ["cedula_ciudadania", "ppt", "pasaporte"]},
    }
    assert _json_schema_type("list[str]") == {"type": ["array", "null"], "items": {"type": "string"}}


def test_coerce_value_turns_stringified_lists_into_real_lists():
    assert _coerce_value('["pasaporte", "ppt"]', _DOC_LIST_TYPE) == ["pasaporte", "ppt"]
    assert _coerce_value("pasaporte, ppt", _DOC_LIST_TYPE) == ["pasaporte", "ppt"]
    assert _coerce_value(["ppt"], _DOC_LIST_TYPE) == ["ppt"]
    assert _coerce_value("ppt", _DOC_LIST_TYPE) == ["ppt"]
    assert _coerce_value(None, _DOC_LIST_TYPE) is None


def test_mechanical_arg_bindings_resolve_the_last_argument_before_a_closing_paren():
    bindings = _extract_mechanical_arg_bindings(
        ["TOOL CALL: call check_documentation (nationality=[nat], document_type=[docs])."],
        {"nat": "VEN", "docs": ["pasaporte", "ppt"]},
    )
    assert bindings == {"nationality": "VEN", "document_type": ["pasaporte", "ppt"]}


# ---------------------------------------------------------------------------
# `[x] = match in <CONSTANT> | 'fallback'` — mechanical list match
# ---------------------------------------------------------------------------

_CITIES = "Bogotá, Soacha, Zipaquirá, Chía, La Calera, Cota y Sibaté"
_MATCH_LINE = "[city] = match in <ALLOWED_CITIES> | 'Otro'"


def _match_in_slots(city):
    return {"ALLOWED_CITIES": _CITIES, "city": city}


def test_match_in_canonicalizes_ignoring_accents_and_case_without_the_llm():
    slots = _match_in_slots("bogota")
    _apply_store_line(_MATCH_LINE, _ctx(slots), _FakeLLMClient())
    assert slots["city"] == "Bogotá"
    slots = _match_in_slots("  LA CALERA ")
    _apply_store_line(_MATCH_LINE, _ctx(slots), _FakeLLMClient())
    assert slots["city"] == "La Calera"
    slots = _match_in_slots("sibate")  # last item, after the " y " separator
    _apply_store_line(_MATCH_LINE, _ctx(slots), _FakeLLMClient())
    assert slots["city"] == "Sibaté"


def test_match_in_uses_the_fallback_for_a_value_outside_the_list():
    slots = _match_in_slots("Medellín")
    _apply_store_line(_MATCH_LINE, _ctx(slots), _FakeLLMClient())
    assert slots["city"] == "Otro"


def test_match_in_leaves_an_empty_slot_untouched():
    slots = _match_in_slots(None)
    _apply_store_line(_MATCH_LINE, _ctx(slots), _FakeLLMClient())
    assert slots["city"] is None



def test_interpolate_slots_fills_contact_placeholders_and_keeps_missing_ones():
    """
`{{contact.field}}` is filled from the session's CRM contact, like `[slot]`.

    A field the contact lacks stays as written instead of being blanked.

    Returns:
        None.
"""
    text = "Hola {{contact.name}}, escribimos a {{ contact.email }} o {{contact.phone}}"

    result = _interpolate_slots(text, {}, contact={"name": "Tomas", "email": "t@x.co", "phone": None})

    assert result == "Hola Tomas, escribimos a t@x.co o {{contact.phone}}"


def test_render_say_keeps_contact_values_out_of_the_paraphrase():
    """
The paraphrasing model never sees the contact's real name, only a token,

    so it cannot rewrite it (e.g. add an accent); the real value is restored after.

    Returns:
        None.
"""
    prompts = []

    class _AccentAddingLLM:
        def complete(self, prompt, *, temperature=0.0):
            prompts.append(prompt)
            return "Qué tal <CONTACT_FIRST_NAME>, soy Sofía."

    render_say = _make_render_say(_AccentAddingLLM())

    result = render_say("OP_ASK_WHO", ["Hola {{contact.first_name}}, soy Sofia."], False, "Spanish", {}, contact={"first_name": "Tomas"})

    assert result == "Qué tal Tomas, soy Sofía."
    assert "Tomas" not in prompts[0] and "<CONTACT_FIRST_NAME>" in prompts[0]


def _action_node_fn(node: GraphNode, executor):
    return _make_node_fn(
        node,
        _FakeLLMClient(),
        router=GlobalRouterDefinition(handlers=[], faqs=[]),
        node_by_id={},
        render_say=lambda *args, **kwargs: "",
        resolve_edges=lambda *args: None,
        tool_executors={"sync": executor},
        tool_input_fields={},
        say_callback=lambda text: None,
    )


def _failing_tool(**kwargs):
    from agent_runtime.runtime.tool_executor import ToolExecutionError

    raise ToolExecutionError("HTTP 500")


def test_action_node_that_captures_nothing_survives_a_tool_failure():
    """
A fire-and-forget tool call (a CRM sync) has no result to route on, so its

    failure must not end the conversation.

    Returns:
        None.
"""
    node = GraphNode(node_id="SYNC", node_type="action", execute="sync", capture=[])

    result = _action_node_fn(node, _failing_tool)({"slots": {}, "current_state": "", "last_user_message": ""})

    assert result["current_state"] == "SYNC"


def test_action_node_that_captures_a_result_still_raises_on_a_tool_failure():
    """
A node that routes on the tool's result cannot continue without it.

    Returns:
        None.
"""
    import pytest

    from agent_runtime.runtime.tool_executor import ToolExecutionError

    node = GraphNode(node_id="RUN", node_type="action", execute="sync", capture=[("success", "boolean")])

    with pytest.raises(ToolExecutionError):
        _action_node_fn(node, _failing_tool)({"slots": {}, "current_state": "", "last_user_message": ""})


def test_action_capture_takes_the_longest_matching_result_key_for_a_namespaced_slot():
    """
`q__eligibility_result` ends with both `result` and `eligibility_result`:

    each namespaced slot must get its own key's value, not the shorter key's.

    Returns:
        None.
"""
    node = GraphNode(
        node_id="RUN",
        node_type="action",
        execute="sync",
        capture=[("q__result", "string"), ("q__eligibility_result", "string")],
    )

    result = _action_node_fn(node, lambda **kwargs: {"result": "Rejected (Age)", "eligibility_result": "rejected"})(
        {"slots": {}, "current_state": "", "last_user_message": ""}
    )

    assert result["slots"]["q__result"] == "Rejected (Age)"
    assert result["slots"]["q__eligibility_result"] == "rejected"


def test_render_say_discards_a_paraphrase_that_balloons_past_the_original():
    invented = "Hola Ana, tengo estos días disponibles para tu cita: martes 10 y jueves 12. ¿Cuál prefieres para agendar?"
    client = _FakeLLMClient(reply=invented)
    render_say = _make_render_say(client)
    assert render_say("N", ["Hasta luego."], False, "es", {}) == "Hasta luego."


def test_render_say_discards_a_paraphrase_that_adds_a_question():
    client = _FakeLLMClient(reply="Hasta luego. ¿Algo más?")
    render_say = _make_render_say(client)
    assert render_say("N", ["Hasta luego."], False, "es", {}) == "Hasta luego."


def test_resolve_edges_llm_condition_before_an_unconditional_default_still_gets_judged():
    client = _FakeLLMClient(reply="0")
    resolve_edges = _make_resolve_edges(client)
    edges = [
        GraphEdge(target="SWITCH_LANGUAGE", condition_text="the message is clearly English", is_mechanical=False),
        GraphEdge(target="GREET", condition_text=None, is_mechanical=False),
    ]
    assert resolve_edges(edges, _ctx({})) == "SWITCH_LANGUAGE"
    assert len(client.prompts) == 1


def test_resolve_edges_unconditional_default_wins_when_no_llm_condition_applies():
    client = _FakeLLMClient(reply="NONE")
    resolve_edges = _make_resolve_edges(client)
    edges = [
        GraphEdge(target="SWITCH_LANGUAGE", condition_text="the message is clearly English", is_mechanical=False),
        GraphEdge(target="GREET", condition_text=None, is_mechanical=False),
    ]
    assert resolve_edges(edges, _ctx({})) == "GREET"


def test_coerce_value_turns_the_word_null_into_an_empty_value_except_for_literals():
    from agent_runtime.runtime.graph_builder import _coerce_value

    assert _coerce_value("null", "email") is None
    assert _coerce_value("None", "free_text") is None
    assert _coerce_value("none", "Literal[ivf, surrogacy, none]") == "none"
    assert _coerce_value("21:00", "appointment_slot_selection") == "21:00"


def test_coerce_value_writes_a_chosen_time_as_24_hour_hh_mm():
    from agent_runtime.runtime.graph_builder import _coerce_value

    assert _coerce_value("9:40 am", "appointment_slot_selection") == "09:40"
    assert _coerce_value("3:05 pm", "appointment_slot_selection") == "15:05"
    assert _coerce_value("2026-11-04T09:40:00-05:00", "appointment_slot_selection") == "09:40"
    assert _coerce_value("10", "appointment_slot_selection") == "10"
    assert _coerce_value("1:10 de la tarde", "appointment_slot_selection") == "13:10"
    assert _coerce_value("9:40 de la mañana", "appointment_slot_selection") == "09:40"
    assert _coerce_value("3 pm", "appointment_slot_selection") == "15:00"
    assert _coerce_value("3 de la tarde", "appointment_slot_selection") == "15:00"
    assert _coerce_value("12:30 am", "appointment_slot_selection") == "00:30"
    assert _coerce_value("12:30 pm", "appointment_slot_selection") == "12:30"
    assert _coerce_value("9:40 amazing", "appointment_slot_selection") == "09:40"


def test_missing_required_inputs_lists_only_required_ones_without_a_value():
    from types import SimpleNamespace

    from agent_runtime.runtime.graph_builder import _missing_required_inputs

    fields = [SimpleNamespace(name="start_date", required=True), SimpleNamespace(name="note", required=False)]
    assert _missing_required_inputs(fields, {"start_date": None}) == ["start_date"]
    assert _missing_required_inputs(fields, {"start_date": "2026-11-04T09:40:00-05:00"}) == []


def test_render_say_cuts_a_closing_question_the_rewording_added():
    reply = "Estos son los horarios:\n\n<NUM_1>\n<NUM_2>\n\n¿Cuál prefieres?"
    client = _FakeLLMClient(reply=reply)
    render_say = _make_render_say(client)
    out = render_say("N", ["These are the times:\n\n09:00\n10:00"], False, "es", {})
    assert out == "Estos son los horarios:\n\n09:00\n10:00"


def test_render_say_discards_a_rewording_that_changes_a_time():
    class _Client(_FakeLLMClient):
        def complete(self, prompt, *, temperature=0.0):
            self.temperatures.append(temperature)
            return "Hora: 16:00" if temperature == 1.0 else "Hora: <NUM_1>"

    client = _Client()
    render_say = _make_render_say(client)
    assert render_say("N", ["Time: 04:00"], False, "es", {}) == "Hora: 04:00"


_CALENDAR = "2026-10-27 Tuesday{n}2026-10-28 Wednesday{n}2026-10-29 Thursday{n}2026-10-30 Friday{n}2026-10-31 Saturday{n}2026-11-01 Sunday{n}2026-11-02 Monday{n}2026-11-03 Tuesday{n}2026-11-04 Wednesday{n}2026-11-05 Thursday".format(n=chr(10))
_OFFERED = [{"start_local": f"2026-{d}T09:00:00-05:00"} for d in ("10-30", "11-03", "11-04", "11-05")]


def test_resolve_day_reference_reads_weekdays_in_three_languages():
    from agent_runtime.runtime.graph_builder import _resolve_day_reference

    for reply in ("el viernes", "sexta", "Friday", "this coming friday"):
        assert _resolve_day_reference(reply, _CALENDAR, _OFFERED) == "2026-10-30"
    assert _resolve_day_reference("quarta", _CALENDAR, _OFFERED) == "2026-11-04"


def test_resolve_day_reference_reads_numbers_months_and_relative_days():
    from agent_runtime.runtime.graph_builder import _resolve_day_reference

    assert _resolve_day_reference("dia 3 de novembro", _CALENDAR, _OFFERED) == "2026-11-03"
    assert _resolve_day_reference("Nov 5", _CALENDAR, _OFFERED) == "2026-11-05"
    assert _resolve_day_reference("el 30", _CALENDAR, _OFFERED) == "2026-10-30"
    assert _resolve_day_reference("hoy", _CALENDAR, _OFFERED) == "2026-10-27"
    assert _resolve_day_reference("tomorrow", _CALENDAR, _OFFERED) == "2026-10-28"
    assert _resolve_day_reference("2026-11-04", _CALENDAR, _OFFERED) == "2026-11-04"


def test_resolve_day_reference_is_empty_when_no_real_day_is_named():
    from agent_runtime.runtime.graph_builder import _resolve_day_reference

    assert _resolve_day_reference("banana", _CALENDAR, _OFFERED) is None
    assert _resolve_day_reference("el 31 de febrero", _CALENDAR, _OFFERED) is None
    assert _resolve_day_reference("viernes", None, _OFFERED) is None


def test_day_label_follows_the_conversation_language():
    from agent_runtime.runtime.graph_builder import _day_label

    assert _day_label("2026-10-30", "Spanish") == "viernes 30 de octubre"
    assert _day_label("2026-10-30", "English") == "Friday, October 30"
    assert _day_label("2026-10-30", "Portuguese") == "sexta-feira 30 de outubro"
    assert _day_label(None, "Spanish") is None


def test_is_bare_yes_no_only_accepts_plain_yes_no_replies():
    from agent_runtime.runtime.graph_builder import _is_bare_yes_no

    for reply in ("Sí", "no", "Claro, por favor", "de acuerdo", "Sim"):
        assert _is_bare_yes_no(reply)
    for reply in ("tengo 30 años", "sí, y cuánto cuesta", "", "FIV"):
        assert not _is_bare_yes_no(reply)


def test_blank_word_to_none_clears_the_word_null_only():
    from agent_runtime.runtime.graph_builder import _blank_word_to_none

    assert _blank_word_to_none("null") is None
    assert _blank_word_to_none(" None ") is None
    assert _blank_word_to_none("2026-11-04") == "2026-11-04"
    assert _blank_word_to_none(3) == 3


def test_coerce_value_rejects_an_incomplete_email_and_lowercases_a_valid_one():
    from agent_runtime.runtime.graph_builder import _coerce_value

    assert _coerce_value("juan@", "email") is None
    assert _coerce_value("sin arroba", "email") is None
    assert _coerce_value("  Marcela.Arango@Gmail.com ", "email") == "marcela.arango@gmail.com"


def test_coerce_value_rejects_a_phone_that_cannot_be_a_number():
    from agent_runtime.runtime.graph_builder import _coerce_value

    assert _coerce_value("123", "phone_number") is None
    assert _coerce_value("+57 300 701 1593", "phone_number") == "+573007011593"
    assert _coerce_value("0034 612-345-678", "phone_number") == "+34612345678"
    assert _coerce_value("3001234567", "phone_number") == "3001234567"


def test_correct_contact_email_replaces_the_kept_address_with_the_one_in_the_reply():
    from agent_runtime.runtime.graph_builder import _correct_contact_email

    slots = {"sc__c_email": "ana@gmial.com"}
    capture = [("sc__day", "free_text")]

    assert _correct_contact_email(slots, capture, "perdon, es Ana@Gmail.com.") == "sc__c_email"
    assert slots["sc__c_email"] == "ana@gmail.com"


def test_correct_contact_email_leaves_everything_else_alone():
    from agent_runtime.runtime.graph_builder import _correct_contact_email

    capture = [("sc__day", "free_text")]
    for slots, cap, reply in (
        ({"sc__c_email": "ana@gmail.com"}, capture, "el 4 de noviembre"),
        ({"sc__c_email": "ana@gmail.com"}, capture, "es ana@gmail.com"),
        ({"sc__c_email": None}, capture, "es otra@gmail.com"),
        ({"other": "x"}, capture, "es otra@gmail.com"),
        ({"sc__c_email": "ana@gmail.com"}, [("sc__c_email", "email")], "es otra@gmail.com"),
        ({"sc__c_email": "ana@gmail.com"}, [("sc__ok", "Literal[yes, no]"), ("sc__fix", "free_text")], "es otra@gmail.com"),
    ):
        before = dict(slots)
        assert _correct_contact_email(slots, cap, reply) is None
        assert slots == before


def test_interpolate_slots_lists_booked_appointments_soonest_first_in_the_contacts_language():
    later = {"event_id": "b", "summary": "Consulta", "start_time": "2026-11-05T14:30:00-05:00", "calendar_type": "IVF"}
    sooner = {"event_id": "a", "summary": "Consulta", "start_time": "2026-11-03T10:00:00-05:00", "calendar_type": "IVF"}
    assert _interpolate_slots("[appointments]", {"appointments": [later, sooner]}, "es") == (
        "1. 📅 martes 3 de noviembre de 2026 🕐 10:00\n2. 📅 jueves 5 de noviembre de 2026 🕐 14:30"
    )
    assert _interpolate_slots("[app]", {"app": sooner}, "en") == "📅 Tuesday, November 3, 2026 🕐 10:00"


def test_interpolate_slots_formats_a_booked_appointment_kept_as_json_text():
    text = '{"event_id":"a","summary":"Consulta","start_time":"2026-11-03T10:00:00-05:00","calendar_type":"IVF"}'
    assert _interpolate_slots("[app]", {"app": text}, "es") == "📅 martes 3 de noviembre de 2026 🕐 10:00"


def test_interpolate_slots_joins_consecutive_times_into_ranges():
    times = ["07:00", "08:00", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]
    slots = {"available_slots": [_appointment("2026-09-22", t) for t in times]}
    assert _interpolate_slots("[available_slots]", slots) == "Mañana\n🕐 07:00\n🕐 08:00\n🕐 09:00 a 11:30\n\nTarde\n🕐 13:00 a 15:30"


def test_interpolate_slots_names_every_part_of_the_day_with_availability():
    slots = {"available_slots": [_appointment("2026-11-03", t) for t in ("04:00", "07:00", "14:00", "20:00")] + [_appointment("2026-11-04", "09:00")]}
    assert _interpolate_slots("[available_slots]", slots, "es") == (
        "🗓️ Martes 3 de noviembre\n └─ Madrugada · Mañana · Tarde · Noche\n🗓️ Miércoles 4 de noviembre\n └─ Mañana"
    )


def test_protect_lists_swaps_each_date_or_time_block_for_a_token_and_back():
    from agent_runtime.runtime.graph_builder import _protect_lists, _restore_contact_values

    protected: dict[str, str] = {}
    text = "Dates:\n\n📅 3 de noviembre de 2026 (tarde)\n📅 4 de noviembre de 2026 (mañana - tarde)\n\nWhich day?\n🕐 07:00 - 09:30 / 🕐 11:00"
    swapped = _protect_lists(text, protected)
    assert swapped == "Dates:\n\n<LIST_1>\n\nWhich day?\n<LIST_2>"
    assert _restore_contact_values(swapped, protected) == text


def _offered(day, *times):
    return [_appointment(day, t) for t in times]


def test_resolve_time_reference_accepts_only_unambiguous_offered_times():
    from agent_runtime.runtime.graph_builder import _resolve_time_reference

    offered = _offered("2026-11-04", "10:00", "10:30", "15:00", "16:00")
    assert _resolve_time_reference("10:30", offered, "2026-11-04") == "10:30"
    assert _resolve_time_reference("10:40", offered, "2026-11-04") is None
    assert _resolve_time_reference("a las 3", offered, "2026-11-04") == "15:00"
    assert _resolve_time_reference("3 pm", offered, "2026-11-04") == "15:00"
    assert _resolve_time_reference("a las 10", offered, "2026-11-04") == "10:00"
    assert _resolve_time_reference("a las 4", offered, "2026-11-04") == "16:00"
    assert _resolve_time_reference("a las 7", offered, "2026-11-04") is None
    assert _resolve_time_reference("a las 3", offered, "2026-11-05") is None
    both = _offered("2026-11-04", "03:00", "15:00")
    assert _resolve_time_reference("a las 3", both, "2026-11-04") is None
    assert _resolve_time_reference("15", both, "2026-11-04") == "15:00"


def test_protect_figures_swaps_times_and_long_numbers_for_tokens_and_back():
    from agent_runtime.runtime.graph_builder import _protect_figures, _restore_contact_values

    protected: dict[str, str] = {}
    text = "Our support is 360\u00b0: call +573001234567 before 16:00. Step 2 of 3."
    swapped = _protect_figures(text, protected)
    assert swapped == "Our support is <NUM_1>\u00b0: call +<NUM_2> before <NUM_3>. Step 2 of 3."
    assert _restore_contact_values(swapped, protected) == text


def test_render_say_falls_back_to_a_plain_translation_before_the_template_language():
    class _Client(_FakeLLMClient):
        def __init__(self):
            super().__init__()
            self.prompts = []

        def complete(self, prompt, *, temperature=0.0):
            self.prompts.append(prompt)
            return "¿Podrías decirme la hora? Gracias." if len(self.prompts) < 3 else "Lo siento, no entendí esa hora."

    client = _Client()
    render_say = _make_render_say(client)
    assert render_say("N", ["Sorry, I didn't understand that time."], False, "es", {}) == "Lo siento, no entendí esa hora."
    assert client.prompts[2].startswith("Translate this agent message")


def test_mechanical_arg_bindings_turn_a_language_name_into_its_uppercase_code():
    from agent_runtime.runtime.graph_builder import _extract_mechanical_arg_bindings

    line = "duration = 30. language = [preferred_language] in uppercase ('EN', 'ES', or 'PT'). iana_timezone = [user_timezone]."
    for name, code in (("English", "EN"), ("Spanish", "ES"), ("Portuguese", "PT")):
        bound = _extract_mechanical_arg_bindings([line], {"preferred_language": name, "user_timezone": "America/Bogota"})
        assert bound["language"] == code
    assert "language" not in _extract_mechanical_arg_bindings([line], {})


def test_hours_are_grouped_under_each_part_of_the_day_with_ranges_in_the_language():
    times = ["07:00", "08:00", "09:20", "09:40", "10:00", "10:20", "10:40", "11:00", "13:00", "13:20"]
    slots = {"available_slots": [_appointment("2026-11-09", t) for t in times]}
    assert _interpolate_slots("[available_slots]", slots, "es") == (
        "Mañana\n🕐 07:00\n🕐 08:00\n🕐 09:20 a 11:00\n\nTarde\n🕐 13:00 a 13:20"
    )
    assert _interpolate_slots("[available_slots]", slots, "en").splitlines()[3] == "🕐 09:20 to 11:00"


def test_location_label_asks_for_country_and_city_in_the_conversation_language():
    client = _FakeLLMClient("'Spain - Seville'\n")
    slots = {"user_location": "spian, sevila", "user_timezone": "Europe/Madrid", "preferred_language": "English"}
    _apply_store_line("[location_label] = LOCATION_LABEL [user_location]", _ctx(slots), client)
    assert slots["location_label"] == "Spain - Seville"
    assert "'spian, sevila'" in client.prompts[0] and "in English" in client.prompts[0]


def test_protect_place_swaps_the_location_label_for_a_token_and_back():
    from agent_runtime.runtime.graph_builder import _protect_place, _restore_contact_values

    protected: dict[str, str] = {}
    text = "- Time zone: Japan - Tokyo\n- Name: Ana"
    swapped = _protect_place(text, {"location_label": "Japan - Tokyo"}, protected)
    assert swapped == "- Time zone: <LIST_1>\n- Name: Ana"
    assert _restore_contact_values(swapped, protected) == text
    assert _protect_place(text, {"location_label": None}, {}) == text


def test_an_unpadded_time_without_am_or_pm_needs_only_one_offered_twin():
    from agent_runtime.runtime.graph_builder import _resolve_time_reference as resolve

    def offered(*times):
        return [{"start_local": f"2026-11-10T{t}:00+09:00"} for t in times]

    assert resolve("at 3:00", offered("03:00", "06:00"), "2026-11-10") == "03:00"
    assert resolve("3:00", offered("15:00"), "2026-11-10") == "15:00"
    assert resolve("3:00", offered("03:00", "15:00"), "2026-11-10") is None
    assert resolve("03:00", offered("03:00", "15:00"), "2026-11-10") == "03:00"
    assert resolve("3:00 pm", offered("03:00", "15:00"), "2026-11-10") == "15:00"
    assert resolve("10:30", offered("10:30", "22:30"), "2026-11-10") == "10:30"


def test_day_full_store_op_writes_the_weekday_day_and_month_with_a_capital():
    slots = {"day": "2026-11-10", "preferred_language": "Spanish"}
    _apply_store_line("[day_full] = DAY_FULL [day]", _ctx(slots), _FakeLLMClient())
    assert slots["day_full"] == "Martes 10 de noviembre"
    slots["preferred_language"] = "English"
    _apply_store_line("[day_full] = DAY_FULL [day]", _ctx(slots), _FakeLLMClient())
    assert slots["day_full"] == "Tuesday, November 10"


def test_the_summary_block_is_protected_as_one_list():
    from agent_runtime.runtime.graph_builder import _protect_lists

    block = "🗓️ Martes 10 de noviembre\n├─ 🕐 03:00 (24h)\n├─ 🌎 Japón - Tokio\n├─ 👤 Ana\n├─ ✉️ a@b.co\n└─ 📞 +5712345678"
    protected: dict[str, str] = {}
    assert _protect_lists(f"Before:\n\n{block}", protected) == "Before:\n\n<LIST_1>"
    assert protected["<LIST_1>"] == block


def test_location_label_is_empty_without_a_location():
    slots = {"user_location": None, "preferred_language": "Spanish"}
    _apply_store_line("[location_label] = LOCATION_LABEL [user_location]", _ctx(slots), _FakeLLMClient())
    assert slots["location_label"] is None


def test_day_title_store_op_capitalizes_the_day_label():
    slots = {"day": "2026-11-09", "preferred_language": "Spanish"}
    _apply_store_line("[day_title] = DAY_TITLE [day]", _ctx(slots), _FakeLLMClient())
    assert slots["day_title"] == "Lunes. 9 nov"
    slots["preferred_language"] = "English"
    _apply_store_line("[day_title] = DAY_TITLE [day]", _ctx(slots), _FakeLLMClient())
    assert slots["day_title"] == "Monday. Nov 9"
    slots["preferred_language"] = "Portuguese"
    _apply_store_line("[day_title] = DAY_TITLE [day]", _ctx(slots), _FakeLLMClient())
    assert slots["day_title"] == "Segunda-feira. 9 nov"


def test_protect_lists_also_covers_the_new_day_and_part_of_day_blocks():
    from agent_runtime.runtime.graph_builder import _protect_lists

    protected: dict[str, str] = {}
    text = "Hi\n\n🗓️ Martes 3 de noviembre\n └─ Mañana · Tarde\n\nTitle\n\nMañana\n🕐 07:00\n\nTarde\n🕐 13:00 a 13:30"
    assert _protect_lists(text, protected) == "Hi\n\n<LIST_1>\n\nTitle\n\n<LIST_2>\n\n<LIST_3>"


def test_lists_follow_the_language_name_held_in_preferred_language():
    slots = {"available_slots": [_appointment("2026-11-04", t) for t in ("09:00", "09:30", "14:00")]}
    assert _interpolate_slots("[available_slots]", slots, "English") == "Morning\n🕐 09:00 to 09:30\n\nAfternoon\n🕐 14:00"
    assert _interpolate_slots("[available_slots]", slots, "Portuguese") == "Manhã\n🕐 09:00 a 09:30\n\nTarde\n🕐 14:00"


def test_session_history_keeps_ten_lines_but_prompts_show_the_last_five():
    from agent_runtime.runtime.llm_client import PROMPT_HISTORY_LINES

    history: list[str] = []
    for i in range(14):
        history = _append_history(history, f"user: message {i}")
    assert len(history) == 10 and history[0] == "user: message 4"
    shown = _ctx({}, history=history).block()
    assert "message 13" in shown and "message 9" in shown
    assert "message 8" not in shown
    assert PROMPT_HISTORY_LINES == 5
