"""
Backward-compatible re-export — the type grammar now lives in `dsl/`.

    `capture.type_expr` classification moved to `dsl/capture_types.py`
    because it's a target-agnostic DSL concern (`CaptureField.type_expr`
    enforces it at load time, and the text-prompt target prints it verbatim
    into every `CAPTURE` block too — see that module's docstring). Same
    reasoning that moved `dsl/condition_grammar.py` (formerly
    `condition_parser.py`) here too. This module is kept only so existing
    imports of `agent_runtime.targets.langgraph.type_parser` keep working.
"""

from __future__ import annotations

from agent_runtime.dsl.capture_types import (
    PASCAL_CASE_RE,
    SCALAR_TYPES,
    SEMANTIC_SCALAR_REGISTRY,
    SYNONYM_MAP,
    Category,
    ParsedType,
    classify_type_expr,
)

__all__ = [
    "PASCAL_CASE_RE",
    "SCALAR_TYPES",
    "SEMANTIC_SCALAR_REGISTRY",
    "SYNONYM_MAP",
    "Category",
    "ParsedType",
    "classify_type_expr",
]
