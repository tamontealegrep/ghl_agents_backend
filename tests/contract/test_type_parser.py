"""
Unit tests for agent_runtime.targets.langgraph.type_parser — capture.type_expr classification.
"""

from __future__ import annotations

from agent_runtime.targets.langgraph.type_parser import classify_type_expr

# ---------------------------------------------------------------------------
# Canonical forms
# ---------------------------------------------------------------------------


def test_str_is_canonical():
    result = classify_type_expr("str")
    assert result.category == "canonical"


def test_int_is_canonical():
    result = classify_type_expr("int")
    assert result.category == "canonical"


def test_bool_is_canonical():
    result = classify_type_expr("bool")
    assert result.category == "canonical"


def test_literal_enum_is_canonical():
    result = classify_type_expr("Literal[yes, no]")
    assert result.category == "canonical"


def test_literal_enum_single_value_is_canonical():
    result = classify_type_expr("Literal[yes]")
    assert result.category == "canonical"


def test_list_of_str_is_canonical():
    result = classify_type_expr("list[str]")
    assert result.category == "canonical"


def test_list_of_literal_is_canonical():
    result = classify_type_expr("list[Literal[bleeding, fluid_loss, none]]")
    assert result.category == "canonical"


def test_semantic_registry_email_is_canonical():
    result = classify_type_expr("email")
    assert result.category == "canonical"


def test_semantic_registry_phone_number_is_canonical():
    result = classify_type_expr("phone_number")
    assert result.category == "canonical"


def test_semantic_registry_appointment_slot_selection_is_canonical():
    result = classify_type_expr("appointment_slot_selection")
    assert result.category == "canonical"


def test_semantic_registry_numeric_string_predicate_name_is_canonical():
    result = classify_type_expr("numeric_string_without_spaces_or_punctuation")
    assert result.category == "canonical"


def test_opaque_object_reference_is_canonical():
    """
    PascalCase names (Slot, Appointment) are canonical even with no object-types registry.

        Returns:
            None.
    """
    result = classify_type_expr("Appointment")
    assert result.category == "canonical"


# ---------------------------------------------------------------------------
# Synonyms -> needs migration, but classification says exactly what to rename to
# ---------------------------------------------------------------------------


def test_string_synonym_suggests_str():
    result = classify_type_expr("string")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "str"


def test_text_synonym_suggests_str():
    result = classify_type_expr("text")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "str"


def test_number_synonym_suggests_int():
    result = classify_type_expr("number")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "int"


def test_integer_synonym_suggests_int():
    result = classify_type_expr("integer")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "int"


def test_boolean_synonym_suggests_bool():
    result = classify_type_expr("boolean")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "bool"


# ---------------------------------------------------------------------------
# Bare `list` -> needs an explicit item type (no guessing)
# ---------------------------------------------------------------------------


def test_bare_list_needs_item_type():
    result = classify_type_expr("list")
    assert result.category == "needs_item_type"


def test_list_of_non_canonical_item_is_unrecognized():
    result = classify_type_expr("list[string]")
    assert result.category == "unrecognized"


# ---------------------------------------------------------------------------
# Unrecognized
# ---------------------------------------------------------------------------


def test_garbage_text_is_unrecognized():
    result = classify_type_expr("this is not a type at all")
    assert result.category == "unrecognized"


def test_lowercase_literal_keyword_is_unrecognized():
    """
    `Literal` must be spelled exactly as Python's typing spells it — not a DSL keyword.

        Returns:
            None.
    """
    result = classify_type_expr("literal[yes, no]")
    assert result.category == "unrecognized"
