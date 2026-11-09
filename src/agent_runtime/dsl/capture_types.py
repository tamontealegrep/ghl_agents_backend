"""
Canonical type grammar for `capture.type_expr` — shared by both targets.

    A `type_expr` string is parsed with the stdlib ``ast`` module (the same
    restricted-Python-subset design used by ``dsl/condition_grammar.py``,
    see DESIGN_PATTERNS.md P01) since ``Literal[...]``/``list[T]`` are already
    valid ``typing`` syntax.

    Lives in ``dsl/`` because both compiler targets need it: the text-prompt
    target already prints `type_expr` verbatim into every ``CAPTURE`` block
    so the LLM knows exactly what to extract
    (``renderer.py::_render_capture_block``), and ``CaptureField.type_expr``
    (``schemas.py``) enforces this grammar at load time for every agent
    regardless of which target it's ultimately compiled to — the same
    reasoning that moved ``dsl/condition_grammar.py`` here too (2026-09-16):
    an interpretive, ungrammatical value is a hallucination surface for
    whichever LLM reads it, not a concern specific to one target.

    PascalCase names (``Slot``, ``Appointment``) are accepted as canonical
    even when no object-types registry declares them — they stay valid,
    opaque type markers until an author deliberately gives them structure.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Literal

SCALAR_TYPES = {"str", "int", "bool"}

# Closed registry — extended only by a deliberate schema edit, same
# governance as dsl.validators._COMPLIANCE_CHECKERS / condition_parser.NAMED_PREDICATES.
SEMANTIC_SCALAR_REGISTRY = {
    "email",
    "phone_number",
    "person_name",
    "free_text",
    "date_or_relative",
    "appointment_slot_selection",
    "numeric_string_without_spaces_or_punctuation",
}

SYNONYM_MAP: dict[str, str] = {
    "string": "str",
    "text": "str",
    "number": "int",
    "integer": "int",
    "boolean": "bool",
}

PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")

Category = Literal["canonical", "synonym", "needs_item_type", "unrecognized"]


@dataclass(frozen=True, slots=True)
class ParsedType:
    """
Result of classifying one `capture.type_expr` value.
"""

    raw: str
    category: Category
    canonical_suggestion: str | None = None
    reason: str | None = None


def classify_type_expr(type_expr: str) -> ParsedType:
    """Classify one `capture.type_expr` value per the canonical type grammar.

    Args:
        type_expr: The raw `type_expr` string from a capture field.

    Returns:
        ParsedType: The classification. `category` is `"canonical"` (already
        conforms), `"synonym"` (a known non-canonical spelling —
        `canonical_suggestion` names the fix), `"needs_item_type"` (bare
        `list` with no parametrization), or `"unrecognized"` (does not
        parse, or parses outside the whitelist).
    """
    text = type_expr.strip()

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        return ParsedType(raw=type_expr, category="unrecognized", reason=f"not parseable: {exc}")

    category, detail = _classify_node(tree.body)
    if category == "canonical":
        return ParsedType(raw=type_expr, category="canonical")
    if category == "synonym":
        return ParsedType(raw=type_expr, category="synonym", canonical_suggestion=detail)
    if category == "needs_item_type":
        return ParsedType(raw=type_expr, category="needs_item_type")
    return ParsedType(raw=type_expr, category="unrecognized", reason=detail)


def _classify_node(node: ast.AST) -> tuple[Category, str | None]:
    if isinstance(node, ast.Name):
        return _classify_name(node.id)

    if isinstance(node, ast.Subscript):
        return _classify_subscript(node)

    return ("unrecognized", f"disallowed syntax: {type(node).__name__}")


def _classify_name(name: str) -> tuple[Category, str | None]:
    if name in SCALAR_TYPES or name in SEMANTIC_SCALAR_REGISTRY:
        return ("canonical", None)
    if name in SYNONYM_MAP:
        return ("synonym", SYNONYM_MAP[name])
    if name == "list":
        return ("needs_item_type", None)
    if PASCAL_CASE_RE.fullmatch(name):
        return ("canonical", None)  # opaque or object-types-registry-backed object reference
    return ("unrecognized", f"unrecognized bare name: {name!r}")


def _classify_subscript(node: ast.Subscript) -> tuple[Category, str | None]:
    base = node.value
    if not isinstance(base, ast.Name):
        return ("unrecognized", "subscript base is not a bare name")

    if base.id == "Literal":
        items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if all(isinstance(item, ast.Name) for item in items):
            return ("canonical", None)
        return ("unrecognized", "Literal[...] members must be bare names")

    if base.id == "list":
        inner_category, inner_detail = _classify_node(node.slice)
        if inner_category == "canonical":
            return ("canonical", None)
        return ("unrecognized", f"list[...] item type is not canonical: {inner_detail}")

    return ("unrecognized", f"unrecognized subscripted type: {base.id!r}")
