"""
Backward-compatible re-export — the condition grammar now lives in `dsl/`.

    `route`/`fallback` classification moved to `dsl/condition_grammar.py`
    (2026-09-16) because it's a target-agnostic DSL concern — see that
    module's docstring — not LangGraph-specific. This module is kept only
    so existing imports of `agent_runtime.targets.langgraph.condition_parser`
    keep working.
"""

from __future__ import annotations

from agent_runtime.dsl.condition_grammar import (
    NAMED_PREDICATES,
    ParsedRule,
    classify_rule,
)

__all__ = ["NAMED_PREDICATES", "ParsedRule", "classify_rule"]
