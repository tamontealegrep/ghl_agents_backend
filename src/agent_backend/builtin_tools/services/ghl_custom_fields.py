"""Reading the custom fields an agent sends to the contact and opportunity tools."""

import ast
import json
from typing import Any


def _pairs_from_mapping_item(item: dict[str, Any]) -> tuple[str, Any] | None:
    """One ``{id|key|name, value|fieldValue|field_value}`` object as ``(name, value)``."""
    name = next((item[k] for k in ("id", "key", "name", "field") if item.get(k)), None)
    value = next((item[k] for k in ("fieldValue", "field_value", "value") if k in item), None)
    return (str(name).strip(), value) if name is not None and value is not None else None


def normalize_custom_fields(raw: Any) -> list[tuple[str, str]]:
    """Turns whatever the agent sent into ``(name or id, value)`` pairs.

    Accepted: a mapping ``{"city": "Bogotá"}``; a list of ``"city=Bogotá"`` strings (split on the first ``=``); a
    list of objects with an ``id``, ``key`` or ``name`` and a ``value`` or ``fieldValue``; or a string holding any of
    those as JSON or a Python literal. Entries without a name or a value are dropped, and a name given twice keeps
    the last value.

    Args:
        raw: The custom fields as sent.

    Returns:
        The pairs, values as text, in order.
    """
    if isinstance(raw, str):
        text = raw.strip()
        parsed: Any = None
        if text.startswith(("[", "{")):
            for parse in (json.loads, ast.literal_eval):
                try:
                    parsed = parse(text)
                    break
                except (ValueError, SyntaxError):
                    continue
        raw = parsed if parsed is not None else [line for line in text.splitlines() if line.strip()]
    if isinstance(raw, dict):
        raw = [{"name": name, "value": value} for name, value in raw.items()]
    pairs: dict[str, str] = {}
    for item in raw or []:
        pair: tuple[str, Any] | None = None
        if isinstance(item, dict):
            pair = _pairs_from_mapping_item(item)
        elif isinstance(item, str) and "=" in item:
            name, _, value = item.partition("=")
            pair = (name.strip(), value.strip())
        if pair and pair[0] and str(pair[1]).strip() != "":
            pairs[pair[0]] = str(pair[1]).strip() if not isinstance(pair[1], (list, tuple)) else ",".join(map(str, pair[1]))
    return list(pairs.items())
