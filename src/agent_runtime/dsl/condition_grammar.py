"""
Canonical condition grammar for `route`/`fallback` lines — shared by both targets.

    A `route`/`fallback` line is translated into a restricted Python
    expression and parsed with the stdlib ``ast`` module against a fixed
    node-type whitelist (see DESIGN_PATTERNS.md P01). A line that parses
    cleanly is "code"-eligible; anything else (bare flags, natural language,
    non-canonical synonyms like lowercase ``true``/``false`` or the retired
    ``== null`` idiom) is "llm"-only by construction — there is no special-
    casing, only what the whitelist accepts.

    Lives in ``dsl/`` rather than ``targets/langgraph/`` (moved 2026-09-16,
    reversing the original 2026-09-13 decision — see SPEC.md's decision
    log): mechanical-vs-interpretive is not actually a LangGraph-only
    concern. A `route`/`fallback` line that can't be reduced to this
    whitelist is exactly the hallucination surface both targets share — an
    LLM reading it in the compiled text prompt has to *guess* its meaning
    the same way the LangGraph runtime would have to fall back to an LLM
    judgment call for it. `dsl/validators.py` enforces this grammar
    unconditionally (every compile, either target, unless a node opts out
    with `eval: "llm"`), which is also what guarantees the two targets stay
    semantically equivalent: a spec that validates is mechanically
    consistent everywhere, not just wherever someone happened to also
    compile it to LangGraph.

    This module is read-only diagnostics: it does not mutate ``dsl/schemas.py``
    models and does not touch agent content — it only classifies text that
    already exists on a spec.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Named-predicate registry — governed like dsl.validators._COMPLIANCE_CHECKERS:
# extended only by a deliberate code change, never by YAML content.
# ---------------------------------------------------------------------------

NAMED_PREDICATES: dict[str, re.Pattern[str]] = {
    "numeric_string_without_spaces_or_punctuation": re.compile(r"^[0-9]+$"),
    "iana_timezone_format": re.compile(r"^[A-Z][A-Za-z_]+/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?$"),
    "scheduling_state_id": re.compile(r"^SC__.+$"),
    "knowledge_state_id": re.compile(r"^KQ__.+$"),
}

NAMED_PREDICATE_DESCRIPTIONS: dict[str, str] = {
    "numeric_string_without_spaces_or_punctuation": (
        "Only digits 0-9, one or more, nothing else — no spaces, letters, "
        "dashes, or punctuation of any kind. Valid: '1234567890'. "
        "Not valid: '123-456', '123 456', '12a45', ''."
    ),
    "iana_timezone_format": (
        "An IANA timezone identifier: two or three parts separated by a "
        "single '/' each (continent/city, or continent/country/city for "
        "zones that need it), each part starting with an uppercase letter "
        "and containing only letters and underscores after that — never an "
        "abbreviation, offset, or lowercase form. Valid: 'America/Bogota', "
        "'Europe/Lisbon', 'Asia/Jakarta', 'America/Argentina/Buenos_Aires', "
        "'America/Indiana/Indianapolis'. Not valid: 'EST', 'COT', 'UTC-5', "
        "'america/bogota', 'GMT+1'."
    ),
    "scheduling_state_id": (
        "The id of a state that belongs to the scheduling subflow: it starts "
        "with 'SC__' followed by at least one more character. Valid: "
        "'SC__SC_ASK_E', 'SC__SC_DEC_OK'. Not valid: 'AH__AH_ASK', 'O__OP_S', "
        "'SC__', ''."
    ),
    "knowledge_state_id": (
        "The id of a state that belongs to the knowledge questions subflow: it "
        "starts with 'KQ__' followed by at least one more character. Valid: "
        "'KQ__KQ_ASK_DOUBT', 'KQ__KQ_MORE'. Not valid: 'SC__SC_ASK_E', "
        "'O__OP_ASK', 'KQ__', ''."
    ),
}
"""Human-readable, precise definition of every `NAMED_PREDICATES` entry
(2026-09-17) — the text-prompt target's only source of truth for what a
`MATCHES <predicate_name>` condition actually means. Found live: the
LangGraph target evaluates `MATCHES` against the real regex above,
100% mechanically, zero LLM involved — but the text-prompt target has no
code interpreter at all, so the *same* condition, rendered as literal
text, left the reading LLM nothing but the predicate's bare name to work
from. `CONDITION_AND_OPERATOR_SEMANTICS` already tells it "never
approximate... based on the name alone", while structurally giving it no
alternative — a hallucination surface this module's own docstring already
names as the exact kind of gap both targets are meant to share the fix
for. `targets/text/renderer.py::render_matches_predicate_definitions`
renders these into the compiled prompt, but only for predicates the
agent's own ROUTE/FALLBACK lines actually reference, keeping the common
case (no `MATCHES` used) silent. A test enforces `NAMED_PREDICATES` and
this dict share the exact same key set, so a newly-registered predicate
can never silently ship without a description again.
"""

_ALLOWED_CALL_NAMES = {"len", "_matches"}

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.Is,
    ast.IsNot,
    ast.Name,
    ast.Constant,
    ast.List,
    ast.Load,
    ast.Call,
)

# Lowercase spellings that must never be accepted as a bare Name — real
# Python would otherwise happily parse them as ordinary identifiers.
_DISALLOWED_NAMES = {"null", "true", "false"}

_IF_RE = re.compile(r"^IF\s+(?P<condition>.+?)\s*->\s*GO_TO:\s*(?P<target>.+)$")
_GOTO_RE = re.compile(r"^GO_TO:\s*(?P<target>.+)$")

_MATCHES_RE = re.compile(r"(\S+)\s+MATCHES\s+([a-zA-Z_][a-zA-Z0-9_]*)")
_LENGTH_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]\.length\b")
_SLOT_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]")
_CONST_RE = re.compile(r"<([A-Z][A-Z0-9_]*)>")

# Order matters: "IS NOT NULL" must be replaced before "IS NULL".
_KEYWORD_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bIS NOT NULL\b"), "is not None"),
    (re.compile(r"\bIS NULL\b"), "is None"),
    (re.compile(r"\bAND\b"), "and"),
    (re.compile(r"\bOR\b"), "or"),
    (re.compile(r"\bNOT\b"), "not"),
    (re.compile(r"\bIN\b"), "in"),
    (re.compile(r"\bTRUE\b"), "True"),
    (re.compile(r"\bFALSE\b"), "False"),
]


class _NotMechanical(Exception):
    """
Raised internally when a condition falls outside the whitelist.
"""


@dataclass(frozen=True, slots=True)
class ParsedRule:
    """
Result of classifying one `route`/`fallback` line.
"""

    raw: str
    kind: Literal["unconditional", "conditional", "unrecognized"]
    eval_class: Literal["code", "llm"]
    target: str | None
    reason: str | None = None
    python_expression: str | None = None
    """The translated Python expression, set only when `eval_class == "code"`
    and `kind == "conditional"`. Used by the LangGraph emitter to generate
    the node's actual guard — never passed to `eval()` unvalidated, since
    `classify_rule` already ran it through `_validate_ast`'s whitelist."""


def find_used_predicates(condition_lines: list[str]) -> set[str]:
    """Every `NAMED_PREDICATES` name referenced via `MATCHES <name>` in `condition_lines`.

    Reuses `_MATCHES_RE` (the same pattern `classify_rule`'s mechanical
    translation already matches against) rather than a second regex, so the
    two can never drift on what counts as a `MATCHES` usage. Built for
    `targets/text/renderer.py::render_matches_predicate_definitions` — an
    agent's compiled prompt only needs the predicates it actually
    references, not the full registry.
    """
    return {m.group(2) for line in condition_lines for m in _MATCHES_RE.finditer(line)}


def classify_rule(line: str) -> ParsedRule:
    """Classify one `route`/`fallback` line as `code`-eligible or `llm`-only.

    Args:
        line: A single entry from a `route` or `fallback` list.

    Returns:
        ParsedRule: The classification, with `reason` set when `eval_class`
        is `"llm"` because the line fell outside the whitelist.
    """
    text = line.strip()

    match_if = _IF_RE.match(text)
    if match_if:
        condition_text = match_if.group("condition")
        target = match_if.group("target").strip()
        try:
            python_expression = _validate_condition(condition_text)
        except _NotMechanical as exc:
            return ParsedRule(
                raw=line, kind="conditional", eval_class="llm", target=target, reason=str(exc)
            )
        return ParsedRule(
            raw=line,
            kind="conditional",
            eval_class="code",
            target=target,
            python_expression=python_expression,
        )

    match_goto = _GOTO_RE.match(text)
    if match_goto:
        return ParsedRule(
            raw=line,
            kind="unconditional",
            eval_class="code",
            target=match_goto.group("target").strip(),
        )

    return ParsedRule(
        raw=line,
        kind="unrecognized",
        eval_class="llm",
        target=None,
        reason="does not match 'GO_TO: <target>' or 'IF <condition> -> GO_TO: <target>'",
    )


def _validate_condition(condition_text: str) -> str:
    """Return the translated Python expression if `condition_text` is mechanical.

    Raises `_NotMechanical` otherwise.
    """
    expr, known_names = _translate_to_python(condition_text)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise _NotMechanical(f"not a parseable expression: {exc}") from exc

    # A condition that is nothing but a single bare Name (no comparison, no
    # boolean operator) is only mechanical if that name came from an actual
    # `[slot]`/`<CONST>` token — otherwise it's an unbracketed prose flag
    # (e.g. "call_answered"), which is exactly what has no ground truth
    # to evaluate deterministically against.
    if isinstance(tree.body, ast.Name) and tree.body.id not in known_names:
        raise _NotMechanical(f"unbracketed bare identifier: {tree.body.id!r}")

    _validate_ast(tree)
    return expr


def _translate_to_python(condition_text: str) -> tuple[str, set[str]]:
    known_names: set[str] = set()

    def _matches_repl(match: re.Match[str]) -> str:
        return f"_matches({match.group(1)}, '{match.group(2)}')"

    text = _MATCHES_RE.sub(_matches_repl, condition_text)

    def _length_repl(match: re.Match[str]) -> str:
        known_names.add(match.group(1))
        return f"len({match.group(1)})"

    # Must run before _SLOT_RE strips the brackets — otherwise "[x].length"
    # becomes "x.length", an ast.Attribute access, which is not whitelisted.
    text = _LENGTH_RE.sub(_length_repl, text)

    def _bracket_repl(match: re.Match[str]) -> str:
        known_names.add(match.group(1))
        return match.group(1)

    text = _SLOT_RE.sub(_bracket_repl, text)
    text = _CONST_RE.sub(_bracket_repl, text)

    for pattern, replacement in _KEYWORD_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    return text, known_names


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise _NotMechanical(f"disallowed syntax: {type(node).__name__}")

        if isinstance(node, ast.Name) and node.id in _DISALLOWED_NAMES:
            raise _NotMechanical(f"non-canonical literal spelling: {node.id!r}")

        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_CALL_NAMES):
                raise _NotMechanical("disallowed function call")
            if node.func.id == "_matches":
                if len(node.args) != 2 or not isinstance(node.args[1], ast.Constant):
                    raise _NotMechanical("malformed MATCHES clause")
                predicate_name = node.args[1].value
                if predicate_name not in NAMED_PREDICATES:
                    raise _NotMechanical(f"unregistered MATCHES predicate: {predicate_name!r}")
