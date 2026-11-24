"""
Unit tests for agent_runtime.targets.langgraph.type_parser — capture.type_expr classification.
"""
from __future__ import annotations

from agent_runtime.targets.langgraph.type_parser import classify_type_expr

# ---------------------------------------------------------------------------
# Canonical forms
# ---------------------------------------------------------------------------


def test_str_is_canonical():
    """`str` is a canonical type."""
    result = classify_type_expr("str")
    assert result.category == "canonical"


def test_int_is_canonical():
    """`int` is a canonical type."""
    result = classify_type_expr("int")
    assert result.category == "canonical"


def test_bool_is_canonical():
    """`bool` is a canonical type."""
    result = classify_type_expr("bool")
    assert result.category == "canonical"


def test_literal_enum_is_canonical():
    """A Literal enum is a canonical type."""
    result = classify_type_expr("Literal[yes, no]")
    assert result.category == "canonical"


def test_literal_enum_single_value_is_canonical():
    """A single-value Literal is a canonical type."""
    result = classify_type_expr("Literal[yes]")
    assert result.category == "canonical"


def test_list_of_str_is_canonical():
    """A list of str is a canonical type."""
    result = classify_type_expr("list[str]")
    assert result.category == "canonical"


def test_list_of_literal_is_canonical():
    """A list of Literal is a canonical type."""
    result = classify_type_expr("list[Literal[bleeding, fluid_loss, none]]")
    assert result.category == "canonical"


def test_email_is_canonical():
    """`email` is a canonical semantic type."""
    result = classify_type_expr("email")
    assert result.category == "canonical"


def test_phone_number_is_canonical():
    """`phone_number` is a canonical semantic type."""
    result = classify_type_expr("phone_number")
    assert result.category == "canonical"


def test_slot_selection_is_canonical():
    """`appointment_slot_selection` is a canonical semantic type."""
    result = classify_type_expr("appointment_slot_selection")
    assert result.category == "canonical"


def test_predicate_name_is_canonical():
    """A predicate name from the registry is a canonical type."""
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
    """"string" is a synonym that suggests str."""
    result = classify_type_expr("string")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "str"


def test_text_synonym_suggests_str():
    """"text" is a synonym that suggests str."""
    result = classify_type_expr("text")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "str"


def test_number_synonym_suggests_int():
    """"number" is a synonym that suggests int."""
    result = classify_type_expr("number")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "int"


def test_integer_synonym_suggests_int():
    """"integer" is a synonym that suggests int."""
    result = classify_type_expr("integer")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "int"


def test_boolean_synonym_suggests_bool():
    """"boolean" is a synonym that suggests bool."""
    result = classify_type_expr("boolean")
    assert result.category == "synonym"
    assert result.canonical_suggestion == "bool"


# ---------------------------------------------------------------------------
# Bare `list` -> needs an explicit item type (no guessing)
# ---------------------------------------------------------------------------


def test_bare_list_needs_item_type():
    """A bare list needs an item type."""
    result = classify_type_expr("list")
    assert result.category == "needs_item_type"


def test_list_of_unknown_item_unrecognised():
    """A list of a non-canonical item is unrecognised."""
    result = classify_type_expr("list[string]")
    assert result.category == "unrecognized"


# ---------------------------------------------------------------------------
# Unrecognized
# ---------------------------------------------------------------------------


def test_garbage_is_unrecognised():
    """Garbage text is unrecognised."""
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
