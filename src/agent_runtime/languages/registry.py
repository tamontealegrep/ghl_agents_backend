"""The languages a text agent can speak: one data file per language, found by the registry.

Everything that depends on a language (day and month names, date layouts, fixed messages, the phrases the
router listens for, the words a contact uses to pick a day or a time of day) lives in one YAML file in
`data/`, named after the language code. Nothing else in the code names a language, so:

* adding a language is adding `data/<code>.yaml` (`scripts/add_language.py` drafts it with a model);
* removing one is deleting its file, or leaving it out of `GLOBAL_ROUTER_LANGUAGES`;
* `tests/runtime/test_languages.py` checks every file, present and future, with no change.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).with_name("data")

LANGUAGES_ENV = "GLOBAL_ROUTER_LANGUAGES"
"""The languages a conversation may switch to, by name or code, comma separated (`English, Spanish, French`).
Empty or missing means the languages whose file says `default_enabled: true`."""

FALLBACK_CODE = "en"
"""The language used when a value names none the registry knows."""

PART_KEYS = ("early_morning", "morning", "afternoon", "night")
"""The four parts of the day, in order, as written in `calendar.parts_of_day` and `scheduling.part_words`."""

ORDINAL_KEYS = (
    ("last", -1),
    ("second_to_last", -2),
    ("first", 0),
    ("second", 1),
    ("third", 2),
    ("fourth", 3),
    ("fifth", 4),
)
"""The positions among a list of offered times a contact can name, as `(file key, index)`; -1 is the last."""

_FORMAT_KEYS = ("date", "day_label", "weekday_date", "full_date", "day_title")
_MESSAGE_KEYS = ("closing", "unsupported_media", "menu_offer", "menu_or")


def fold(text: Any) -> str:
    """Accent- and case-insensitive comparison key."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").casefold().strip()


def _words_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    """One regex that matches any of `words` (already folded) as whole words; never matches when empty."""
    if not words:
        return re.compile(r"(?!x)x")
    alternatives = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternatives})\b")


@dataclass(frozen=True, eq=False)
class Language:
    """One language, as read from its data file (see `data/en.yaml` for each field). Compared by identity: one per file."""

    code: str
    name: str
    native_name: str
    aliases: tuple[str, ...]
    default_enabled: bool
    weekdays: tuple[str, ...]
    months: tuple[str, ...]
    month_abbreviations: tuple[str, ...]
    parts_of_day: tuple[str, ...]
    range_word: str
    clock: int
    formats: dict[str, str]
    messages: dict[str, str]
    explicit_phrases: tuple[str, ...]
    inability_phrases: tuple[str, ...]
    inability_identifies_language: bool
    content_words: tuple[str, ...]
    topic_words: tuple[str, ...]
    bare_reply_words: tuple[str, ...]
    today: tuple[str, ...]
    tomorrow: tuple[str, ...]
    day_after_tomorrow: tuple[str, ...]
    part_words: dict[str, tuple[str, ...]]
    ordinals: dict[str, tuple[str, ...]]

    # ---- dates

    def _fields(self, date: datetime.date) -> dict[str, str]:
        return {
            "weekday": self.weekdays[date.weekday()],
            "day": str(date.day),
            "month": self.months[date.month - 1],
            "month_abbr": self.month_abbreviations[date.month - 1],
            "year": str(date.year),
        }

    def format_date(self, date: datetime.date) -> str:
        """'8 de abril de 2026' / 'April 8, 2026'."""
        return self.formats["date"].format(**self._fields(date))

    def day_label(self, date: datetime.date) -> str:
        """Weekday, day and month, no year: 'martes 8 de abril' / 'Tuesday, April 8'."""
        return self.formats["day_label"].format(**self._fields(date))

    def weekday_date(self, date: datetime.date) -> str:
        """Weekday and full date in a list: 'martes 8 de abril de 2026' / 'Tuesday, April 8, 2026'."""
        return self.formats["weekday_date"].format(date=self.format_date(date), **self._fields(date))

    def full_date(self, date: datetime.date) -> str:
        """The date in the e-mails: 'martes, 8 de abril de 2026' / 'Tuesday, April 8, 2026'."""
        return self.formats["full_date"].format(date=self.format_date(date), **self._fields(date))

    def day_title(self, date: datetime.date) -> str:
        """The short heading of a list of times: 'Miércoles. 4 nov' / 'Wednesday. Nov 4'."""
        fields = self._fields(date)
        fields["weekday"] = fields["weekday"][:1].upper() + fields["weekday"][1:]
        return self.formats["day_title"].format(**fields)

    def format_time(self, hour: int, minute: int) -> str:
        """'03:30 pm' on a 12-hour clock, '15:30' on a 24-hour one."""
        if self.clock == 12:
            return f"{hour % 12 or 12:02d}:{minute:02d} {'am' if hour < 12 else 'pm'}"
        return f"{hour:02d}:{minute:02d}"

    # ---- matching

    @property
    def all_names(self) -> tuple[str, ...]:
        """Every way this language is written in a value: code, name, native name and aliases."""
        return (self.code, self.name, self.native_name, *self.aliases)

    @property
    def exact_names(self) -> frozenset[str]:
        """A message that is only the language's name asks for that language ('english', 'francais')."""
        return frozenset({fold(self.name), fold(self.native_name)})

    @property
    def message_names(self) -> tuple[str, ...]:
        """How a model may write this language in a reply (not the code: 'EN' is too short to search for)."""
        return tuple(dict.fromkeys(fold(n).upper() for n in (self.name, self.native_name, *self.aliases) if len(n) > 3))


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(value.split())
    return tuple(str(v) for v in value)


def _require(data: dict[str, Any], path: str, source: Path, prefix: str = "") -> Any:
    node: Any = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"{source.name}: missing '{prefix}{path}'")
        node = node[key]
    return node


def _build(source: Path) -> Language:
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    code = str(_require(data, "code", source)).strip().lower()
    if code != source.stem:
        raise ValueError(f"{source.name}: code '{code}' must match the file name")
    calendar = _require(data, "calendar", source)
    weekdays = _as_tuple(_require(calendar, "weekdays", source, "calendar."))
    months = _as_tuple(_require(calendar, "months", source, "calendar."))
    abbreviations = _as_tuple(_require(calendar, "month_abbreviations", source, "calendar."))
    parts = tuple(str(p) for p in _require(calendar, "parts_of_day", source, "calendar."))
    if (len(weekdays), len(months), len(abbreviations), len(parts)) != (7, 12, 12, 4):
        raise ValueError(f"{source.name}: calendar needs 7 weekdays, 12 months, 12 abbreviations and 4 parts of day")
    formats = {key: str(_require(calendar, f"formats.{key}", source, "calendar.")) for key in _FORMAT_KEYS}
    messages = {key: str(_require(data, f"messages.{key}", source)).strip() for key in _MESSAGE_KEYS}
    if "{languages}" not in messages["menu_offer"]:
        raise ValueError(f"{source.name}: messages.menu_offer needs the {{languages}} placeholder")
    clock = int(_require(calendar, "clock", source, "calendar."))
    if clock not in (12, 24):
        raise ValueError(f"{source.name}: calendar.clock must be 12 or 24")
    router = _require(data, "router", source)
    scheduling = _require(data, "scheduling", source)
    part_words = {key: tuple(fold(w) for w in _as_tuple(_require(scheduling, f"part_words.{key}", source, "scheduling."))) for key in PART_KEYS}
    ordinals = {key: tuple(fold(w) for w in _as_tuple((scheduling.get("ordinals") or {}).get(key))) for key, _ in ORDINAL_KEYS}
    language = Language(
        code=code,
        name=str(_require(data, "name", source)),
        native_name=str(_require(data, "native_name", source)),
        aliases=_as_tuple(data.get("aliases")),
        default_enabled=bool(data.get("default_enabled", False)),
        weekdays=weekdays,
        months=months,
        month_abbreviations=abbreviations,
        parts_of_day=parts,
        range_word=str(_require(calendar, "range_word", source, "calendar.")),
        clock=clock,
        formats=formats,
        messages=messages,
        explicit_phrases=tuple(fold(p) for p in _as_tuple(router.get("explicit_phrases"))),
        inability_phrases=tuple(fold(p) for p in _as_tuple(router.get("inability_phrases"))),
        inability_identifies_language=bool(router.get("inability_identifies_language", True)),
        content_words=tuple(fold(w) for w in _as_tuple(router.get("content_words"))),
        topic_words=tuple(fold(w) for w in _as_tuple(router.get("topic_words"))),
        bare_reply_words=tuple(fold(w) for w in _as_tuple(router.get("bare_reply_words"))),
        today=tuple(fold(w) for w in _as_tuple(scheduling.get("today"))),
        tomorrow=tuple(fold(w) for w in _as_tuple(scheduling.get("tomorrow"))),
        day_after_tomorrow=tuple(fold(w) for w in _as_tuple(scheduling.get("day_after_tomorrow"))),
        part_words=part_words,
        ordinals=ordinals,
    )
    try:  # a format with an unknown placeholder must fail here, not in a conversation
        sample = datetime.date(2026, 11, 4)
        language.format_date(sample), language.day_label(sample), language.weekday_date(sample)
        language.full_date(sample), language.day_title(sample)
        language.messages["menu_offer"].format(languages="x")
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(f"{source.name}: a calendar format or message uses an unknown placeholder ({error})") from error
    return language


@lru_cache(maxsize=1)
def available_languages() -> tuple[Language, ...]:
    """Every language that has a data file, by code."""
    return tuple(_build(path) for path in sorted(DATA_DIR.glob("*.yaml")))


@lru_cache(maxsize=1)
def _index() -> dict[str, Language]:
    index: dict[str, Language] = {}
    for language in available_languages():
        for name in language.all_names:
            index.setdefault(fold(name), language)
    return index


def get(value: Any) -> Language | None:
    """The language a code, name, alias or locale ('es_CO', 'Português (Brasil)') stands for, or None."""
    text = fold(value)
    if not text:
        return None
    found = _index().get(text)
    if found is not None:
        return found
    return _index().get(re.split(r"[^a-z0-9]", text)[0])


def resolve(value: Any, default: str = FALLBACK_CODE) -> Language:
    """Like `get`, falling back to the language with code `default` (English when that is not available)."""
    return get(value) or get(default) or get(FALLBACK_CODE) or available_languages()[0]


def enabled_languages() -> tuple[Language, ...]:
    """The languages a conversation may switch to, in the order `GLOBAL_ROUTER_LANGUAGES` lists them."""
    chosen: list[Language] = []
    for item in re.split(r"[,;|]", os.environ.get(LANGUAGES_ENV, "")):
        if not item.strip():
            continue
        language = get(item)
        if language is None:
            logger.warning("%s names '%s', which has no file in %s: ignored", LANGUAGES_ENV, item.strip(), DATA_DIR)
        elif language not in chosen:
            chosen.append(language)
    return tuple(chosen) or tuple(lang for lang in available_languages() if lang.default_enabled)


def is_enabled(language: Language) -> bool:
    """True when conversations may switch to `language`."""
    return language in enabled_languages()


# ---- what the runtime reads across languages (every contact may write in any of them)


@lru_cache(maxsize=1)
def bare_reply_words() -> frozenset[str]:
    """The words of a reply that is only a yes, a no or an acknowledgement, in every language."""
    return frozenset(word for lang in available_languages() for word in lang.bare_reply_words)


@lru_cache(maxsize=1)
def topic_words() -> tuple[str, ...]:
    """Words of the agent's subject (surrogacy, IVF...) that show a message answers a question, in every language."""
    return tuple(dict.fromkeys(word for lang in available_languages() for word in lang.topic_words))


@lru_cache(maxsize=1)
def month_by_word() -> dict[str, int]:
    """Month number by accent-folded month name or its first three letters, in every language."""
    by_word = {fold(name): i + 1 for lang in available_languages() for i, name in enumerate(lang.months)}
    by_word.update({word[:3]: number for word, number in list(by_word.items())})
    return by_word


@lru_cache(maxsize=1)
def weekday_by_word() -> dict[str, int]:
    """Weekday (Monday is 0) by accent-folded weekday name, or its first part ('segunda' for 'segunda-feira')."""
    by_word: dict[str, int] = {}
    for lang in available_languages():
        for index, name in enumerate(lang.weekdays):
            folded = fold(name)
            by_word.setdefault(folded, index)
            by_word.setdefault(re.split(r"[-\s]", folded)[0], index)
    return by_word


@lru_cache(maxsize=1)
def today_pattern() -> re.Pattern[str]:
    """A regex for 'today', in every language."""
    return _words_pattern(tuple(w for lang in available_languages() for w in lang.today))


@lru_cache(maxsize=1)
def tomorrow_pattern() -> re.Pattern[str]:
    """A regex for 'tomorrow', in every language."""
    return _words_pattern(tuple(w for lang in available_languages() for w in lang.tomorrow))


@lru_cache(maxsize=1)
def day_after_tomorrow_pattern() -> re.Pattern[str]:
    """A regex for 'the day after tomorrow', in every language."""
    return _words_pattern(tuple(w for lang in available_languages() for w in lang.day_after_tomorrow))


@lru_cache(maxsize=1)
def part_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """`(part key, regex)` for each part of the day a contact can name, in every language."""
    return tuple(
        (key, _words_pattern(tuple(w for lang in available_languages() for w in lang.part_words[key]))) for key in PART_KEYS
    )


@lru_cache(maxsize=1)
def ordinal_patterns() -> tuple[tuple[int, re.Pattern[str]], ...]:
    """`(index, regex)` for each position a contact can name among the offered times, in every language."""
    return tuple(
        (index, _words_pattern(tuple(w for lang in available_languages() for w in lang.ordinals[key])))
        for key, index in ORDINAL_KEYS
    )


@lru_cache(maxsize=1)
def part_headings() -> frozenset[str]:
    """The capitalized name of every part of the day, in every language (the headings of a list of times)."""
    return frozenset(name.capitalize() for lang in available_languages() for name in lang.parts_of_day)


def reload() -> None:
    """Forget what was read, so changed files or environment are picked up (tests and `add_language.py`)."""
    for cached in (available_languages, _index, bare_reply_words, topic_words, month_by_word, weekday_by_word, today_pattern,
                   tomorrow_pattern, day_after_tomorrow_pattern, part_patterns, ordinal_patterns, part_headings):
        cached.cache_clear()
