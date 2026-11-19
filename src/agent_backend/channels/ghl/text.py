"""Text helpers for incoming GoHighLevel messages."""

import re
import unicodedata
from typing import Any

from agent_runtime import languages


def normalize_channel(value: str | None) -> str:
    """Upper-cases a channel name and turns dashes into underscores."""
    return (value or "").strip().upper().replace("-", "_")


def strip_accents(value: str) -> str:
    """Removes the accents from a text."""
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: Any) -> str:
    """Strips accents, lower-cases and trims, so texts can be compared."""
    return strip_accents(str(value or "")).lower().strip()


DEFAULT_LANGUAGE = languages.FALLBACK_CODE


def normalize_language(value: Any) -> str | None:
    """Normalizes a free-form language value (GHL's `contact_language` or `customData.language`, or anywhere else) to this project's canonical 2-letter code -- the code of one of the languages in `agent_runtime.languages`, never anything else.

    Case- and accent-insensitive, and accepts locale-style codes (en-US, es_CO, pt-BR -- only the primary subtag matters).

    Guards against GHL placeholders (e.g. "[[contact.language]]") by
    returning None for anything containing brackets, allowing a caller
    to fall back to a different source (like the user's latest message).

    Two different "doesn't match" cases, deliberately not collapsed into
    one:
    - No value at all (None/empty/placeholder) -> returns None. A caller
      with its own fallback (like opening.yaml's "if [contact.language]
      is missing, infer it from the user's latest message") needs to know
      nothing was said, not silently get handed a default.
    - A real value that just isn't one of the supported languages (e.g.
      one with no file in `agent_runtime/languages/data`) -> returns DEFAULT_LANGUAGE ("en").
    """
    text = normalize_text(value)
    if not text or "[" in text or "]" in text or "{{" in text:
        return None
    return languages.resolve(text, default=DEFAULT_LANGUAGE).code


def is_affirmative_message(message: str) -> bool:
    """Tells whether a message is a plain confirmation such as 'si', 'ok' or 'confirmo'."""
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalize_text(message))
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    if tokens in (["si"], ["yes"], ["ok"], ["okay"], ["confirmo"], ["confirm"]):
        return True
    phrases = {
        "si la info es correcta",
        "si es correcta",
        "yes correct",
        "yes that is correct",
        "confirmo la informacion",
        "confirmo la info",
    }
    return " ".join(tokens) in phrases


def preview_text(value: str, limit: int = 120) -> str:
    """Shortens a text for log lines."""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."
