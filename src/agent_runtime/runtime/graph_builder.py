"""
Builds a real `langgraph.graph.StateGraph` from a `RuntimeArtifact`.

    Consumes the `RuntimeArtifact` `targets.langgraph.runtime_artifact` emits
    (a plain, JSON-serializable bundle of the graph definition, global-router
    definition, tool contracts, and constants) and builds one LangGraph node
    per DSL node, real conditional edges, and `interrupt()` for the multi-turn
    "ask a question, wait for the reply" pattern. This is the reference
    runtime SPEC.md §2.4 describes as a separate, optional consumer of the
    compiled artifact — `dsl/loaders.py`, `dsl/validators.py`,
    `dsl/classifier.py`, `dsl/deduplicator.py`, `targets/text/`, `diagrams/`,
    `compiler.py`, and `cli.py` are all compiler-only and never imported here.

    Deliberately takes a `RuntimeArtifact`, not an `AgentSpec`: a backend that
    only *runs* compiled agents should be able to load one from a `.json` file
    on disk and never need the YAML-loading, validating, or text-rendering
    machinery at all — swapping an agent means replacing that one file, not
    redeploying this module. See `targets/langgraph/runtime_artifact.py`.

    Known limitations of this reference implementation (documented, not
    silently dropped):
      - `subflow_change` nodes are pure pass-through — `AgentSpec` has already
        resolved every route/fallback to concrete, namespaced state ids by the
        time it reaches this module.

    `action` node tool-argument binding (`_bind_tool_inputs`, 2026-09-16):
    real agent content almost never captures a slot under the exact same
    name as the tool contract's declared input (subflow namespacing alone
    guarantees a mismatch — `cl__nat` vs. `nationalities`) — an exact-name-only
    binder left nearly every tool call unable to run. Three passes, mechanical
    before LLM, same philosophy as `_apply_store_line`'s own STORE fallback:
    (1) exact slot-name match, (2) a `DO` line shaped `input_name = [slot]` /
    `= <CONSTANT>` / `= 'literal'` — the bare-left-hand-side counterpart to
    STORE's own `[slot] = ...` grammar, resolved without any LLM call, and
    (3) one batched LLM call (never one call per argument) deriving whatever
    required inputs are still missing from the full `DO` context and known
    slots — covers the DO lines that describe a real transform or derivation
    ("uppercase", "the literal start_co field of the chosen slot") rather
    than a bare copy, which a mechanical parser can't safely resolve on its
    own.

    Conditional DO/STORE prose (`_apply_conditional_mutations`, 2026-09-16):
    a third, distinct DO/STORE convention — "If X, update [slot]" — found live
    piloting `family_aims_sam_text_2_0` (`SC_FIX`'s corrections were a total
    no-op: the whole node exists to apply a name/phone/email/date correction
    and did nothing). Unlike the other two conventions, this one gets no
    mechanical pass at all: branching on free text ("if the correction is
    about the name", inferring 'surrogacy' from "quiero alguien que lleve a mi
    bebé") is exactly the kind of real-language understanding a `question`
    node's own capture step already needs an LLM for — a regex here would
    silently fail the same way `_bind_tool_inputs`'s exact-match-only binder
    did. Any DO/STORE line that isn't a recognized literal assignment but
    still names a `[slot]` goes straight to one batched LLM call per node
    (every such line together, so the model sees the full instruction set
    against one user message, not one call per line). Excluded from `action`
    nodes' DO lines — those are entirely owned by `_bind_tool_inputs` above.

    `question` nodes are routed exclusively via a `Command(goto=...)` their
    own `node_fn` returns — never via `add_conditional_edges`. Verified
    empirically: LangGraph does not suppress a node's registered conditional
    edges just because that node's function returns a `Command`, so
    registering both causes a concurrent-write `InvalidUpdateError` on the
    `slots` channel the moment a global-router match resolves to a concrete
    jump target (the resume-in-place case never surfaced this, since it never
    produces a second write in the same step). See `_resolve_target`.
"""

from __future__ import annotations

import json
import logging
import datetime
import re
import unicodedata
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from agent_runtime.dsl.schemas import ToolContractField
from agent_runtime.dsl.utils import dynamic_target_slot_name, is_dynamic_target
from agent_runtime.runtime.global_router import (
    UNANSWERED_QUESTION_ACK,
    handle_global_router_match,
    has_unanswered_side_question,
    is_bare_yes_no as _is_bare_yes_no,
    match_side_question,
    _looks_like_question,
    match_global_router,
    router_for_state,
)
from agent_runtime.runtime.knowledge_base import (
    KNOWLEDGE_TOOL_NAME,
    KnowledgeBase,
    make_knowledge_tool_executor,
)
from agent_runtime.runtime.llm_client import LLMClient, LLMContext
from agent_runtime.runtime.safe_expr import safe_eval
from agent_runtime.runtime.tool_executor import ToolExecutionError, make_tool_executor
from agent_runtime.targets.langgraph.condition_parser import NAMED_PREDICATES
from agent_runtime.targets.langgraph.graph_renderer import FaqNode, GlobalRouterDefinition, GraphEdge, GraphNode
from agent_runtime.targets.langgraph.runtime_artifact import RuntimeArtifact
from agent_runtime.targets.langgraph.type_parser import classify_type_expr


class SessionState(TypedDict):
    slots: dict[str, Any]
    current_state: str
    last_user_message: str
    last_message_at: str
    history: list[str]
    contact: dict[str, Any]


_HISTORY_WINDOW = 10
"""How many recent `"agent: ..."` / `"user: ..."` lines the session keeps. The
knowledge-base tool receives all of them (a follow-up question can refer to
something said several messages ago); every other LLM call only shows the last
`PROMPT_HISTORY_LINES` of them (2026-09-17: enough to judge whether a reply
continues the conversation it's in without carrying the whole transcript into
every routing call)."""


def _append_history(history: list[str], entry: str) -> list[str]:
    return (history + [entry])[-_HISTORY_WINDOW:]


# ---------------------------------------------------------------------------
# STORE mutation interpreter (`[slot] = value`, `increment [slot] by 1`)
# ---------------------------------------------------------------------------

_STORE_ASSIGN_RE = re.compile(r"^\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s*=\s*(.+)$")
_STORE_INCREMENT_RE = re.compile(r"^increment\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+by\s+1$", re.IGNORECASE)
_STORE_SLOT_REF_RE = re.compile(r"^\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_SELF_ARITH_RE = re.compile(r"^\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s*([+-])\s*(\d+)$")
_QUOTED_RE = re.compile(r"^'(.*)'$|^\"(.*)\"$")
_STORE_MATCH_IN_RE = re.compile(r"^match in <([A-Z_][A-Z0-9_]*)>\s*\|\s*(?:'([^']*)'|\"([^\"]*)\")$")
_STORE_RESOLVE_DAY_RE = re.compile(
    r"^RESOLVE_DAY\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+IN\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+AMONG\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$"
)
_STORE_RESOLVE_TIME_RE = re.compile(
    r"^RESOLVE_TIME\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+AMONG\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+AT\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$"
)
_STORE_LOCATION_LABEL_RE = re.compile(r"^LOCATION_LABEL\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_DAY_LABEL_RE = re.compile(r"^DAY_(LABEL|TITLE|FULL)\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_CONTACT_RE = re.compile(r"^\{\{contact\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}$")
_STORE_LANGUAGE_NAME_RE = re.compile(r"^LANGUAGE_NAME\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_FIRST_WORD_RE = re.compile(r"^FIRST_WORD\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_FIND_DAY_RE = re.compile(r"^FIND_DAY\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+IN\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$")
_STORE_PICK_RE = re.compile(
    r"^PICK\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\.([a-zA-Z_][a-zA-Z0-9_]*)"
    r"\s+AT\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+\[([a-zA-Z_][a-zA-Z0-9_]*)\]$"
)


def _fold(text: str) -> str:
    """Accent- and case-insensitive comparison key."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").casefold().strip()


def _match_in_constant(current: Any, options_text: Any, fallback: str) -> str | None:
    """
    Canonical option of `options_text` (comma / "y" separated) equal to `current`, else `fallback`.

    Returns None when there is nothing to match (no current value, or the constant is not text).
    """
    if current is None or not isinstance(options_text, str):
        return None
    options = [o.strip() for o in re.split(r",|\sy\s", options_text) if o.strip()]
    wanted = _fold(str(current))
    return next((o for o in options if _fold(o) == wanted), fallback)


def _apply_store_line(line: str, ctx: LLMContext, llm_client: LLMClient) -> None:
    """Apply one `STORE`/`DO` mutation line's effect to `ctx.slots`, in place.

    Literal assignments, slot-to-slot copies, `NULL` resets, the
    `increment [x] by 1` phrase, and the DSL's own documented
    `[x] = [x] + 1` retry-counter arithmetic (`NUMERIC_AND_RETRY_COUNTER_
    SEMANTICS` in the text target's system prompt template — this is the
    form real agent content actually uses, not the `increment` phrase) are
    all resolved mechanically. Bare, unquoted prose (e.g. "the IANA
    identifier derived from the reported city") is a computed assignment,
    not a literal — the model is asked to actually perform the described
    computation instead of storing the instruction text itself. A line
    that isn't shaped like an assignment at all (most `DO` lines — tool-
    argument hints, "TOOL CALL ONLY: call X now") is silently a no-op:
    this function is safe to run over `DO` as well as `STORE`.
    """
    slots = ctx.slots
    match = _STORE_INCREMENT_RE.match(line.strip())
    if match:
        name = match.group(1)
        slots[name] = int(slots.get(name) or 0) + 1
        return

    match = _STORE_ASSIGN_RE.match(line.strip())
    if not match:
        return
    name, rhs = match.group(1), match.group(2).strip()

    slot_ref = _STORE_SLOT_REF_RE.match(rhs)
    if slot_ref:
        slots[name] = slots.get(slot_ref.group(1))
        return
    arith = _STORE_SELF_ARITH_RE.match(rhs)
    if arith and arith.group(1) == name:
        delta = int(arith.group(3))
        current = int(slots.get(name) or 0)
        slots[name] = current + delta if arith.group(2) == "+" else current - delta
        return
    if rhs == "NULL":
        slots[name] = None
        return
    if rhs.lstrip("-").isdigit():
        slots[name] = int(rhs)
        return
    if rhs in ("true", "TRUE", "True"):
        slots[name] = True
        return
    if rhs in ("false", "FALSE", "False"):
        slots[name] = False
        return
    quoted = _QUOTED_RE.match(rhs)
    if quoted:
        slots[name] = _expand_constants(quoted.group(1) if quoted.group(1) is not None else quoted.group(2), slots)
        return
    match_in = _STORE_MATCH_IN_RE.match(rhs)
    if match_in and match_in.group(1) in slots:
        fallback = match_in.group(2) if match_in.group(2) is not None else match_in.group(3)
        matched = _match_in_constant(slots.get(name), slots[match_in.group(1)], fallback)
        if matched is not None:
            slots[name] = matched
        return

    resolve_day = _STORE_RESOLVE_DAY_RE.match(rhs)
    if resolve_day:
        reply, calendar, offered = (slots.get(resolve_day.group(i)) for i in (1, 2, 3))
        slots[name] = _resolve_day_reference(reply, calendar, offered)
        return

    resolve_time = _STORE_RESOLVE_TIME_RE.match(rhs)
    if resolve_time:
        reply, offered, day = (slots.get(resolve_time.group(i)) for i in (1, 2, 3))
        slots[name] = _resolve_time_reference(reply, offered, day)
        return

    location_label = _STORE_LOCATION_LABEL_RE.match(rhs)
    if location_label:
        slots[name] = _location_label(
            llm_client, slots.get(location_label.group(1)), slots.get("user_timezone"), slots.get("preferred_language")
        )
        return

    day_label = _STORE_DAY_LABEL_RE.match(rhs)
    if day_label:
        build = {"LABEL": _day_label, "TITLE": _day_title, "FULL": _day_full}[day_label.group(1)]
        slots[name] = build(slots.get(day_label.group(2)), slots.get("preferred_language"))
        return

    contact_ref = _STORE_CONTACT_RE.match(rhs)
    if contact_ref:
        slots[name] = _contact_field(ctx.contact, contact_ref.group(1))
        return

    language_name = _STORE_LANGUAGE_NAME_RE.match(rhs)
    if language_name:
        slots[name] = _LANGUAGE_NAMES.get(_language_key(slots.get(language_name.group(1))) or "", "English")
        return

    first_word = _STORE_FIRST_WORD_RE.match(rhs)
    if first_word:
        words = str(slots.get(first_word.group(1)) or "").split()
        slots[name] = words[0] if words else None
        return

    find_day = _STORE_FIND_DAY_RE.match(rhs)
    if find_day:
        slots[name] = _offered_day(slots.get(find_day.group(1)), slots.get(find_day.group(2)))
        return

    pick = _STORE_PICK_RE.match(rhs)
    if pick:
        items, field, day, time = (slots.get(pick.group(1)), pick.group(2), slots.get(pick.group(3)), slots.get(pick.group(4)))
        slots[name] = _pick_appointment_field(items, field, day, time)
        return

    slots[name] = _llm_compute_store_value(llm_client, name, rhs, ctx)


_WEEKDAY_WORDS = {
    0: ("lunes", "monday", "segunda"),
    1: ("martes", "tuesday", "terca"),
    2: ("miercoles", "wednesday", "quarta"),
    3: ("jueves", "thursday", "quinta"),
    4: ("viernes", "friday", "sexta"),
    5: ("sabado", "saturday"),
    6: ("domingo", "sunday"),
}
_WEEKDAY_BY_WORD = {word: index for index, words in _WEEKDAY_WORDS.items() for word in words}
_WEEKDAY_NAMES = {
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "pt": ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"],
}
def _month_by_word() -> dict[str, int]:
    """Month number by accent-folded month name or its first three letters, in every language."""
    by_word = {_fold(name): index + 1 for names in _MONTH_NAMES.values() for index, name in enumerate(names)}
    by_word.update({word[:3]: number for word, number in list(by_word.items())})
    return by_word


_LANGUAGE_CODE_BY_NAME = {"spanish": "es", "english": "en", "portuguese": "pt"}


def _language_key(language: Any) -> str | None:
    """'es', 'en' or 'pt' for either the code or the language name (`preferred_language` holds the name)."""
    text = str(language or "").strip().lower()
    return text if text in _LANGUAGE_CODE_BY_NAME.values() else _LANGUAGE_CODE_BY_NAME.get(text)


def _contact_field(contact: dict[str, Any] | None, field: str) -> Any:
    """
    The CRM value of `{{contact.<field>}}`, or None when the CRM has none.

    A blank value, the word "null", and the unsubstituted merge tag itself (`{{contact.name}}` arriving
    as text) all mean the CRM does not have the field. This is what `{{contact.X}} != '{{contact.X}}'`
    conditions used to ask a model to judge; as a plain copy the flow can route on `IS NOT NULL`.
    """
    value = (contact or {}).get(field)
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _EMPTY_WORDS or text == "{{contact." + field + "}}":
            return None
        return text
    return value


def _offered_day(day: Any, items: Any) -> Any:
    """`day` when some appointment in `items` starts on that date in its own `start_local`, else None."""
    if not isinstance(items, list) or not isinstance(day, str):
        return None
    wanted = _date_parts(day)
    if wanted is None:
        return None
    for item in items:
        start = item.get("start_local") if isinstance(item, dict) else None
        if isinstance(start, str) and _date_parts(start) == wanted:
            return day
    return None


def _resolve_day_reference(reply: Any, calendar: Any, offered: Any) -> str | None:
    """
    The YYYY-MM-DD date a contact means by `reply` ("el viernes", "Nov 5", "dia 3", "tomorrow"), or None.

    A model asked to turn a weekday into a date picked the wrong one often enough to book the wrong
    day (a "Friday" came back as a Wednesday), so this is mechanical. `calendar` is the
    'YYYY-MM-DD Weekday' list starting today; `offered` the appointments being offered. A weekday
    means the soonest offered date with it, else the first calendar date after today; a day number
    alone, the first calendar date with that number; day and month, the earliest year not in the past.
    """
    if not isinstance(reply, str) or not isinstance(calendar, str):
        return None
    dates = [datetime.date(int(y), int(m), int(d)) for y, m, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", calendar)]
    if not dates:
        return None
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", reply)
    if iso:
        return iso.group(0)
    text = _fold(reply)
    words = re.findall(r"[a-z]+", text)
    if "pasado" in words and "manana" in words or "depois" in words and "amanha" in words or ("after" in words and "tomorrow" in words):
        return dates[2].isoformat() if len(dates) > 2 else None
    if {"hoy", "today", "hoje"} & set(words):
        return dates[0].isoformat()
    if {"manana", "tomorrow", "amanha"} & set(words) and len(dates) > 1:
        return dates[1].isoformat()

    numbers = [int(n) for n in re.findall(r"(?<![\d:])\b(\d{1,2})(?![\d:])", text) if 1 <= int(n) <= 31]
    month_by_word = _month_by_word()
    months = [month_by_word[w] for w in words if w in month_by_word]
    if numbers:
        day = numbers[0]
        if months:
            for year in (dates[0].year, dates[0].year + 1):
                try:
                    candidate = datetime.date(year, months[0], day)
                except ValueError:
                    return None
                if candidate >= dates[0]:
                    return candidate.isoformat()
            return None
        return next((d.isoformat() for d in dates if d.day == day), None)

    weekdays = {_WEEKDAY_BY_WORD[w] for w in words if w in _WEEKDAY_BY_WORD}
    if len(weekdays) != 1:
        return None
    weekday = weekdays.pop()
    offered_dates = sorted(
        {
            datetime.date(int(y), int(m), int(d))
            for item in (offered if isinstance(offered, list) else [])
            if isinstance(item, dict)
            for y, m, d in [_date_parts(_appointment_datetime(item) or "") or ("0", "0", "0")]
            if y != "0"
        }
    )
    match = next((d for d in offered_dates if d.weekday() == weekday), None)
    if match is None:
        match = next((d for d in dates[1:] if d.weekday() == weekday), None)
    return match.isoformat() if match else None


_UNPADDED_TIME_RE = re.compile(r"(?:[a-z ]*?)([1-9]):([0-5]\d)(?: ?h(?:rs?)?\.?)?")
_BARE_HOUR_RE = re.compile(r"^\D*?(\d{1,2})\D*$")


def _resolve_time_reference(reply: Any, offered: Any, day: Any) -> str | None:
    """
    The offered HH:MM on `day` that `reply` unambiguously names, or None.

    A time written in full ("10:30", "3 pm" already cleaned to 15:00) must be one of the offered
    times. A bare hour ("a las 3") is accepted only when exactly one of that hour and its
    afternoon twin is offered on the hour sharp: with both, or neither, the contact must say
    which, instead of the agent guessing am or pm.
    """
    if not isinstance(reply, str) or not isinstance(day, str) or not isinstance(offered, list):
        return None
    day_parts = _date_parts(day)
    if day_parts is None:
        return None
    times = {
        _time_part(item["start_local"])
        for item in offered
        if isinstance(item, dict)
        and isinstance(item.get("start_local"), str)
        and _date_parts(item["start_local"]) == day_parts
    } - {None}
    text = _clean_slot_time(reply.strip())
    full = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if full is not None:
        unpadded = _UNPADDED_TIME_RE.fullmatch(_fold(reply).strip())
        if unpadded is not None:
            # "3:00" with no am or pm and no leading zero can be 03:00 or 15:00: only a single offered one counts.
            hour, minutes = int(unpadded.group(1)), unpadded.group(2)
            matches = [f"{h:02d}:{minutes}" for h in (hour, hour + 12) if f"{h:02d}:{minutes}" in times]
            return matches[0] if len(matches) == 1 else None
        wanted = f"{int(full.group(1)):02d}:{full.group(2)}"
        return wanted if wanted in times else None
    bare = _BARE_HOUR_RE.match(text)
    if bare is None or re.search(r"\b(am|pm|manana|tarde|noche)\b", _fold(text).replace(".", "")):
        return None
    hour = int(bare.group(1))
    if hour > 23:
        return None
    twins = {hour} if hour == 0 or hour > 12 else {hour % 12, hour % 12 + 12}
    matches = sorted(f"{h:02d}:00" for h in twins if f"{h:02d}:00" in times)
    return matches[0] if len(matches) == 1 else None


def _day_label(day: Any, language: Any) -> str | None:
    """`day` (YYYY-MM-DD) written as weekday, day and month in the conversation's language."""
    parts = _date_parts(day) if isinstance(day, str) else None
    if parts is None:
        return None
    date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    code = _LANGUAGE_CODE_BY_NAME.get(str(language or "").strip().lower(), "es")
    weekday = _WEEKDAY_NAMES[code][date.weekday()]
    month = _MONTH_NAMES[code][date.month - 1]
    if code == "en":
        return f"{weekday}, {month} {date.day}"
    return f"{weekday} {date.day} de {month}"


def _location_label(llm_client: LLMClient, location: Any, time_zone: Any, language: Any) -> str | None:
    """
    The country and city a contact wrote ("spian, sevila") as 'Country - City' in the conversation's language.

    Only the names need a model: it fixes the spelling and gives each name in that language, which a
    general instruction did not get right (an English conversation came back as 'España - Sevilla').
    """
    if not isinstance(location, str) or not location.strip():
        return None
    name = {"es": "Spanish", "en": "English", "pt": "Portuguese"}[_language_key(language) or "es"]
    prompt = (
        f"A contact wrote the country and city where they are as: {location.strip()!r} "
        f"(their IANA time zone is {time_zone}).\n"
        f"Write them as 'Country - City' in {name}: correct any spelling mistake and use the {name} name of the "
        f"country and of the city, even if the contact wrote them in another language "
        f"(for example Italy - Rome in English, Itália - Roma in Portuguese, Italia - Roma in Spanish).\n"
        "Reply with only that text."
    )
    label = " ".join(llm_client.complete(prompt, temperature=0.0).strip().strip("\"'").split())
    return label or None


def _day_full(day: Any, language: Any) -> str | None:
    """`day` (YYYY-MM-DD) as a heading with the weekday capitalized: 'Martes 10 de noviembre' / 'Tuesday, November 10'."""
    label = _day_label(day, language)
    return label[:1].upper() + label[1:] if label else None


_MONTH_ABBREVIATIONS = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
}


def _day_title(day: Any, language: Any) -> str | None:
    """`day` (YYYY-MM-DD) as the short heading of a list of times: 'Miércoles. 4 nov' / 'Wednesday. Nov 4'."""
    parts = _date_parts(day) if isinstance(day, str) else None
    if parts is None:
        return None
    date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    code = _language_key(language) or "es"
    weekday = _WEEKDAY_NAMES[code][date.weekday()]
    weekday = weekday[:1].upper() + weekday[1:]
    month = _MONTH_ABBREVIATIONS[code][date.month - 1]
    return f"{weekday}. {month} {date.day}" if code == "en" else f"{weekday}. {date.day} {month}"


def _pick_appointment_field(items: Any, field: str, day: Any, time: Any) -> Any:
    """
    `field` of the one appointment in `items` that starts on `day` at `time` in its own `start_local`.

    The contact picks a day and a time in their own timezone, while the booking tool needs the
    matching `start_co` instant: the offset between the two is exactly what a model gets wrong
    (a 21:00 pick came back as the 20:00 slot). Matching both the date and the time of
    `start_local` is mechanical. None unless exactly one appointment matches.
    """
    if not isinstance(items, list) or not isinstance(day, str) or not isinstance(time, str):
        return None
    day_parts = _date_parts(day)
    time_match = re.search(r"(\d{1,2}):(\d{2})", time)
    if day_parts is None or time_match is None:
        return None
    wanted_time = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
    matches = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("start_local")
        if isinstance(start, str) and _date_parts(start) == day_parts and _time_part(start) == wanted_time:
            matches.append(item)
    if len(matches) != 1:
        return None
    return matches[0].get(field)


def _llm_compute_store_value(llm_client: LLMClient, slot_name: str, instruction: str, ctx: LLMContext) -> Any:
    policy_block = f"House rules:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    prompt = (
        f"{ctx.block(instruction)}"
        f"{policy_block}"
        f"Compute the new value of `{slot_name}` per this instruction: {instruction!r}\n"
        "Reply with just the resulting value, nothing else."
    )
    return _blank_word_to_none(llm_client.complete(prompt))


_BRACKET_REF_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]")
_COMPARISON_VERB_RE = re.compile(r"^(compare|validate|check|ensure|verify|confirm)\b", re.IGNORECASE)


def _is_recognized_mutation_line(line: str) -> bool:
    """True for a DO/STORE line `_apply_store_line` already resolves mechanically.
    """
    stripped = line.strip()
    return bool(_STORE_INCREMENT_RE.match(stripped) or _STORE_ASSIGN_RE.match(stripped))


def _is_comparison_only_line(line: str) -> bool:
    """True for a DO line that only describes a comparison/validation check — almost always context for a sibling `eval: "llm"` ROUTE condition, not an instruction to change the slot(s) it names (2026-09-17, found live: `SC_DEC_D`'s `"Compare [day] only against the start_local dates in [available_slots].

    Do not accept approximate, inferred, or unlisted days."` was fed to `_apply_conditional_ mutations` as if it might be updating `[day]`/`[available_slots]` — the model obliged, overwriting `available_slots` (a list of real appointment objects) with an arbitrary string, corrupting state a sibling node then rendered straight into a user-facing message. A mechanical exclusion on the line's leading verb is a safe, narrow guard for this exact shape — a false negative here just means the line falls back to being judged by the LLM call below, same as before this existed; it can never cause a *new* false positive.
    """
    return bool(_COMPARISON_VERB_RE.match(line.strip()))


def _apply_conditional_mutations(
    lines: list[str],
    ctx: LLMContext,
    llm_client: LLMClient,
) -> None:
    """Resolve DO/STORE lines shaped as conditional prose ("If X, update Y") — a third convention real content uses, distinct from `[slot] = value` (STORE's own grammar) and `input_name = [slot]` (action-node tool-argument binding).

    A mechanical parser cannot safely branch on free-text conditions like "if the
    correction is about the name" or infer 'surrogacy' from "quiero alguien que
    lleve a mi bebé" — those require the same real language understanding a
    `question` node's own capture step already relies on. So there is no
    mechanical pass here at all: any DO/STORE line that isn't a recognized literal
    assignment (`_is_recognized_mutation_line`) but still names a `[slot]` goes
    straight to one batched LLM call per node (never one call per line), covering
    every slot any of that node's conditional lines mentions together — so the
    model sees the full picture (e.g. SC_FIX's "name vs phone vs email vs date"
    branches) against the single latest user message, the same way a human agent
    reading all of them at once would. A line with no `[slot]` reference at all
    (e.g. "TOOL CALL ONLY: call check_visa now.") is narrative, not a mutation,
    and is left untouched — same as `_apply_store_line`'s existing behavior.

    The schema is keyed by *slot*, not by line, each with its own boolean
    `applies` gate — deliberately finer-grained than gating per instruction
    line: real content bundles independent per-slot conditions into one line
    ("If the correction is the name, update [c_name]; the phone, [c_phone]; "
    "the email, [c_email]." is three conditions, not one), so a per-line gate
    still forced the model to invent a value for a slot whose own condition
    didn't hold, just because a sibling slot's condition on the same line did.
    A flat, ungated schema was tried even before that and asked the model to
    echo back every untouched slot's current value to signal "no change" —
    which silently corrupted a slot whose real value is a list (e.g.
    `available_slots`, a list of appointment objects) into `null`, since the
    schema's scalar-only types gave the model no way to reproduce a list.
    Gating per slot means a slot whose condition didn't fire is simply never
    touched in `slots`, regardless of what type its current value is.
    """
    conditional_lines = [
        line
        for line in lines
        if not _is_recognized_mutation_line(line)
        and not _is_comparison_only_line(line)
        and _BRACKET_REF_RE.search(line)
    ]
    if not conditional_lines:
        return

    target_slots = sorted({name for line in conditional_lines for name in _BRACKET_REF_RE.findall(line)})
    schema = {
        "type": "object",
        "properties": {
            name: {
                "type": "object",
                "properties": {
                    "applies": {"type": "boolean"},
                    "value": {"type": ["string", "boolean", "integer", "null"]},
                },
                "required": ["applies", "value"],
                "additionalProperties": False,
            }
            for name in target_slots
        },
        "required": target_slots,
        "additionalProperties": False,
    }
    context_lines = "\n".join(ctx.goal)
    instructions = "\n".join(f"- {line}" for line in conditional_lines)
    policy_block = f"House rules:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    prompt = (
        "You are applying conditional update instructions to a conversational agent's "
        "memory slots, based on the user's latest message.\n\n"
        f"This step's purpose:\n{context_lines}\n\n"
        f"Instructions:\n{instructions}\n\n"
        f"{ctx.block(instructions)}"
        f"{policy_block}"
        f"For each of these slots — {', '.join(target_slots)} — decide independently "
        "whether an instruction above clearly applies to THAT slot specifically, given "
        "the latest message, and set its `applies` field accordingly. A line naming "
        "several slots together (e.g. 'the name, X; the phone, Y') describes one "
        "condition per slot, not one shared condition — judge each slot on its own. "
        "The latest message may give no real signal for a slot at all (e.g. a bare "
        "greeting) — when you are not reasonably confident the condition is actually "
        "met, set `applies` to false rather than guessing at a value. "
        "Only when a slot's `applies` is true, also set its `value` to the new value "
        "(or null, if the instruction says to clear it). When `applies` is false, "
        "`value` is ignored, so its content does not matter."
    )
    response = llm_client.extract_structured(prompt, schema)
    for name in target_slots:
        entry = response.get(name) or {}
        if entry.get("applies"):
            ctx.slots[name] = _blank_word_to_none(entry.get("value"))


def _coerce_constant(value: str) -> Any:
    if value.lstrip("-").isdigit():
        return int(value)
    return value


# ---------------------------------------------------------------------------
# Capture extraction (question nodes)
# ---------------------------------------------------------------------------

_LITERAL_MEMBERS_RE = re.compile(r"^Literal\[(.+)\]$")


def _literal_members(type_expr: str) -> list[str] | None:
    match = _LITERAL_MEMBERS_RE.match(type_expr.strip())
    if not match:
        return None
    return [m.strip() for m in match.group(1).split(",")]


_LIST_ITEM_RE = re.compile(r"^list\[\s*(.*?)\s*\]$", re.DOTALL)


def _list_item_members(type_expr: str) -> list[str] | None:
    """Return the Literal members of a `list[...]` type (empty for `list[str]`), or None if not a list type."""
    match = _LIST_ITEM_RE.match(type_expr.strip())
    if not match:
        return None
    return _literal_members(match.group(1)) or []


def _json_schema_type(type_expr: str) -> dict[str, Any]:
    """Map a `type_expr` to a nullable JSON-Schema property (OpenAI Structured Outputs).
    """
    list_members = _list_item_members(type_expr)
    if list_members is not None:
        items: dict[str, Any] = {"type": "string"}
        if list_members:
            items["enum"] = list_members
        return {"type": ["array", "null"], "items": items}
    members = _literal_members(type_expr)
    if members:
        return {"type": ["string", "null"], "enum": [*members, None]}
    if type_expr == "bool":
        return {"type": ["boolean", "null"]}
    if type_expr == "int":
        return {"type": ["integer", "null"]}
    return {"type": ["string", "null"]}


def _capture_json_schema(capture: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {slot: _json_schema_type(type_expr) for slot, type_expr in capture},
        "required": [slot for slot, _ in capture],
        "additionalProperties": False,
    }


_ANSWERS_FIELD = "answers_the_question"
def _llm_extract_capture(
    llm_client: LLMClient,
    capture: list[tuple[str, str]],
    ctx: LLMContext,
) -> dict[str, Any]:
    """Ask the model to extract the declared capture slots from the user's reply.

    Takes the shared `LLMContext` (2026-09-17) rather than its own hand-picked
    parameter list — this call site was found live missing `slots` (a `free_text`
    capture like `[day]` has no way to normalize "el 22" against the real dates in
    `[available_slots]` without seeing it) the same way an earlier pass found it
    missing `history`; bundling every decision call onto one context type is the
    fix for that entire *class* of gap, not just this one instance of it.

    `ctx.goal`/`ctx.do` carry the DSL's own normalization instructions (e.g. two
    enum members that must stay distinct categories, not synonyms) — that guidance
    only exists there, nowhere else. `ctx.pending_question` is the question this
    reply is answering. `ctx.policies` (2026-09-18) is the artifact's
    `judgment_policies` — see `LLMContext`'s own docstring.
    """
    context_lines = "\n".join(ctx.goal + ctx.do)
    policy_block = f"House rules:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    prompt = (
        "You are extracting structured data from a chat reply for a conversational "
        "agent's memory slots. The agent just asked:\n"
        f"{ctx.pending_question}\n\n"
        f"{ctx.block()}"
        f"{policy_block}"
        f"Normalization instructions for this step:\n{context_lines}\n\n"
        "Extract the fields defined by the provided schema, following the "
        "normalization instructions above. Use null for anything not clearly stated."
    )
    schema = _capture_json_schema(capture)
    if capture:
        # A reply about something else used to be filed anyway: under the nearest option of a closed
        # list ("I'm 30" to "are you interested?" became maybe) or as an invented value ("yes" to "how
        # many children?" became 1, to "when was your last birth?" today's date). The model says first
        # whether the reply answers the question at all.
        schema["properties"][_ANSWERS_FIELD] = {"type": "boolean"}
        schema["required"].append(_ANSWERS_FIELD)
        prompt += (
            f"{chr(10)}{chr(10)}Also set {_ANSWERS_FIELD}: true only if the reply actually answers the question "
            "just asked, even briefly or indirectly; false if it talks about something else or gives "
            "another piece of information."
        )
    extracted = llm_client.extract_structured(prompt, schema)
    answers = extracted.pop(_ANSWERS_FIELD, True)
    # A plain yes/no does answer a closed question, however the model judged it, but never a name or a place.
    closed = all(type_expr.strip().startswith(("Literal", "bool")) for _, type_expr in capture)
    if capture and answers is False and not (closed and _is_bare_yes_no(ctx.last_user_message)):
        return {}
    return extracted


def _coerce_list(value: Any) -> Any:
    """Turn a list-typed value that arrived as text (a JSON array or comma-separated) into a real list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
    return [part.strip() for part in text.strip("[]").replace('"', "").split(",") if part.strip()]


_EMPTY_WORDS = frozenset({"null", "none", "n/a", "undefined", ""})


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _clean_email(value: str) -> str | None:
    """The email in lowercase, or None when what was typed is not an address ("juan@")."""
    email = value.strip().lower()
    return email if _EMAIL_RE.match(email) else None


_EMAIL_IN_TEXT_RE = re.compile(r"[^\s@,;:<>()\[\]]+@[^\s@,;:<>()\[\]]+\.[^\s@,;:<>()\[\]]{2,}")
_EMAIL_UPDATED_ACK = "Thanks, I updated your email to [{slot}]."


def _correct_contact_email(slots: dict[str, Any], capture: list[tuple[str, str]], reply: str) -> str | None:
    """
    The address the contact wrote in `reply` when it replaces the email already kept for the appointment.

    Someone who mistyped their email says "sorry, it is ...@gmail.com" to whatever is asked next
    (the day, the time), and the question took it for a wrong answer, so the confirmation went to the
    typo. The address is read mechanically, with no model call. The summary question is left alone:
    its own `fix` capture applies corrections and the summary is shown again. Returns the
    name of the slot that was replaced, or None.
    """
    match = _EMAIL_IN_TEXT_RE.search(reply or "")
    email = _clean_email(match.group(0).rstrip(".")) if match else None
    key = next((k for k in slots if k == "c_email" or k.endswith("__c_email")), None)
    if email is None or key is None or not slots.get(key) or slots[key] == email:
        return None
    if any(type_expr.strip() == "email" or name.endswith("fix") for name, type_expr in capture):
        return None
    slots[key] = email
    return key


def _clean_phone(value: str) -> str | None:
    """The phone without spaces or punctuation (a leading 00 written as +), or None when it cannot be a number."""
    phone = re.sub(r"[\s().-]", "", value)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone if re.fullmatch(r"\+?\d{8,15}", phone) else None


_SLOT_TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?:\s*(?:([ap])\.?\s?m\b\.?|de la (ma[ñn]ana|tarde|noche)))?(?!\d)",
    re.IGNORECASE,
)
_SLOT_HOUR_RE = re.compile(
    r"(?<![\d:])(\d{1,2})\s*(?:([ap])\.?\s?m\b\.?|de la (ma[ñn]ana|tarde|noche))",
    re.IGNORECASE,
)


def _clean_slot_time(value: str) -> str:
    """The time inside what was captured ("9:40 am", "1:10 de la tarde", a full timestamp) as 24-hour HH:MM; the text itself when it holds none."""
    match = _SLOT_TIME_RE.search(value)
    if match is not None:
        hour, minute, meridiem, period = int(match.group(1)), match.group(2), match.group(3), match.group(4)
    else:
        match = _SLOT_HOUR_RE.search(value)
        if match is None:
            return value
        hour, minute, meridiem, period = int(match.group(1)), "00", match.group(2), match.group(3)
    word = (meridiem or (period or "")[:1]).lower()
    if word in ("p", "t") and hour < 12:
        hour += 12
    elif word == "n" and hour < 12:
        hour = hour + 12 if hour >= 6 else hour
    elif word == "a" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}" if hour < 24 else value


def _blank_word_to_none(value: Any) -> Any:
    """A model clearing a slot sometimes writes the word "null"; kept as text it would read as a value."""
    if isinstance(value, str) and value.strip().lower() in _EMPTY_WORDS:
        return None
    return value


def _coerce_value(value: Any, type_expr: str) -> Any:
    """Best-effort coercion of a value against its declared type_expr.

    Two callers (2026-09-17): a question node's capture extraction (the
    original use — an LLM-extracted value against its `capture` schema type),
    and `_bind_tool_inputs` (a mechanically-resolved tool argument against
    its *contract's own* declared type) — found live: `book_appointment`'s
    `duration` input is declared `type_expr: "int"`, bound mechanically from
    `<APPOINTMENT_DURATION_MINUTES>` (a compile-time constant `initial_slots()`
    coerces to a real Python `int`), but the actual backend's Pydantic schema
    expects a JSON string (`HTTP 422: "Input should be a valid string"`) — a
    real mismatch between the tool's declared contract type and its backend's
    real wire shape, silently untyped because mechanical binding (unlike the
    LLM-fallback path, which gets JSON-schema type enforcement for free) never
    coerced its resolved value against anything at all.
    """
    if value is None:
        return None
    if (
        isinstance(value, str)
        and value.strip().lower() in _EMPTY_WORDS
        and not type_expr.strip().startswith("Literal")
    ):
        # A model asked for a value the reply does not contain sometimes writes the word
        # "null" instead of leaving it empty; stored as text it would pass for a real
        # email, time or name. A Literal keeps its own members ('none' can be one).
        return None
    if isinstance(value, str) and type_expr.strip() == "email":
        return _clean_email(value)
    if isinstance(value, str) and type_expr.strip() == "phone_number":
        return _clean_phone(value)
    if isinstance(value, str) and type_expr.strip() == "appointment_slot_selection":
        return _clean_slot_time(value)
    if _list_item_members(type_expr) is not None:
        return _coerce_list(value)
    parsed = classify_type_expr(type_expr)
    if parsed.category == "canonical" and type_expr == "bool":
        return bool(value)
    if parsed.category == "canonical" and type_expr == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if parsed.category == "canonical" and type_expr == "str":
        return str(value)
    return value


# ---------------------------------------------------------------------------
# `say` rendering and slot interpolation
# ---------------------------------------------------------------------------

_LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "pt": "Portuguese"}


def _language_name_from_slots(slots: dict[str, Any] | None, fallback: str | None = None) -> str | None:
    """Resolve full language name from slots['preferred_language'] (code or name)."""
    if not slots:
        return fallback
    value = slots.get("preferred_language")
    if not isinstance(value, str):
        return fallback
    v = value.strip()
    if v.lower() in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[v.lower()]
    return v if v in set(_LANGUAGE_NAMES.values()) else fallback


_INTERPOLATION_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]|<([A-Z_][A-Z0-9_]*)>|\{\{\s*contact\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_CONTACT_PLACEHOLDER_RE = re.compile(r"\{\{\s*contact\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ISO_TIME_RE = re.compile(r"T(\d{2}):(\d{2})")
_STANDALONE_NUMBER_RE = re.compile(r"\b\d{1,2}\b")
_CONSTANT_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_MONTH_NAMES = {
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "pt": [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ],
}

_DateParts = tuple[str, str, str]  # (yyyy, mm, dd)


def _appointment_datetime(item: dict[str, Any]) -> str | None:
    start = item.get("start_local") or item.get("start_co")
    return start if isinstance(start, str) else None


def _date_parts(iso_text: str) -> _DateParts | None:
    match = _ISO_DATE_RE.match(iso_text.strip())
    return match.groups() if match else None  # type: ignore[return-value]


def _time_part(iso_text: str) -> str | None:
    match = _ISO_TIME_RE.search(iso_text)
    return f"{match.group(1)}:{match.group(2)}" if match else None


def _format_date_human(date_parts: _DateParts, language_code: str | None) -> str:
    year, month, day = date_parts
    months = _MONTH_NAMES.get(language_code or "es", _MONTH_NAMES["es"])
    month_name = months[int(month) - 1]
    day_number = str(int(day))
    if language_code == "en":
        return f"{month_name} {day_number}, {year}"
    return f"{day_number} de {month_name} de {year}"


_ANY_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _captured_string_values(slots: dict[str, Any]) -> list[str]:
    """Non-empty string values of `slots`, excluding compile-time constants.

    A constant (`RuntimeArtifact.constants`, seeded into `slots` under its
    exact `UPPER_SNAKE_CASE` name — the same naming convention `_CONST_REF_RE`
    already relies on) never represents anything the user said, so it must
    never be treated as a candidate "the user already picked this date"
    signal. Found live (2026-09-17): `PROCESS_DURATION_MONTHS` (value `"24"`)
    was picked up by the day-of-month heuristic below as if the user had
    already chosen the 24th, before `[day]` was ever asked, silently
    filtering `SC_DAYS`'s very first display down to one wrong day's times.
    Excluding every all-uppercase-named slot closes the whole category, not
    just this one constant — any future constant with a short numeric value
    has the same latent risk.
    """
    return [
        value
        for name, value in slots.items()
        if not _CONSTANT_NAME_RE.match(name) and isinstance(value, str) and value.strip()
    ]


def _find_selected_date(slots: dict[str, Any], candidate_dates: set[_DateParts]) -> _DateParts | None:
    """Does an already-captured slot name one of `candidate_dates`?

    Two passes, most reliable first: (1) a slot whose value is itself an
    ISO date string exactly matching one candidate, (2) only when that
    finds nothing, a slot whose value contains a standalone 1-2 digit
    number matching exactly one candidate's day-of-month — a `free_text`
    capture like `[day]` (e.g. "el 22") is never guaranteed to be
    ISO-normalized, so this loose fallback is what actually fires for real
    content; it only ever acts when the day-of-month is unambiguous among
    the dates on offer, so a coincidental number elsewhere (a retry count,
    a phone digit run — `` never matches inside one) can't misfire into
    a wrong single-day filter. Both passes only ever look at real captured
    slots (`_captured_string_values`), never compile-time constants.
    """
    values = _captured_string_values(slots)

    for value in values:
        # A bare date only: a timestamp (a `now` anchor) or a list of dates (a
        # `calendar`) is a reference, never the date the contact picked.
        if len(value.strip()) > 10:
            continue
        parts = _date_parts(value)
        if parts is not None and parts in candidate_dates:
            return parts

    by_day_number: dict[str, set[_DateParts]] = {}
    for parts in candidate_dates:
        by_day_number.setdefault(str(int(parts[2])), set()).add(parts)

    for value in values:
        # Anything already written as an ISO date or timestamp is handled
        # above; its loose numbers (a `calendar`, a `now` anchor) name nothing.
        if _ANY_ISO_DATE_RE.search(value):
            continue
        numbers = {n for n in _STANDALONE_NUMBER_RE.findall(value) if n in by_day_number}
        if len(numbers) != 1:
            continue
        matches = by_day_number[next(iter(numbers))]
        if len(matches) == 1:
            return next(iter(matches))
    return None


def _format_appointment_list(items: list[dict[str, Any]], slots: dict[str, Any], language_code: str | None) -> str:
    """Format a `[slot]`-shaped list of appointment objects for display.

    The root-cause fix (2026-09-17) for `SC_DAYS`/`SC_HOURS` dumping the
    same raw `start - end; start - end` text regardless of what the DSL's
    own `goal:` asked for ("use only the date part", "filter by [day] and
    use only the time part") — those instructions described a real data
    transformation that no code ever executed, since a `say_verbatim: true`
    block (required here — real appointment data must never be
    paraphrased) never goes through the LLM at all. Mechanical and
    deterministic by design: this is live booking data, zero hallucination
    risk is worth more than handling every possible shape.

    Detects which transformation to apply generically, from data already
    on hand — no new DSL syntax, no hardcoded slot/agent names (chosen
    directly, 2026-09-17): if some other already-captured slot names one of
    this list's dates (`_find_selected_date`), show only that date's times;
    otherwise show the distinct dates on offer. The same mechanism serves
    both `SC_DAYS` (asked before `[day]` exists — no match, shows dates)
    and `SC_HOURS` (asked after `[day]` is captured — matches, shows
    times) without either node needing its own code path.
    """
    dated_items: list[tuple[_DateParts, str | None]] = []
    for item in items:
        start = _appointment_datetime(item)
        parts = _date_parts(start) if start else None
        if parts is not None:
            dated_items.append((parts, _time_part(start)))

    if not dated_items:
        # Not the expected start_local/start_co ISO shape at all -- fall
        # back to the old raw dump rather than silently show nothing.
        parts_out = []
        for item in items:
            start = item.get("start_local") or item.get("start_co", "?")
            end = item.get("end_local") or item.get("end_co", "?")
            parts_out.append(f"{start} - {end}")
        return "; ".join(parts_out)

    candidate_dates = {date_parts for date_parts, _ in dated_items}
    # Even with a single date on offer the times are shown only once the contact has picked that day;
    # before that the list must name the date, or "which day?" is asked about a list with no days in it.
    selected_date = _find_selected_date(slots, candidate_dates)

    step = _slot_step_minutes(dated_items)
    if selected_date is not None:
        times = sorted({t for date_parts, t in dated_items if date_parts == selected_date and t})
        if times:
            return _times_by_part_of_day(times, step, language_code)

    lines = []
    for date_parts in sorted(candidate_dates):
        times = sorted({t for d, t in dated_items if d == date_parts and t})
        day_parts = _parts_of_day(times, language_code)
        lines.append(f"🗓️ {_date_title(date_parts, language_code)}" + (f"\n └─ {day_parts}" if day_parts else ""))
    return "\n".join(lines)


def _date_title(date_parts: _DateParts, language_code: str | None) -> str:
    """'Martes 3 de noviembre' / 'Tuesday, November 3': the weekday and day, no year."""
    code = language_code if language_code in _MONTH_NAMES else "es"
    label = _day_label("-".join(date_parts), {"es": "spanish", "en": "english", "pt": "portuguese"}[code]) or ""
    return label[:1].upper() + label[1:]


_PARTS_OF_DAY = (
    (0, 6, {"es": "madrugada", "en": "early morning", "pt": "madrugada"}),
    (6, 12, {"es": "mañana", "en": "morning", "pt": "manhã"}),
    (12, 19, {"es": "tarde", "en": "afternoon", "pt": "tarde"}),
    (19, 24, {"es": "noche", "en": "night", "pt": "noite"}),
)


def _minutes(time_text: str) -> int:
    hours, minutes = time_text.split(":")
    return int(hours) * 60 + int(minutes)


def _parts_of_day(times: list[str], language_code: str | None) -> str:
    """The parts of the day (madrugada, mañana, tarde, noche) that have at least one of `times`, in order."""
    code = language_code if language_code in _MONTH_NAMES else "es"
    hours = {_minutes(t) // 60 for t in times}
    return " · ".join(
        names[code].capitalize() for start, end, names in _PARTS_OF_DAY if any(start <= h < end for h in hours)
    )


def _slot_step_minutes(dated_items: list[tuple[_DateParts, str | None]]) -> int:
    """The spacing between consecutive offered times: the smallest gap seen on any day (30 when there is none)."""
    gaps = []
    for date_parts in {d for d, _ in dated_items}:
        times = sorted({_minutes(t) for d, t in dated_items if d == date_parts and t})
        gaps.extend(b - a for a, b in zip(times, times[1:]))
    return min(gaps) if gaps else 30


_RANGE_WORDS = {"es": "a", "en": "to", "pt": "a"}


def _times_by_part_of_day(times: list[str], step: int, language_code: str | None) -> str:
    """The times of one day under a heading per part of the day, a blank line between the parts."""
    code = language_code if language_code in _MONTH_NAMES else "es"
    blocks = []
    for start, end, names in _PARTS_OF_DAY:
        part = [t for t in times if start <= _minutes(t) // 60 < end]
        if part:
            blocks.append("\n".join([names[code].capitalize(), *_time_ranges(part, step, language_code)]))
    return "\n\n".join(blocks)


def _time_ranges(times: list[str], step: int, language_code: str | None = None) -> list[str]:
    """`times` (sorted HH:MM) as single times and ranges of consecutive ones: '🕐 07:00', '🕐 09:00 a 11:30'."""
    word = _RANGE_WORDS.get(language_code or "es", "a")
    runs: list[list[str]] = []
    for t in times:
        if runs and _minutes(t) - _minutes(runs[-1][-1]) == step:
            runs[-1].append(t)
        else:
            runs.append([t])
    return [f"🕐 {run[0]}" if len(run) == 1 else f"🕐 {run[0]} {word} {run[-1]}" for run in runs]


def _is_booked_appointment(value: Any) -> bool:
    """An appointment the contact already has (from find_appointment), as opposed to an offered slot."""
    return isinstance(value, dict) and "event_id" in value and isinstance(value.get("start_time"), str)


def _format_booked_appointments(items: list[dict[str, Any]], language_code: str | None) -> str:
    """
    The contact's booked appointments, soonest first, one line each (numbered when there are several).

    Written by code so every list reads the same: a model asked to list them wrote a different
    layout each time, and the raw record (JSON) showed up when it was interpolated whole.
    """
    code = language_code if language_code in _MONTH_NAMES else "es"
    lines = []
    for item in sorted(items, key=lambda i: i["start_time"]):
        parts = _date_parts(item["start_time"])
        if parts is None:
            lines.append(item["start_time"])
            continue
        date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        weekday = _WEEKDAY_NAMES[code][date.weekday()]
        month = _MONTH_NAMES[code][date.month - 1]
        day = f"{weekday}, {month} {date.day}, {date.year}" if code == "en" else f"{weekday} {date.day} de {month} de {date.year}"
        time = _time_part(item["start_time"])
        lines.append(f"📅 {day}" + (f" 🕐 {time}" if time else ""))
    if len(lines) > 1:
        lines = [f"{number}. {line}" for number, line in enumerate(lines, 1)]
    return "\n".join(lines)


def _interpolate_slots(
    text: str, slots: dict[str, Any], language_code: str | None = None, contact: dict[str, Any] | None = None
) -> str:
    """Replace `[slot_name]` and `<CONSTANT>` references in `say` text with their current value.

    Real content authors both forms in `say:` blocks — `[slot]` for a
    captured value, `<CONSTANT>` for a compile-time constant like
    `<AGENT_NAME>`/`<COMPANY_NAME>`/`<PROCESS_DURATION_MONTHS>` — but this
    function only ever substituted the first (2026-09-17: found live,
    `<AGENT_NAME>` etc. showed up literally, unresolved, in every real
    conversation this whole session). `initial_slots()` already seeds every
    compile-time constant into `slots` under its exact uppercase name
    (`RuntimeArtifact.constants`, needed for `MAX_RETRY_ATTEMPTS`-style
    retry-limit conditions to `eval()` at all) — the constant's *value* was
    always one dict lookup away, `_interpolate_slots` just never looked.

    A name missing from `slots` is left as its original bracket token
    (either form) rather than silently blanked, so a real gap stays visible
    instead of disappearing.

    `language_code` (2026-09-17) only matters for a list-of-appointment-
    objects value's human-readable date formatting (`_format_appointment_
    list`) — every other value renders the same regardless.
    """

    language_code = _language_key(language_code)

    def _format_value(value: Any) -> str:
        if isinstance(value, str) and value.lstrip().startswith("{"):
            # A chosen appointment can arrive as its JSON text.
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            value = parsed if _is_booked_appointment(parsed) else value
        if _is_booked_appointment(value):
            return _format_booked_appointments([value], language_code)
        if isinstance(value, list) and value and all(_is_booked_appointment(item) for item in value):
            return _format_booked_appointments(value, language_code)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return _format_appointment_list(value, slots, language_code)
        return str(value)

    def repl(match: re.Match[str]) -> str:
        if match.group(3) is not None:
            value = (contact or {}).get(match.group(3))
            return match.group(0) if value in (None, "") else str(value)
        name = match.group(1) or match.group(2)
        if name not in slots or slots[name] is None:
            return match.group(0)
        return _format_value(slots[name])

    return _INTERPOLATION_RE.sub(repl, text)

def _protect_contact_values(text: str, contact: dict[str, Any] | None, protected: dict[str, str]) -> str:
    """Swap each `{{contact.field}}` the contact has for an opaque `<CONTACT_FIELD>` token.

    The paraphrasing model rewrites names it sees (adding or dropping accents),
    but leaves a placeholder token alone; `_restore_contact_values` puts the real
    value back afterwards. Fields the contact lacks stay as written.

    Args:
        text: Say text before interpolation.
        contact: The session's CRM contact fields.
        protected: Filled with token -> real value, to restore after paraphrasing.

    Returns:
        The text with the contact placeholders replaced by tokens.
    """

    def repl(match: re.Match[str]) -> str:
        value = (contact or {}).get(match.group(1))
        if value in (None, ""):
            return match.group(0)
        token = f"<CONTACT_{match.group(1).upper()}>"
        protected[token] = str(value)
        return token

    return _CONTACT_PLACEHOLDER_RE.sub(repl, text)


_PART_HEADINGS = frozenset(
        names[code].capitalize() for _, _, names in _PARTS_OF_DAY for code in names
)
_LIST_LINE_RE = re.compile(r"^(\d+\. )?[📅🕐🗓├└🌎]")


def _protect_lists(text: str, protected: dict[str, str]) -> str:
    """
    `text` with each block of date/time lines (the 📅 and 🕐 lists code wrote) swapped for a `<LIST_n>` token.

    The paraphrasing model translated and reshuffled the parts of the day ("(por la tarde)",
    "por la mañana y por la tarde") and merged ranges, so the same list read differently every
    time; the list is code-made data and goes back in untouched.
    """
    lines = text.split("\n")
    out: list[str] = []
    block: list[str] = []
    for line in lines + [None]:
        if line is not None and (_LIST_LINE_RE.match(line.lstrip(" |")) or line in _PART_HEADINGS):
            block.append(line)
            continue
        if block:
            token = f"<LIST_{len(protected) + 1}>"
            protected[token] = "\n".join(block)
            out.append(token)
            block = []
        if line is not None:
            out.append(line)
    return "\n".join(out)


def _protect_place(text: str, slots: dict[str, Any], protected: dict[str, str]) -> str:
    """
    `text` with the contact's country and city (`location_label`) swapped for a `<LIST_n>` token.

    The label is written by code in the conversation's language ('Japan - Tokyo'); a rewording of the
    sentence around it would otherwise translate or respell it.
    """
    place = slots.get("location_label")
    if not isinstance(place, str) or not place or place not in text or place in protected.values():
        return text
    token = f"<LIST_{len(protected) + 1}>"
    protected[token] = place
    return text.replace(place, token)


def _protect_figures(text: str, protected: dict[str, str]) -> str:
    """
    `text` with each time (HH:MM) and long number swapped for a `<NUM_n>` token.

    A rewording that drops or rewrites a figure is thrown away by `_keeps_figures`, and the message
    then goes out in the template's language: "Our support is 360\u00b0" was reworded as "Nuestro soporte es
    completo" every time, so that block always came out in English. With the figure behind a token the
    model only has to keep the token, and the figure itself can never change.
    """

    def repl(match: re.Match[str]) -> str:
        token = f"<NUM_{len(protected) + 1}>"
        protected[token] = match.group(0)
        return token

    return _FIGURE_RE.sub(repl, text)


def _restore_contact_values(text: str, protected: dict[str, str]) -> str:
    for token, value in protected.items():
        text = text.replace(token, value)
    return text


logger = logging.getLogger(__name__)

_ADVISOR_HANDLER_ID = "H_ADVISOR_Q"
_KNOWLEDGE_HANDLER_ID = "H_KB_Q"
"""The handler a side question falls to when no FAQ or handler matched it: the knowledge base
answers it when the agent has one, otherwise the advisor handler hands it to a person."""
_SIDE_QUESTION_FALLBACK_IDS = (_KNOWLEDGE_HANDLER_ID, _ADVISOR_HANDLER_ID)
_LANGUAGE_CHANGE_HANDLER_ID = "H_LANG_CHANGE"


def _sync_language_change(
    previous_language: str | None,
    slots: dict[str, Any],
    contact: dict[str, Any],
    tool_executors: dict[str, Callable[..., dict[str, Any]]],
) -> None:
    """Push `preferred_language` to the CRM `language` field when the global router changed it.

    Fired even when the contact lacks `contact_id`/`location_id`; the tool call may then fail, which is logged only.
    """
    new_language = _language_name_from_slots(slots)
    executor = tool_executors.get("update_custom_field")
    if new_language is None or new_language == previous_language or executor is None:
        return
    inputs = {"name": "language", "value": new_language}
    for key in ("contact_id", "location_id"):
        if contact.get(key):
            inputs[key] = contact[key]
    try:
        executor(**inputs)
    except Exception:
        logger.warning("language sync to CRM failed; continuing", exc_info=True)


_FIGURE_RE = re.compile(r"\d{1,2}:\d{2}|\d{3,}")


def _keeps_figures(original: str, candidate: str) -> bool:
    """
    True when every time (HH:MM) and long number of `original` is still written in `candidate`.

    A rewording once turned the 04:00 of an appointment summary into 16:00. Times, phone numbers
    and the like are facts the contact acts on, so a rewording that changes one is discarded.
    """
    return set(_FIGURE_RE.findall(original)) <= set(_FIGURE_RE.findall(candidate))


def _drop_added_questions(candidate: str, original: str) -> str:
    """
    `candidate` without the closing question lines a rewording tacked on to `original`.

    Right before a question node a model likes to end a list with its own "which one
    do you prefer?"; the real question is asked next, so the extra line is cut instead of
    throwing away the whole translated message.
    """
    candidate = (candidate or "").rstrip()
    lines = candidate.split("\n")
    while lines and candidate.count("?") > original.count("?") and "?" in lines[-1]:
        lines = lines[:-1]
        candidate = "\n".join(lines).rstrip()
    return candidate


def _make_render_say(
    llm_client: LLMClient,
) -> Callable[[str, list[str], bool, str | None, dict[str, Any], list[str] | None], str]:
    """Build a `say`-rendering function.
    """

    def render_say(
        node_id: str,
        say: list[str],
        say_verbatim: bool,
        language_code: str | None,
        slots: dict[str, Any],
        policies: list[str] | None = None,
        user_message: str = "",
        contact: dict[str, Any] | None = None,
    ) -> str:
        """Render a `say` block, paraphrased naturally in the caller's language via the LLM.

        `say_verbatim: true` blocks are never touched — that flag exists
        specifically to forbid paraphrasing legally-sensitive copy. Every
        other block is paraphrased on every render, deliberately never
        cached: the point (2026-09-16, requested directly — real content
        was reading as scripted and repetitive, especially a question
        re-asked verbatim after a failed capture) is that the same node
        visited twice sounds like a person rephrasing, not a script
        replaying, so a cache that returned the same rendering for the
        same node would defeat that on exactly the retry-loop case this
        was meant to fix. Previously this instructed the model to "return
        it unchanged" if already in the target language, which is the
        wording that produced the scripted-repeat feel in the first place.

        Passes `temperature=1.0` explicitly (2026-09-17) — `complete()`'s
        own default is `0.0`, correct for every other caller's factual
        judgment calls, but wrong here: a paraphrase call at temperature 0
        tends toward the single most-likely rewording, which is exactly
        the boring, repetitive sameness this function exists to avoid.

        `policies` (2026-09-18) is the artifact's pre-filtered `say_policies`
        list (`targets/langgraph/runtime_artifact.py` — `compliance_and_
        scope_rules` + `data_and_variable_rules`, decided at compile time,
        not here). Only the `message`/`terminal` call site in `_make_node_fn`
        passes it for now; `question` phrasing and the global-router's
        matched-handler/FAQ `say` still render without it.

        Args:
            user_message: Latest user message; accepted for call sites that pass it.
        """
        protected: dict[str, str] = {}
        text = "\n".join(say)
        if not say_verbatim:
            text = _protect_contact_values(text, contact, protected)
        raw = _interpolate_slots(text, slots, language_code, contact)
        if say_verbatim:
            return raw
        raw = _protect_lists(raw, protected)
        raw = _protect_place(raw, slots, protected)
        raw = _protect_figures(raw, protected)

        language_name = _LANGUAGE_NAMES.get(language_code, language_code) if language_code else None
        in_language = f" in {language_name}" if language_name else ""
        policy_block = (
            f"House rules this message must respect:\n{chr(10).join(policies)}\n\n" if policies else ""
        )
        prompt = (
            f"Rephrase this agent message naturally{in_language}, the way a person "
            "would say it in conversation rather than reading a script — vary the "
            "wording and sentence structure. Preserve the exact meaning, every fact, "
            "and any placeholders like <NAME> exactly as written; do not add, remove, "
            "or soften any information, and never add a question it does not already ask.\n\n"
            f"{policy_block}"
            "Output ONLY the rephrased message itself, "
            "exactly as the agent would send it to the user — no preamble like \"here's "
            "a version of that\", no label, no quotes around it, nothing before or "
            f"after it:\n\n{raw}"
        )
        # The prompt forbids adding questions, but at temperature 1.0 a very short message
        # ("Hasta luego.") sometimes comes back as a whole invented message (a scheduling
        # offer with made-up dates, say). A rewording that adds a question or balloons past
        # the original is discarded. The original text is in the template's language, not
        # the contact's, so a discarded rewording is retried once before falling back to it.
        # The last attempt is a plain translation: two rewordings in a row can both be thrown away
        # (a question tacked on mid-sentence, say), and the message would go out in English.
        translate_prompt = (
            f"Translate this agent message{in_language}, sentence by sentence, as faithfully as possible. "
            "Keep every placeholder like <NAME> exactly as written, add nothing and ask nothing. "
            "Output ONLY the translation:\n\n"
            f"{raw}"
        )
        paraphrased = raw
        for attempt_prompt, temperature in ((prompt, 1.0), (prompt, 0.0), (translate_prompt, 0.0)):
            candidate = _drop_added_questions(llm_client.complete(attempt_prompt, temperature=temperature), raw)
            if (
                candidate
                and candidate.count("?") <= raw.count("?")
                and len(candidate) <= 2 * len(raw) + 60
                and _keeps_figures(raw, candidate)
                and all(token in candidate for token in protected if token.startswith(("<LIST_", "<NUM_")))
            ):
                paraphrased = candidate
                break
        return _restore_contact_values(paraphrased, protected)

    return render_say


# ---------------------------------------------------------------------------
# Edge resolution
# ---------------------------------------------------------------------------


def _matches(value: Any, predicate_name: str) -> bool:
    """Implement the `MATCHES <predicate>` operator for compiled conditions.

    `condition_parser.classify_rule` already refuses to mark a `MATCHES`
    condition mechanical unless `predicate_name` is a registered key in
    `NAMED_PREDICATES` (`targets/langgraph/condition_parser.py`) — this
    function is the runtime counterpart that was missing entirely until
    now: `_EVAL_BUILTINS` never included `_matches`, so a condition
    correctly classified as mechanical (e.g. real content's
    `[document_number] MATCHES numeric_string_without_spaces_or_punctuation`)
    raised `NameError` at eval() time, silently swallowed by
    `resolve_edges`'s `except Exception: continue` — the edge could never
    actually match, regardless of the captured value.
    """
    pattern = NAMED_PREDICATES.get(predicate_name)
    if pattern is None or value is None:
        return False
    return pattern.fullmatch(str(value)) is not None


_EVAL_BUILTINS = {"len": len, "_matches": _matches}


def _make_resolve_edges(
    llm_client: LLMClient,
) -> Callable[[list[GraphEdge], LLMContext], str | None]:
    def resolve_edges(edges: list[GraphEdge], ctx: LLMContext) -> str | None:
        llm_candidates: list[GraphEdge] = []
        for edge in edges:
            if edge.condition_text is None:
                # An unconditional edge is the default: the LLM-judged conditions listed before it
                # still get their turn, and only when none applies does the default win.
                if llm_candidates:
                    chosen = _llm_pick_condition(llm_client, llm_candidates, ctx)
                    if chosen is not None:
                        return chosen.target
                return edge.target
            if edge.is_mechanical and edge.python_expression is not None:
                try:
                    if safe_eval(edge.python_expression, ctx.slots, _EVAL_BUILTINS):
                        return edge.target
                except Exception:
                    continue
            else:
                llm_candidates.append(edge)

        if llm_candidates:
            chosen = _llm_pick_condition(llm_client, llm_candidates, ctx)
            if chosen is not None:
                return chosen.target
        return None

    return resolve_edges


def _llm_pick_condition(
    llm_client: LLMClient,
    candidates: list[GraphEdge],
    ctx: LLMContext,
) -> GraphEdge | None:
    """Ask the model which (if any) of the non-mechanical route conditions applies.
    """
    numbered = "\n".join(f"{i}. {edge.condition_text}" for i, edge in enumerate(candidates))
    context_lines = "\n".join(ctx.goal + ctx.do)
    policy_block = f"House rules:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    prompt = (
        "Given the conversation state below, which of these numbered conditions "
        "is true right now? Reply with just the number, or NONE if none apply.\n\n"
        f"This decision's own instructions:\n{context_lines}\n\n"
        f"{ctx.block(numbered)}"
        f"{policy_block}"
        f"Conditions:\n{numbered}"
    )
    text = llm_client.complete(prompt)
    if text.isdigit() and int(text) < len(candidates):
        return candidates[int(text)]
    return None


# ---------------------------------------------------------------------------
# Node / router function factories
# ---------------------------------------------------------------------------


_ARG_BIND_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$")
_CONST_REF_RE = re.compile(r"^<([A-Z_][A-Z0-9_]*)>$")
_CONST_IN_TEXT_RE = re.compile(r"<([A-Z_][A-Z0-9_]*)>")
_SLOT_IN_TEXT_RE = re.compile(r"\[([a-z_][a-z0-9_]*)\]")


def _expand_constants(text: str, slots: dict[str, Any]) -> str:
    """
    A constant (`<A>`) or slot (`[a]`) written inside a quoted text is replaced by its value, like a bare `<A>`
    or `[a]` on the right-hand side already is; one that has no value stays as written.
    """

    def value_of(match: re.Match[str]) -> str:
        value = slots.get(match.group(1))
        return str(value) if value is not None else match.group(0)

    return _SLOT_IN_TEXT_RE.sub(value_of, _CONST_IN_TEXT_RE.sub(value_of, text))
_ATTR_ACCESS_RE = re.compile(r"^\[([a-zA-Z_][a-zA-Z0-9_]*)\]\.([a-zA-Z_][a-zA-Z0-9_]*)$")
_SEGMENT_SPLIT_RE = re.compile(r",\s*|\.(?=\s|$)")
_IN_UPPERCASE_RE = re.compile(r"^\[([a-zA-Z_][a-zA-Z0-9_]*)\]\s+in\s+uppercase\b", re.IGNORECASE)


def _uppercase_binding(rhs: str, slots: dict[str, Any]) -> tuple[bool, Any]:
    """
    `[slot] in uppercase ('EN', 'ES', or 'PT')`: the slot's value in capitals, a language name as its code.

    The segment splitter cuts that line at the commas inside the parenthesis, so the binding never
    resolved and a model filled it in: an English contact was booked with `language: "ES"`.
    """
    match = _IN_UPPERCASE_RE.match(rhs)
    value = slots.get(match.group(1)) if match else None
    if not isinstance(value, str) or not value.strip():
        return False, None
    code = _LANGUAGE_CODE_BY_NAME.get(value.strip().lower())
    return True, (code or value.strip()).upper()


def _extract_mechanical_arg_bindings(do_lines: list[str], slots: dict[str, Any]) -> dict[str, Any]:
    """Parse `DO` lines for `input_name = <value>` tool-argument hints.

    The bare-left-hand-side counterpart to `_apply_store_line`'s
    `[slot] = ...` grammar: `input_name` here is deliberately NOT
    bracketed (it names a tool input, not a memory slot). Real content
    often crams several of these into one line
    (`"contact_name = [c_name], contact_email = [c_email]."`), so each
    line is split into candidate segments; only segments whose right-hand
    side is a pure `[slot]` reference, a `[slot].field` attribute access,
    a `<CONSTANT>`, or a quoted literal resolve here — anything else (a
    described transformation or derivation) is left for the LLM fallback.

    Splits only on a comma, or a period followed by whitespace/end-of-line
    (2026-09-17, found live) — not on every period. The original
    `[.,]`-only split broke real content shaped `"event_id = [app].
    event_id"` (`AM_DO_CANCEL`/`AM_DO_RESCHED`, `[app]` a captured
    appointment *object*, not a scalar): it chopped the line into
    `"event_id = [app]"` and `"event_id"`, so the first segment
    mechanically bound `event_id` to the *entire* `[app]` dict instead of
    its `event_id` field — a wrong-shaped value silently reaching
    `cancel_appointment`/`edit_appointment`, the same "mechanical pass
    resolves confidently to the wrong thing" failure mode as the untyped
    `duration` bug, just via the line-splitting step instead of missing
    type coercion. A dot immediately followed by an identifier character
    (no space) is attribute access, part of the same segment; a dot
    followed by whitespace or the end of the line is a sentence/clause
    boundary, same as before.
    """
    bindings: dict[str, Any] = {}
    for line in do_lines:
        for segment in _SEGMENT_SPLIT_RE.split(line.strip()):
            segment = segment.strip()
            if not segment:
                continue
            match = _ARG_BIND_RE.search(segment)
            if not match:
                continue
            arg_name, rhs = match.group(1), match.group(2).strip()
            if rhs.endswith(")") and "(" not in rhs:
                rhs = rhs[:-1].rstrip()  # closing paren of "call tool (a=[x], b=[y])."
            resolved, value = _uppercase_binding(rhs, slots)
            if not resolved:
                resolved, value = _resolve_simple_rhs(rhs, slots)
            if resolved:
                bindings[arg_name] = value
    return bindings


def _arg_names_mentioned(do_lines: list[str]) -> set[str]:
    """Every argument name a `DO` line assigns to, whether or not the mechanical pass could resolve its right-hand side (2026-09-21).

    `_bind_tool_inputs` used to only send *required* fields to the LLM
    fallback — but a `DO` line can name a field the tool contract marks
    optional (`find_appointment`'s `contact_name`/`contact_email`, bound via
    `"contact_name = [name] ?? {{contact.name}}"`, a compound RHS the
    mechanical pass can't resolve). Optional-and-unresolved silently meant
    "never even try the LLM fallback" — the DSL author's explicit DO
    instruction for that field was just dropped. This only widens which
    fields get a chance at the LLM fallback; it never changes what a field
    the DO text never mentions does (still untouched, same as before).
    """
    names: set[str] = set()
    for line in do_lines:
        for segment in _SEGMENT_SPLIT_RE.split(line.strip()):
            match = _ARG_BIND_RE.search(segment.strip())
            if match:
                names.add(match.group(1))
    return names


def _resolve_simple_rhs(rhs: str, slots: dict[str, Any]) -> tuple[bool, Any]:
    slot_ref = _STORE_SLOT_REF_RE.match(rhs)
    if slot_ref:
        return True, slots.get(slot_ref.group(1))
    const_ref = _CONST_REF_RE.match(rhs)
    if const_ref:
        return True, slots.get(const_ref.group(1))
    quoted = _QUOTED_RE.match(rhs)
    if quoted:
        return True, _expand_constants(quoted.group(1) if quoted.group(1) is not None else quoted.group(2), slots)
    attr_access = _ATTR_ACCESS_RE.match(rhs)
    if attr_access:
        container = slots.get(attr_access.group(1))
        if isinstance(container, dict):
            return True, container.get(attr_access.group(2))
        return False, None
    return False, None


def _llm_bind_tool_inputs(
    llm_client: LLMClient,
    missing_fields: list[ToolContractField],
    ctx: LLMContext,
) -> dict[str, Any]:
    """One batched call deriving every still-missing required input's value.

    Never one call per argument. Reuses the same JSON-Schema-per-field
    shape `_capture_json_schema` builds for CAPTURE extraction, keyed by
    each field's own `type_expr` — the tool-contract typing work already
    done for real content pays for itself here.

    Also passes each field's own `description`/`examples` from the tool
    contract (2026-09-17, found missing while chasing a real reliability
    issue: `check_visa`'s `nationalities` field is documented as accepting
    "'USA', 'China, India', ['Spain', 'AFG']" — country names or ISO
    codes — but this function only ever fed the model the DO line's own
    wording and a bare JSON-Schema type, discarding that authored spec
    entirely. Without it, deriving a country form from a reported
    nationality (e.g. "venezolana" -> "VEN") sometimes just echoed the raw
    captured wording back — the DO line alone doesn't tell the model what
    the target format actually looks like, only that a conversion is
    wanted).

    `ctx.policies` (2026-09-18) is the artifact's `judgment_policies`
    (`data_and_variable_rules` — "tool results are the only source",
    "never invent availability", "don't mix service tools") — the one
    place this LLM call could otherwise derive a plausible-looking but
    fabricated argument value.
    """
    schema = {
        "type": "object",
        "properties": {f.name: _json_schema_type(f.type_expr or "str") for f in missing_fields},
        "required": [f.name for f in missing_fields],
        "additionalProperties": False,
    }
    specs = "\n".join(
        f"- {f.name}: {f.description}" + (f" Examples: {', '.join(f.examples)}." if f.examples else "")
        for f in missing_fields
    )
    policy_block = f"House rules for this tool call:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    prompt = (
        "You are filling in the arguments for a tool call in a conversational agent.\n\n"
        f"{ctx.block(specs)}"
        f"Instructions for this tool call (from the agent's DO field):\n{chr(10).join(ctx.do)}\n\n"
        f"What each requested argument actually expects (from the tool's own contract):\n{specs}\n\n"
        f"{policy_block}"
        "Determine the value for each requested argument, following the DO instructions above "
        "precisely and matching the format the argument's own contract describes — copy a field "
        "verbatim only where the instructions literally say to copy a slot as-is. If an "
        "instruction describes a derived, converted, or looked-up value (e.g. \"the country name "
        "or code for [nationality]\", \"in uppercase\"), you must actually perform that "
        "derivation — a slot's raw captured wording (e.g. a nationality adjective like "
        "\"Venezuelan\"/\"venezolana\", not the country name \"Venezuela\") is almost never "
        "already in the form the instruction asks for; returning it unchanged when a conversion "
        "was requested is wrong, not a safe default. Never invent a value the instructions don't "
        "support deriving; use null if genuinely unresolvable."
    )
    return llm_client.extract_structured(prompt, schema)


def _bind_tool_inputs(
    contract_inputs: list[ToolContractField],
    ctx: LLMContext,
    llm_client: LLMClient,
) -> dict[str, Any]:
    """Resolve every declared tool input's value for one tool call.

    Three passes, mechanical before LLM — see this module's docstring:
    (1) a slot already exists under the input's exact name, (2) the `DO`
    argument-binding grammar (`_extract_mechanical_arg_bindings`), and
    (3) one batched LLM call for whatever input is still missing after
    both mechanical passes and is either required, or optional but named
    by a `DO` line the mechanical pass couldn't fully resolve
    (`_arg_names_mentioned` — see its own docstring).

    Every resolved value is coerced against its own contract field's
    `type_expr` before returning (2026-09-17, found live — see
    `_coerce_value`'s docstring: a mechanically-bound value, unlike the
    LLM-fallback path, previously never had its type checked against
    anything at all, so a `str`-typed input silently reached the backend
    as whatever raw type its source slot happened to hold).

    `ctx.policies` only reaches the LLM fallback pass (3) — the mechanical
    passes (1)/(2) copy a named slot or a literal `DO` binding verbatim,
    nothing for a policy to guard against.
    """
    slots = ctx.slots
    input_names = {f.name for f in contract_inputs}
    bound: dict[str, Any] = {name: slots[name] for name in input_names if name in slots}

    mechanical = _extract_mechanical_arg_bindings(ctx.do, slots)
    for name, value in mechanical.items():
        if name in input_names and name not in bound:
            bound[name] = value

    # `history` is reserved: a tool that declares it receives the recent conversation as the runtime
    # holds it, never a value a DO line or the model has to produce.
    if "history" in input_names and "history" not in bound and ctx.history:
        bound["history"] = "\n".join(ctx.history)

    mentioned = _arg_names_mentioned(ctx.do)
    optional_mentioned = {f.name for f in contract_inputs if not f.required and f.name in mentioned}
    missing_fields = [
        f for f in contract_inputs if f.name not in bound and (f.required or f.name in mentioned)
    ]
    if missing_fields:
        llm_bound = _llm_bind_tool_inputs(llm_client, missing_fields, ctx)
        # An optional field the LLM couldn't resolve comes back as an explicit
        # `None` (the schema requires *a* value, even if it's null) — dropped
        # here rather than sent on, so it's omitted from the call exactly like
        # before this field ever reached the LLM fallback (the contract's own
        # default, not a `null` the backend's plain `str` schema may reject).
        # A `None` for a *required* field is left as-is: that call was already
        # going to fail without a real value, same as before this change.
        for name, value in llm_bound.items():
            if value is None and name in optional_mentioned:
                continue
            bound[name] = value

    type_by_name = {f.name: f.type_expr for f in contract_inputs if f.type_expr}
    return {
        name: _coerce_value(value, type_by_name[name]) if name in type_by_name else value
        for name, value in bound.items()
    }


def _missing_required_inputs(contract_inputs: list[ToolContractField], inputs: dict[str, Any]) -> list[str]:
    """Names of the required tool inputs that have no value (absent or null) in `inputs`."""
    return [f.name for f in contract_inputs if f.required and inputs.get(f.name) is None]


def _resolve_target(
    node: GraphNode,
    ctx: LLMContext,
    node_by_id: dict[str, GraphNode],
    resolve_edges: Callable[[list[GraphEdge], LLMContext], str | None],
) -> str:
    """Resolve `node`'s next node id from ROUTE/FALLBACK, defaulting to `END`.

    Shared by `_make_router_fn` (for every non-question node, dispatched via
    `add_conditional_edges`) and `question` nodes' own `node_fn` (dispatched
    via a `Command(goto=...)` instead — see this module's docstring on why
    a question node must never also have `add_conditional_edges`
    registered: LangGraph does not suppress those when a node returns a
    `Command`, so both would fire and collide on the same state channel).

    `ctx` must already be built from `node`'s own `goal`/`do` — callers pass
    the same `LLMContext` they used for this node's other decisions.
    """
    target = resolve_edges(node.route, ctx)
    if target is None:
        target = resolve_edges(node.fallback, ctx)
    if target is None:
        return END

    if is_dynamic_target(target):
        slot_name = dynamic_target_slot_name(target)
        target = ctx.slots.get(slot_name) or END

    if target not in node_by_id:
        return END
    return target


def _make_node_fn(
    node: GraphNode,
    llm_client: LLMClient,
    router: GlobalRouterDefinition,
    node_by_id: dict[str, GraphNode],
    render_say: Callable[[str, list[str], bool, str | None, dict[str, Any], list[str] | None], str],
    resolve_edges: Callable[[list[GraphEdge], LLMContext], str | None],
    tool_executors: dict[str, Callable[..., dict[str, Any]]],
    tool_input_fields: dict[str, list[ToolContractField]],
    say_callback: Callable[[str], None],
    say_policies: list[str] | None = None,
    judgment_policies: list[str] | None = None,
):
    """Build one LangGraph node function for `node`.

    `say_policies`/`judgment_policies` (2026-09-18) are the artifact's two
    pre-filtered policy line lists (`targets/langgraph/runtime_artifact.py`),
    split by call *purpose*, not node type: `say_policies` reaches every
    `render_say` call this node makes (it takes its own explicit `policies`
    argument, since it has no `ctx`); `judgment_policies` is set once, as
    `policies=` on every `LLMContext` this function builds, so it reaches
    `_llm_extract_capture`, `_apply_conditional_mutations`,
    `_llm_compute_store_value`, `_llm_pick_condition` (via `resolve_edges`),
    and `_llm_bind_tool_inputs` automatically — none of those five take a
    `policies` parameter of their own; they read `ctx.policies`.
    """
    def node_fn(state: SessionState) -> Any:
        slots = dict(state["slots"])
        last_user_message = state.get("last_user_message", "")
        language_code = slots.get("preferred_language")
        history = list(state.get("history", []))
        contact = state.get("contact") or {}

        # Ensure [current_state] is available in slots for DSL references
        # (2026-10-20). Tracks the "last stable waiting point" — only updated
        # on question nodes, so registration/message nodes (e.g. a language-
        # switching subflow) can capture the interrupted question's ID as a
        # resume target instead of capturing their own ID and looping.
        if node.node_type == "question":
            slots["current_state"] = node.node_id

        # One `LLMContext` per decision point (2026-09-17) — rebuilt whenever
        # `history`/`last_user_message` change below (the interrupt loop
        # replaces both), never reused stale. `slots` is never reassigned in
        # this function (only mutated in place), so every ctx built from it
        # always sees the latest values without needing a fresh copy.
        ctx = LLMContext(
            slots=slots,
            history=history,
            last_user_message=last_user_message,
            goal=node.goal,
            do=node.do,
            policies=judgment_policies or [],
            contact=contact,
        )

        # `DO` mutations (retry-counter increments, `[x] = NULL` resets —
        # see NUMERIC_AND_RETRY_COUNTER_SEMANTICS) are applied for every
        # node type, mirroring `STORE` on `registration` nodes below.
        # `DO` was previously only fed to the LLM as route-decision
        # context and never actually mutated `slots`, so every retry
        # counter silently never incremented — see DESIGN_PATTERNS.md.
        # A `DO` line identical to a `STORE` line (common on
        # `registration` nodes, which duplicate the same assignment in
        # both fields) is skipped here to avoid double-applying it.
        store_lines = set(node.store)
        do_lines = [line for line in node.do if line not in store_lines]
        for line in do_lines:
            _apply_store_line(line, ctx, llm_client)
        # `action` nodes' DO lines are entirely owned by `_bind_tool_inputs`
        # below (tool-argument hints like "input_name = [slot]" are not slot
        # mutations) — the conditional-prose fallback only applies elsewhere,
        # or it would double-handle the same lines and fire an extra LLM call
        # on every single tool call.
        #
        # `eval: "llm"` nodes, any node type (2026-09-17, found live — see
        # `_is_comparison_only_line`'s docstring for the first, narrower
        # attempt at this same bug): a `SC_DEC_S`-shaped node's `do:` line
        # ("Map [slot] to the exact object in [available_slots]. It is
        # valid only if that object has start_co and end_co.") isn't a
        # `compare`/`validate`/... verb, so the earlier verb-list guard let
        # it through — the model "applied" it, nulling out `available_slots`
        # (a list of real appointment objects) and silently derailing the
        # booking into objections. A verb blacklist can never be complete;
        # checking every real `eval: "llm"` node's `do:` lines in this
        # agent instead confirms the actual structural rule: on any node
        # whose route is `eval: "llm"` — `decision` nodes (`SC_DEC_S`,
        # `SC_DEC_D`, ...), but also real content's `registration`
        # (`AM_INIT`) and `question` (`AM_ASK_NAME`) nodes, since `eval` is
        # a route-evaluation property of any node type, not decision-only —
        # `do:` lines exist exclusively to ground `_llm_pick_condition`'s
        # route judgment (`resolve_edges` already receives them via
        # `ctx.do`); every real occurrence across this agent is validation
        # prose ("Evaluate whether...", "Compare...", "Map...", "Treat..."),
        # never a mutation instruction. A genuine conditional mutation
        # (e.g. `OP_DEC`'s "If [svc] is still NULL, infer it...") only ever
        # appears on an `eval: "code"` node, which has no route-judgment use
        # for `do:` at all — that's the only place this pass is needed.
        if node.node_type != "action" and node.eval != "llm":
            _apply_conditional_mutations(do_lines, ctx, llm_client)

        if node.node_type in ("message", "terminal") and node.say:
            rendered_message = render_say(
                node.node_id, node.say, node.say_verbatim, language_code, slots, say_policies,
                contact=contact,
            )
            say_callback(rendered_message)
            history = _append_history(history, f"agent: {rendered_message}")

        elif node.node_type == "question":
            # Don't call say_callback here: interrupt() re-runs this function
            # from the top on every resume, so a call before it would repeat
            # on every turn. The caller reads the prompt from the interrupt
            # payload instead, exactly once.
            rendered_say = render_say(
                node.node_id, node.say, node.say_verbatim, language_code, slots, say_policies,
                contact=contact,
            )

            # Global router: every reply is checked against every handler
            # trigger / FAQ match phrase BEFORE it's treated as the answer
            # to this question (DESIGN_PATTERNS.md P04). A match either
            # re-asks the same pending question (the common "resume where
            # you were" case) or jumps straight to a different state via
            # Command(goto=...) when the matched handler's own routing
            # resolves somewhere else.
            def _on_router_say(n: GraphNode | FaqNode, say: list[str]) -> None:
                nonlocal history
                rendered = render_say(
                    n.node_id if hasattr(n, "node_id") else n.faq_id,
                    say,
                    n.say_verbatim,
                    language_code,
                    slots,
                    say_policies,
                    contact=contact,
                )
                say_callback(rendered)
                history = _append_history(history, f"agent: {rendered}")

            active_router = router_for_state(router, node.node_id)
            while True:
                reply = interrupt({"prompt": [rendered_say]})
                history = _append_history(history, f"agent: {rendered_say}")
                history = _append_history(history, f"user: {reply}")
                router_ctx = LLMContext(
                    slots=slots,
                    history=history,
                    last_user_message=reply,
                    pending_question=rendered_say,
                    policies=judgment_policies or [],
                    contact=contact,
                )
                previous_language = _language_name_from_slots(slots)
                match = match_global_router(llm_client, active_router, router_ctx)
                _sync_language_change(previous_language, slots, contact, tool_executors)
                side_question = match is None and has_unanswered_side_question(llm_client, router_ctx)
                if match is None and (side_question or _looks_like_question(reply)):
                    # The first pass can take a question for a plain answer ("how long does it take?"
                    # to a yes/no question), so a reply that asks something still gets matched against
                    # the specific FAQs and handlers before the generic advisor fallback.
                    match = match_side_question(
                        llm_client, active_router, router_ctx, frozenset({*_SIDE_QUESTION_FALLBACK_IDS, _LANGUAGE_CHANGE_HANDLER_ID})
                    )
                if side_question and match is None:
                    advisor_handler = next(
                        (
                            h
                            for fallback_id in _SIDE_QUESTION_FALLBACK_IDS
                            for h in active_router.handlers
                            if h.node_id == fallback_id
                        ),
                        None,
                    )
                    if advisor_handler is not None:
                        match = ("handler", advisor_handler)
                if match is None:
                    last_user_message = reply
                    if side_question:
                        ack = render_say(
                            f"{node.node_id}__side_question_ack",
                            UNANSWERED_QUESTION_ACK,
                            False,
                            language_code,
                            slots,
                            say_policies,
                            contact=contact,
                        )
                        say_callback(ack)
                        history = _append_history(history, f"agent: {ack}")
                    break
                if match[0] == "handler" and match[1].node_id == "H_LANG_ASK":
                    # Ambiguous "I don't speak X": ask once in all three languages and wait
                    # for the answer instead of re-asking the pending question.
                    rendered_say = "\n".join(match[1].say)
                    continue
                goto_target = handle_global_router_match(
                    match,
                    router_ctx,
                    resolve_edges=resolve_edges,
                    on_say=_on_router_say,
                )
                if goto_target is not None and goto_target in node_by_id:
                    return Command(
                        update={
                            "slots": slots,
                            "current_state": goto_target,
                            "last_user_message": reply,
                            "history": history,
                        },
                        goto=goto_target,
                    )
                # else: resume where we were. The node is entered again instead of looping on a second
                # interrupt() here: every resume re-executes the node from the top, so with a loop the
                # answer just given (an FAQ, say) was replayed and sent a second time with the next reply.
                return Command(
                    update={
                        "slots": slots,
                        "current_state": node.node_id,
                        "last_user_message": reply,
                        "history": history,
                    },
                    goto=node.node_id,
                )

            ctx = LLMContext(
                slots=slots,
                history=history,
                last_user_message=last_user_message,
                goal=node.goal,
                do=node.do,
                pending_question=rendered_say,
                policies=judgment_policies or [],
                contact=contact,
            )
            corrected_email_slot = _correct_contact_email(slots, node.capture, last_user_message)
            if node.capture:
                extracted = _llm_extract_capture(llm_client, node.capture, ctx)
                for slot_name, type_expr in node.capture:
                    if slot_name in extracted:
                        slots[slot_name] = _coerce_value(extracted[slot_name], type_expr)
                if corrected_email_slot and not any(extracted.get(name) not in (None, "") for name, _ in node.capture):
                    # Only the email was sent: say it was updated and ask the same question again.
                    ack = render_say(
                        f"{node.node_id}__email_ack",
                        [_EMAIL_UPDATED_ACK.format(slot=corrected_email_slot)],
                        False,
                        language_code,
                        slots,
                        say_policies,
                        contact=contact,
                    )
                    say_callback(ack)
                    history = _append_history(history, f"agent: {ack}")
                    return Command(
                        update={
                            "slots": slots,
                            "current_state": node.node_id,
                            "last_user_message": last_user_message,
                            "history": history,
                        },
                        goto=node.node_id,
                    )

            # A question node must ALWAYS route via a returned Command, never
            # a plain dict — see _resolve_target's docstring: LangGraph does
            # not suppress add_conditional_edges just because a node returns
            # a Command, so registering both causes a concurrent-write error
            # the moment a global-router match resolves to a concrete jump
            # target. Question nodes therefore never get add_conditional_edges
            # registered (see build_graph) and always resolve their own
            # target here instead.
            target = _resolve_target(node, ctx, node_by_id, resolve_edges)
            return Command(
                update={
                    "slots": slots,
                    "current_state": node.node_id,
                    "last_user_message": last_user_message,
                    "history": history,
                },
                goto=target,
            )

        elif node.node_type == "action" and node.execute:
            executor = tool_executors.get(node.execute)
            if executor is not None:
                input_fields = tool_input_fields.get(node.execute, [])
                inputs = _bind_tool_inputs(input_fields, ctx, llm_client)
                missing = _missing_required_inputs(input_fields, inputs)
                try:
                    if missing:
                        # The backend would reject the call (HTTP 422 on a null); the flow's own routes
                        # handle the empty result, like a tool that failed.
                        logger.warning("tool %s skipped in %s: missing %s", node.execute, node.node_id, missing)
                        result = {}
                    else:
                        result = executor(**inputs)
                except ToolExecutionError:
                    # A tool that captures nothing (a CRM sync, say) has no result to route on:
                    # its failure must not end the conversation, so the flow just moves on.
                    if node.capture:
                        raise
                    logger.warning("tool %s failed in %s; continuing", node.execute, node.node_id, exc_info=True)
                    result = {}
                for slot_name, _type_expr in node.capture:
                    if slot_name in result:
                        slots[slot_name] = result[slot_name]
                    else:
                        # The namespaced slot (`q__eligibility_result`) matches by suffix; the longest key wins so
                        # `eligibility_result` is never taken for `result`.
                        key = max((k for k in result if slot_name.endswith(k)), key=len, default=None)
                        if key is not None:
                            slots[slot_name] = result[key]
                for line in node.store:
                    _apply_store_line(line, ctx, llm_client)

        elif node.node_type == "registration":
            for line in node.store:
                _apply_store_line(line, ctx, llm_client)
            _apply_conditional_mutations(node.store, ctx, llm_client)

        return {
            "slots": slots,
            "current_state": node.node_id,
            "last_user_message": last_user_message,
            "history": history,
        }

    return node_fn


def _make_router_fn(
    node: GraphNode,
    node_by_id: dict[str, GraphNode],
    resolve_edges: Callable[[list[GraphEdge], LLMContext], str | None],
    judgment_policies: list[str] | None = None,
):
    def router_fn(state: SessionState) -> str:
        ctx = LLMContext(
            slots=state["slots"],
            history=list(state.get("history", [])),
            last_user_message=state.get("last_user_message", ""),
            goal=node.goal,
            do=node.do,
            policies=judgment_policies or [],
            contact=state.get("contact") or {},
        )
        return _resolve_target(node, ctx, node_by_id, resolve_edges)

    return router_fn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_graph(
    artifact: RuntimeArtifact,
    llm_client: LLMClient,
    *,
    tools_base_url: str = "http://localhost/tools",
    tool_http_client: Any = None,
    say_callback: Callable[[str], None] = print,
    checkpointer: BaseCheckpointSaver | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> Any:
    """Build and compile a real `langgraph.graph.StateGraph` for `artifact`.

    Args:
        artifact: The compiled graph bundle — from
            `targets.langgraph.runtime_artifact.render_runtime_artifact(spec)`
            at compile time, or `runtime_artifact_from_dict(json.load(f))`
            when loaded from a `.json` file a backend swapped in.
        llm_client: Isolates every model call this graph makes.
        tools_base_url: Base URL every `action` node's tool executor
            POSTs to (`{tools_base_url}/{tool_name}`).
        tool_http_client: Optional `httpx.Client` shared by every generated
            tool executor — inject a client with a `httpx.MockTransport`
            in tests to avoid real network calls.
        say_callback: Called with the rendered text of every `message` and
            `terminal` node's `SAY` block (and every matched global-router
            handler/FAQ's `SAY`). Defaults to `print`; inject a list-append
            callback in tests instead.
        knowledge_base: Answers the agent's `kb_answer` tool
            (see `knowledge_base.py`). Without one the tool is called over HTTP like any other.
        checkpointer: Where session state
            (`[current_state]`, captured slots, ...) is persisted between
            turns. Defaults to `InMemorySaver()` — state is lost on process
            restart, fine for tests and local exploration. A real deployment
            serving live traffic across process restarts (or multiple
            workers) must inject a real one (e.g.
            `langgraph.checkpoint.sqlite.SqliteSaver`,
            `langgraph.checkpoint.postgres.PostgresSaver`) — this function
            never decides that policy itself.

    Returns:
        A compiled LangGraph graph, checkpointed per `checkpointer` above.
    """
    agent_graph = artifact.graph
    node_by_id = {n.node_id: n for n in agent_graph.nodes}
    router = artifact.global_router

    render_say = _make_render_say(llm_client)
    resolve_edges = _make_resolve_edges(llm_client)

    contracts = {c.name: c for c in artifact.tool_contracts}
    tool_executors = {
        name: make_tool_executor(contract, tools_base_url, client=tool_http_client)
        for name, contract in contracts.items()
    }
    tool_input_fields = {name: contract.inputs for name, contract in contracts.items()}
    if knowledge_base is not None and KNOWLEDGE_TOOL_NAME in contracts:
        # The agent's own knowledge answers its `kb_answer` tool in-process: no endpoint to call.
        tool_executors[KNOWLEDGE_TOOL_NAME] = make_knowledge_tool_executor(llm_client, knowledge_base)

    builder = StateGraph(SessionState)
    for node in agent_graph.nodes:
        builder.add_node(
            node.node_id,
            _make_node_fn(
                node, llm_client, router, node_by_id, render_say, resolve_edges,
                tool_executors, tool_input_fields, say_callback,
                say_policies=artifact.say_policies, judgment_policies=artifact.judgment_policies,
            ),
        )
    builder.set_entry_point(agent_graph.entry_point)

    for node in agent_graph.nodes:
        if node.node_type == "terminal":
            builder.add_edge(node.node_id, END)
            continue
        if node.node_type == "question":
            # No add_conditional_edges here — the question node's own
            # node_fn always returns a Command(goto=...) that fully
            # determines routing (see _make_node_fn / _resolve_target).
            continue
        builder.add_conditional_edges(
            node.node_id,
            _make_router_fn(node, node_by_id, resolve_edges, judgment_policies=artifact.judgment_policies),
        )

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def initial_slots(artifact: RuntimeArtifact) -> dict[str, Any]:
    """Seed constants (e.g.

    `MAX_RETRY_ATTEMPTS`) and the [current_state] slot.

    Without this, every retry-limit check referencing a constant would
    raise `NameError` inside `_resolve_edges`'s `eval()` and silently never
    match. [current_state] (2026-10-20) is seeded as an empty string so
    registration nodes can reference it (e.g. `[resume_state] = [current_state]`)
    even before the first question is reached.
    """
    slots = {name: _coerce_constant(value) for name, value in artifact.constants.items()}
    slots["current_state"] = ""
    return slots


def fresh_state(
    artifact: RuntimeArtifact,
    contact: dict[str, Any] | None = None,
    seed_history: list[str] | None = None,
    seed_last_user_message: str | None = None,
) -> SessionState:
    """Build the initial `SessionState` for a brand-new conversation.

    `contact` (2026-09-21) is the session's known CRM contact fields (e.g.
    `{"name": ..., "email": ..., "phone": ..., "language": ...}`), matching
    whatever `input_variables.yaml` declares under `contact.*` for this
    agent. Optional and defaults to `{}` — an agent whose DO/ROUTE/SAY text
    never references `{{contact.X}}` is unaffected either way; one that
    does simply sees every such reference as unresolved/unknown until a
    caller supplies real values here.

    `seed_history`/`seed_last_user_message` (2026-09-25) let a caller give
    the very first node some context before anything has actually happened
    in the conversation -- the gap that broke `eval: "llm"` gates shaped
    like an outbound-call agent's "was the call answered?" decision: on a
    genuinely fresh state `history` is `[]`, so `_llm_pick_condition` has
    zero evidence and reliably answers `NONE`, taking the "not answered"
    fallback before the agent ever gets to speak. Both default to the old
    empty values, so every existing caller is unaffected. Neither is
    interpreted here -- a caller decides what "the call connected" or "the
    user already said X" looks like as plain history lines (e.g.
    `f"user: {text}"`), since that phrasing is a harness/UI concern, not
    part of the compiled agent.
    """
    from agent_runtime.runtime.session_resolver import now_iso

    return {
        "slots": initial_slots(artifact),
        "current_state": "",
        "last_user_message": seed_last_user_message or "",
        "last_message_at": now_iso(),
        "history": list(seed_history) if seed_history else [],
        "contact": contact or {},
    }
