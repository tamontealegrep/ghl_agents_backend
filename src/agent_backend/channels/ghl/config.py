"""Settings of one agent's GHL webhook, plus the text and phone helpers it needs."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_backend.channels.ghl.client import (
    GhlClientConfig,
)


@dataclass(frozen=True)
class CompiledAgentGhlConfig:
    """
Everything that differs from one compiled agent's GHL endpoint to another.
"""

    slug: str
    """Must match a folder under compiled_agents/."""
    path: str
    """Route path, e.g. "/sam_text" -> mounted as POST {path}."""
    allowed_phones: frozenset[str]
    """Normalized (no spaces/dashes/parens) E.164 numbers this pilot accepts.
    Ignored entirely when `enforce_phone_whitelist` is False."""
    debounce_seconds: float
    ghl_client_config: Callable[[], GhlClientConfig]
    """Returns the GhlClientConfig to send replies with -- typically reuses
    an existing agent.json's ghl/runtime/messaging sections (base_url,
    token env var, channel map -- none of that is agent-specific)."""
    enforce_phone_whitelist: bool = True
    """Kill switch for the pilot gate, per agent -- False lets every phone
    through regardless of `allowed_phones` (e.g. once an agent is cleared
    to go live). Defaults to True so an agent stays gated unless a caller
    explicitly opts out; see each agent's own text.py for the .env var
    that drives this (load_phone_whitelist's own docstring)."""
    closing_message_lookback_days: float = 3.0
    """How many days back `run_closing_sweep_once` still considers a
    candidate -- a safety bound, not the trigger itself (that's always
    ~23h45m of inactivity, see postgres.CLOSING_MESSAGE_INACTIVITY_THRESHOLD,
    a WhatsApp platform constant, not a per-agent choice). Guards against a
    sweep that was down for a while suddenly messaging contacts from
    long-dead conversations once it catches back up. One .env var per
    agent, same pattern as debounce_seconds -- see each agent's own
    text.py."""
    closing_message: str | dict[str, str] | None = None
    """Override for the text sent by the closing sweep. A plain string
    always wins; a dict is looked up by the thread's preferred_language
    (stored as "English"/"Spanish"/"Portuguese" or as a code; English when
    the language is unknown or missing). None uses the built-in
    default entirely -- deliberately generic ("puede ser de cualquiera"),
    since the sweep's only job is to get *something* out before Meta's 24h
    window closes, not to carry flow-specific content."""
    redirect_widget_to_whatsapp: bool = True
    """(2026-10-02, pedido directamente) If True, an inbound message from
    the widget (LIVE_CHAT) is responded to via WhatsApp instead. Enabled
    by default; el widget solo se usa para el primer contacto."""
    unsupported_media_message: str | dict[str, str] | None = None
    """Override for the reply sent when a message arrives with no text (a
    video, audio or sticker reaches GHL with an empty body) in the middle of
    a conversation. Same shape as `closing_message`: a plain string always
    wins; a dict is looked up by the conversation's language (falls back to
    the built-in ES/EN/PT default). The graph is not invoked, so the pending
    question stays pending."""
    turn_lock_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("GHL_TURN_LOCK_TIMEOUT_SECONDS", "60"))
    )
    """Longest a flushed turn waits for the previous turn of the same conversation to finish before
    running anyway. Turns of one conversation run one at a time, so a message that arrives while the
    agent is still answering (a slow availability check, say) is answered after it, from the state
    that turn left, instead of racing it on the same checkpoint. The limit only exists so a hung turn
    cannot block the conversation forever. Same default for every agent; override per agent here or
    for all with GHL_TURN_LOCK_TIMEOUT_SECONDS."""


_DEFAULT_CLOSING_MESSAGES: dict[str, str] = {
    "es": "Gracias por contactarte con nosotros. Si tienes alguna otra pregunta, no dudes en escribirnos. ¡Que tengas un buen día!",
    "en": "Thank you for reaching out to us. If you have any other questions, feel free to write to us anytime. Have a great day!",
    "pt": "Obrigado por entrar em contato conosco. Se tiver mais alguma pergunta, não hesite em nos escrever. Tenha um ótimo dia!",
}


def _closing_message_text(cfg: CompiledAgentGhlConfig, preferred_language: str | None) -> str:
    if isinstance(cfg.closing_message, str):
        return cfg.closing_message
    messages = cfg.closing_message if isinstance(cfg.closing_message, dict) else _DEFAULT_CLOSING_MESSAGES
    raw = (preferred_language or "en").strip().lower()
    code = _LANGUAGE_CODES.get(raw, raw)
    return messages.get(code) or messages.get("en") or next(iter(messages.values()))


_DEFAULT_UNSUPPORTED_MEDIA_MESSAGES: dict[str, str] = {
    "es": "No pude entender ese mensaje. Por ahora solo puedo responderte por texto.",
    "en": "I couldn't understand that message. For now I can only reply to text.",
    "pt": "Não consegui entender essa mensagem. Por enquanto só posso responder por texto.",
}

_LANGUAGE_CODES = {"spanish": "es", "english": "en", "portuguese": "pt"}


def _unsupported_media_text(cfg: CompiledAgentGhlConfig, language: str | None) -> str:
    if isinstance(cfg.unsupported_media_message, str):
        return cfg.unsupported_media_message
    messages = (
        cfg.unsupported_media_message
        if isinstance(cfg.unsupported_media_message, dict)
        else _DEFAULT_UNSUPPORTED_MEDIA_MESSAGES
    )
    raw = (language or "es").strip().lower()
    code = _LANGUAGE_CODES.get(raw, raw)
    return messages.get(code) or messages.get("es") or next(iter(messages.values()))


def _normalize_phone(raw: object) -> str:
    return str(raw or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


# Manual-testing reset marker (2026-09-29, pedido directamente): the classic
# /sam agent had its own version of this ("</>", see agents/helpers/history.py
# ::DEFAULT_RESET_MARKER), but it's not going to be used going forward and,
# separately, never actually matched anyway -- a real GHL/WhatsApp payload
# sends "<\>" (one literal backslash), confirmed live against the exact
# payload shared this session, not "</>" (forward slash). sam_text doesn't
# share any code with that agent (never calls agents.helpers.runner or
# apply_reset_marker -- its "memory" is the LangGraph checkpoint, not
# re-fetched GHL history), so this is its own, independent mechanism.
# Three spellings accepted, so a tester doesn't have to remember which one
# actually reaches the LLM unmangled: "<\>" (what a real payload sends),
# "<\\>" (two backslashes -- what typing the JSON-escaped form seen in a
# logged payload literally into WhatsApp produces), and "</>" (forward
# slash, kept for muscle memory from the classic agent's own marker).
_RESET_MARKERS = ("<\\>", "<\\\\>", "</>")


def _strip_reset_marker(message: str) -> tuple[str, bool]:
    """If `message` starts with a reset marker (either slash direction, see _RESET_MARKERS), returns (message with the marker removed, True).

    Otherwise returns (message unchanged, False). Whitespace around the marker is ignored on both sides.
    """
    stripped = message.lstrip()
    for marker in _RESET_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker):].strip(), True
    return message, False


GHL_TEXT_HISTORY_MAX_DAYS = float(os.getenv("GHL_TEXT_HISTORY_MAX_DAYS", "7"))
"""Shared across every text agent wired here (2026-09-29, pedido directamente)
-- unlike debounce_seconds/closing_message_lookback_days, this is deliberately
ONE .env var for all of them, not one per agent. How many days of inactivity
before resolve_session treats the next inbound message as a brand-new
conversation instead of resuming the existing one.

Previously this was each agent's own compiled session_timeout_minutes
(manifest.yaml -- content, requires a recompile to change). This env var is
now the authoritative source for the real GHL webhook pipeline (_run_turn
below); each agent's own artifact.session_timeout_minutes is left as-is in
the DSL and still governs compiled_runner/endpoint.py's generic test-chat
tool, which isn't text-agent-specific and has nothing to do with GHL."""

GHL_TEXT_SESSION_TIMEOUT_MINUTES = GHL_TEXT_HISTORY_MAX_DAYS * 24 * 60


_FALSE_STRINGS = {"0", "false", "no", "off"}


def load_phone_whitelist(
    list_env_var: str, enforce_env_var: str, default_phones: str = ""
) -> tuple[frozenset[str], bool]:
    """Reads one agent's phone pilot gate from two .env vars, instead of a hardcoded frozenset in that agent's own text.py -- moved here 2026-09-29 so the actual numbers (and whether the gate applies at all) can change without touching code or redeploying.

    `list_env_var`: comma-separated E.164 numbers, e.g.
        "+573215616921,+573007011593". Spaces around commas are trimmed;
        each number is normalized the same way an inbound request's phone
        is (see _normalize_phone) so formatting differences never cause a
        silent mismatch.
    `enforce_env_var`: "true"/"false" (also accepts 1/0, yes/no, on/off,
        case-insensitive). Defaults to enforcing (True) if unset or
        unrecognized -- an agent stays gated unless a caller explicitly
        opts out, never the other way around by accident. This is the
        switch to flip when an agent is cleared to go live: set it to
        false and every phone gets through, no code change needed.
    `default_phones`: used only if `list_env_var` isn't set in .env at all
        -- lets a caller keep working with zero .env setup, same as
        before this moved out of hardcoded Python.
    """
    raw_phones = os.getenv(list_env_var, default_phones)
    phones = frozenset(_normalize_phone(p) for p in raw_phones.split(",") if p.strip())

    raw_enforce = os.getenv(enforce_env_var, "true").strip().lower()
    enforce = raw_enforce not in _FALSE_STRINGS  # anything unrecognized defaults to enforcing, not open

    return phones, enforce
