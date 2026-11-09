"""
Unit tests for agent_runtime.targets.langgraph.condition_parser — route/fallback classification.
"""
from __future__ import annotations

from agent_runtime.targets.langgraph.condition_parser import classify_rule

# ---------------------------------------------------------------------------
# Unconditional GO_TO
# ---------------------------------------------------------------------------


def test_unconditional_goto_is_code():
    result = classify_rule("GO_TO: CB_INIT")
    assert result.eval_class == "code"
    assert result.kind == "unconditional"
    assert result.target == "CB_INIT"


def test_unconditional_goto_dynamic_slot_target_is_code():
    result = classify_rule("GO_TO: [current_state]")
    assert result.eval_class == "code"
    assert result.target == "[current_state]"


# ---------------------------------------------------------------------------
# Canonical conditional forms -> code
# ---------------------------------------------------------------------------


def test_is_null_is_code():
    result = classify_rule("IF [num] IS NULL -> GO_TO: CB_ASK_NUM")
    assert result.eval_class == "code"
    assert result.target == "CB_ASK_NUM"


def test_is_not_null_is_code():
    result = classify_rule("IF [num] IS NOT NULL -> GO_TO: CB_HAS_TZ")
    assert result.eval_class == "code"


def test_comparison_against_quoted_string_is_code():
    result = classify_rule("IF [profile] == 'single_woman' -> GO_TO: VI_MENU_S")
    assert result.eval_class == "code"


def test_not_equal_is_code():
    result = classify_rule("IF [o__who] != 'yes' -> GO_TO: O__OP_PRIV")
    assert result.eval_class == "code"


def test_retry_counter_against_constant_is_code():
    result = classify_rule("IF [treat_try] >= <MAX_RETRY_ATTEMPTS> -> GO_TO: VI_ASK_KNOW_MULTI")
    assert result.eval_class == "code"


def test_in_scalar_membership_is_code():
    result = classify_rule(
        "IF [gestational_stage] IN [menos_de_20, mas_de_20, post_parto] -> GO_TO: TRIAGE_ASK_MAIN_REASON"
    )
    assert result.eval_class == "code"


def test_len_is_code():
    result = classify_rule("IF len([appointments]) > 1 -> GO_TO: AM_PICK_ONE")
    assert result.eval_class == "code"


def test_and_chain_is_code():
    result = classify_rule(
        "IF [knows] == 'no' AND [treat] == 'ivf_conventional' -> GO_TO: VI_EXPLAIN_CONV"
    )
    assert result.eval_class == "code"


def test_or_chain_is_code():
    result = classify_rule(
        "IF [reason] == 'past_date' OR [reason] == 'invalid_start_date' -> GO_TO: SC_DEC_T"
    )
    assert result.eval_class == "code"


def test_parenthesized_mixed_and_or_is_code():
    result = classify_rule(
        "IF ([a] != 'x' AND [a] != 'y') AND ([b] != 'x' AND [b] != 'y') -> GO_TO: AM_FIND"
    )
    assert result.eval_class == "code"


def test_true_false_uppercase_is_code():
    result = classify_rule("IF [success] == TRUE -> GO_TO: AM_CANCEL_OK")
    assert result.eval_class == "code"


def test_registered_matches_predicate_is_code():
    result = classify_rule(
        "IF [document_number] MATCHES numeric_string_without_spaces_or_punctuation -> GO_TO: TRIAGE_ASK_GESTATIONAL_STAGE"
    )
    assert result.eval_class == "code"


def test_code_result_exposes_python_expression():
    """
Needed by the LangGraph emitter to generate the real guard.

    Returns:
        None.
"""
    result = classify_rule("IF [num] IS NOT NULL -> GO_TO: CB_HAS_TZ")
    assert result.python_expression == "num is not None"


def test_llm_result_has_no_python_expression():
    result = classify_rule("IF call_answered -> GO_TO: CALL_ANSWERED")
    assert result.python_expression is None


def test_unconditional_goto_has_no_python_expression():
    result = classify_rule("GO_TO: CB_INIT")
    assert result.python_expression is None


def test_bracketed_slot_alone_is_code():
    """
A bracketed boolean-typed slot used as the whole condition is mechanical.

    Returns:
        None.
"""
    result = classify_rule("IF [confirmed] -> GO_TO: NEXT")
    assert result.eval_class == "code"


def test_mixed_and_or_uses_python_precedence_and_is_code():
    """
AND binds tighter than OR in real Python — no ambiguity, no parens required.

    Returns:
        None.
"""
    result = classify_rule("IF [a] == 'x' AND [b] == 'y' OR [c] == 'z' -> GO_TO: STATE")
    assert result.eval_class == "code"


# ---------------------------------------------------------------------------
# Non-canonical / non-mechanical forms -> llm (fall through under `auto`)
# ---------------------------------------------------------------------------


def test_lowercase_true_false_is_llm():
    result = classify_rule("IF [success] == true -> GO_TO: AM_CANCEL_OK")
    assert result.eval_class == "llm"


def test_null_literal_idiom_is_llm():
    result = classify_rule("IF {{contact.name}} == null -> GO_TO: AM_ASK_NAME")
    assert result.eval_class == "llm"


def test_missing_arrow_is_llm():
    result = classify_rule("IF [repeat_count] < <MAX_REPEAT_ATTEMPTS> GO_TO: [current_state]")
    assert result.eval_class == "llm"


def test_contains_any_of_is_llm():
    result = classify_rule(
        "IF [associated_symptoms] CONTAINS ANY OF [bleeding, fever] -> GO_TO: TRIAGE_MARK_URGENT_FINAL"
    )
    assert result.eval_class == "llm"


def test_unregistered_matches_predicate_is_llm():
    result = classify_rule("IF [x] MATCHES some_unregistered_name -> GO_TO: Y")
    assert result.eval_class == "llm"


def test_bare_flag_identifier_is_llm():
    result = classify_rule("IF call_answered -> GO_TO: CALL_ANSWERED")
    assert result.eval_class == "llm"


def test_natural_language_condition_is_llm():
    result = classify_rule(
        "IF the user's latest message sounds frustrated -> GO_TO: HANDOFF"
    )
    assert result.eval_class == "llm"


def test_dot_length_is_mechanical():
    """
`[slot].length` translates to `len(slot)` — both "len" and "_matches"

    are the only allowed Call names, and this is real-content syntax
        (e.g. `[appointments].length > 1`), not raw attribute access.

    Returns:
        None.
"""
    result = classify_rule("IF [appointments].length > 1 -> GO_TO: AM_PICK_ONE")
    assert result.eval_class == "code"
    assert result.python_expression == "len(appointments) > 1"
