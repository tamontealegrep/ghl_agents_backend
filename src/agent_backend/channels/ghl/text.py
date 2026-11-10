import re
import unicodedata
from typing import Any


def normalize_channel(value: str | None) -> str:
    return (value or "").strip().upper().replace("-", "_")


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: Any) -> str:
    return strip_accents(str(value or "")).lower().strip()


# Every alias a CRM/webhook might send for one of the 3 languages every
# text agent actually supports (see e.g. opening.yaml's
# "[preferred_language] = 'es' | 'en' | 'pt'") -- keys are already
# accent-stripped/lowercased, matched against normalize_text's own output,
# so "Español"/"espanol" and "Português"/"portugues" share one entry each
# instead of needing both spellings listed.
_LANGUAGE_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "ingles": "en",
    "es": "es",
    "esp": "es",
    "spa": "es",
    "spanish": "es",
    "espanol": "es",
    "castellano": "es",
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "portugues": "pt",
}


DEFAULT_LANGUAGE = "en"


def normalize_language(value: Any) -> str | None:
    """Normalizes a free-form language value (GHL's `contact_language` or `customData.language`, or anywhere else) to this project's canonical 2-letter code -- "es"/"en"/"pt", never anything else.

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
    - A real value that just isn't one of the 3 supported languages (e.g.
      French, German) -> returns DEFAULT_LANGUAGE ("en").
    """
    text = normalize_text(value)
    if not text or "[" in text or "]" in text or "{{" in text:
        return None
    # Split on any non-alphanumeric character (covers spaces, parens, dashes, etc.)
    primary = re.split(r"[^a-z0-9]", text)[0]
    return _LANGUAGE_ALIASES.get(primary, DEFAULT_LANGUAGE)


def is_affirmative_message(message: str) -> bool:
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
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."
