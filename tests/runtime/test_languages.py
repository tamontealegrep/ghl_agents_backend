"""The language registry: every data file is valid, and a language is added or removed by its file alone."""

from __future__ import annotations

import datetime
import shutil

import pytest

from agent_runtime import languages
from agent_runtime.languages import registry

LANGUAGE_CODES = [language.code for language in languages.available_languages()]
SAMPLE_DAY = datetime.date(2026, 11, 4)  # a Wednesday

ITALIAN = """\
code: it
name: Italian
native_name: italiano
aliases: [ita]
default_enabled: false

calendar:
  weekdays: [lunedì, martedì, mercoledì, giovedì, venerdì, sabato, domenica]
  months: [gennaio, febbraio, marzo, aprile, maggio, giugno, luglio, agosto, settembre, ottobre, novembre, dicembre]
  month_abbreviations: [gen, feb, mar, apr, mag, giu, lug, ago, set, ott, nov, dic]
  parts_of_day: [alba, mattina, pomeriggio, sera]
  range_word: alle
  clock: 24
  formats:
    date: "{day} {month} {year}"
    day_label: "{weekday} {day} {month}"
    weekday_date: "{weekday} {date}"
    full_date: "{weekday} {date}"
    day_title: "{weekday}. {day} {month_abbr}"

messages:
  closing: "Grazie per averci contattato."
  unsupported_media: "Non ho capito il messaggio. Per ora rispondo solo a testo."
  menu_offer: "Posso risponderti in {languages}."
  menu_or: o

router:
  explicit_phrases: [parla in italiano, in italiano per favore]
  inability_phrases: [non parlo inglese]
  content_words: [ciao, grazie, buongiorno, vorrei]
  bare_reply_words: si no certo va bene perfetto

scheduling:
  today: [oggi]
  tomorrow: [domani]
  day_after_tomorrow: [dopodomani]
  part_words:
    early_morning: [alba]
    morning: [mattina]
    afternoon: [pomeriggio]
    night: [sera, notte]
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A copy of the real data directory that a test may add files to or remove files from."""
    copy = tmp_path / "data"
    shutil.copytree(registry.DATA_DIR, copy)
    monkeypatch.setattr(registry, "DATA_DIR", copy)
    languages.reload()
    yield copy
    monkeypatch.undo()
    languages.reload()


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_every_language_file_is_complete(code):
    """Every language file is complete."""
    language = languages.get(code)
    assert language is not None and language.code == code
    assert language.explicit_phrases and language.content_words and language.bare_reply_words
    assert language.today and language.tomorrow and language.day_after_tomorrow
    assert all(language.part_words[key] for key in languages.registry.PART_KEYS)
    assert language.ordinals["first"] and language.ordinals["last"]
    for text in (
        language.format_date(SAMPLE_DAY),
        language.day_label(SAMPLE_DAY),
        language.weekday_date(SAMPLE_DAY),
        language.full_date(SAMPLE_DAY),
        language.day_title(SAMPLE_DAY),
        language.format_time(15, 30),
        language.messages["menu_offer"].format(languages="x"),
    ):
        assert text and "{" not in text
    assert "2026" in language.format_date(SAMPLE_DAY)
    assert language.weekdays[SAMPLE_DAY.weekday()].lower() in language.day_label(SAMPLE_DAY).lower()


@pytest.mark.parametrize("code", LANGUAGE_CODES)
def test_language_found_by_any_spelling(code):
    """A language is found by every way it is written."""
    language = languages.get(code)
    for written in (
        language.code,
        language.code.upper(),
        language.name,
        language.name.upper(),
        language.native_name,
        f"{language.code}-XX",
        f"{language.code}_XX",
        *language.aliases,
    ):
        assert languages.get(written) is language


def test_unknown_language_is_none():
    """Unknown languages give None without raising."""
    assert languages.get("klingon") is None and languages.get(None) is None and languages.get("") is None
    assert languages.resolve("klingon").code == "en"
    assert languages.resolve("klingon", default="es").code == "es"


def test_dates_and_clock_per_language():
    """Dates and clock times follow each language."""
    assert languages.get("es").full_date(SAMPLE_DAY) == "miércoles, 4 de noviembre de 2026"
    assert languages.get("es").weekday_date(SAMPLE_DAY) == "miércoles 4 de noviembre de 2026"
    assert languages.get("en").full_date(SAMPLE_DAY) == "Wednesday, November 4, 2026"
    assert languages.get("fr").full_date(SAMPLE_DAY) == "mercredi 4 novembre 2026"
    assert languages.get("es").format_time(15, 30) == "03:30 pm"
    assert languages.get("es").format_time(0, 5) == "12:05 am"
    assert languages.get("pt").format_time(15, 30) == "15:30"


def test_env_picks_languages_in_order(monkeypatch):
    """The environment picks the allowed languages in its own order."""
    monkeypatch.delenv(languages.LANGUAGES_ENV, raising=False)
    assert [language.code for language in languages.enabled_languages()] == ["en", "es", "pt"]
    monkeypatch.setenv(languages.LANGUAGES_ENV, "French, es; english|klingon")
    assert [language.code for language in languages.enabled_languages()] == ["fr", "es", "en"]


def test_new_language_is_a_file(data_dir, monkeypatch):
    """Adding a language only requires adding its file."""
    from agent_backend.channels.ghl.text import normalize_language
    from agent_runtime.runtime.global_router import _detect_fixed_phrases, _language_menu, is_bare_yes_no

    (data_dir / "it.yaml").unlink()  # the copy has the real Italian: start without it
    languages.reload()
    assert languages.get("it") is None
    assert normalize_language("Italiano") == "en"

    (data_dir / "it.yaml").write_text(ITALIAN, encoding="utf-8")
    languages.reload()
    monkeypatch.setenv(languages.LANGUAGES_ENV, "English,Italian")

    italian = languages.get("Italiano")
    assert italian is not None and italian.code == "it"
    assert normalize_language("Italiano") == "it"
    assert italian.full_date(SAMPLE_DAY) == "mercoledì 4 novembre 2026"
    assert [language.name for language in languages.enabled_languages()] == ["English", "Italian"]
    assert _detect_fixed_phrases("parla in italiano per favore", "English") == ("Italian", "explicit")
    assert _detect_fixed_phrases("Ciao, vorrei un appuntamento", "English") == ("Italian", "content_answer")
    assert is_bare_yes_no("perfetto")
    assert (
        _language_menu()
        == "I can assist you in English or italiano. / Posso risponderti in English o italiano."
    )
    assert languages.month_by_word()["novembre"] == 11
    assert languages.weekday_by_word()["martedi"] == 1
    assert languages.today_pattern().search("oggi") and languages.tomorrow_pattern().search("domani")
    assert any(
        key == "morning" and pattern.search("di mattina") for key, pattern in languages.part_patterns()
    )

    (data_dir / "it.yaml").unlink()
    languages.reload()
    assert languages.get("it") is None
    assert [language.name for language in languages.enabled_languages()] == ["English"]
    assert normalize_language("Italiano") == "en"


def test_unknown_placeholder_refused(data_dir):
    """A format with an unknown placeholder is refused when loaded."""
    (data_dir / "it.yaml").write_text(ITALIAN.replace("{month_abbr}", "{month_abbrev}"), encoding="utf-8")
    languages.reload()
    with pytest.raises(
        ValueError, match=r"it\.yaml: a calendar format or message uses an unknown placeholder"
    ):
        languages.available_languages()


def test_broken_file_names_itself(data_dir):
    """A broken language file is refused with its name."""
    (data_dir / "it.yaml").write_text(ITALIAN.replace("  range_word: alle\n", ""), encoding="utf-8")
    languages.reload()
    with pytest.raises(ValueError, match=r"it\.yaml: missing 'calendar\.range_word'"):
        languages.available_languages()

    (data_dir / "it.yaml").write_text(ITALIAN.replace("code: it", "code: xx"), encoding="utf-8")
    languages.reload()
    with pytest.raises(ValueError, match="must match the file name"):
        languages.available_languages()


def test_french_scheduling_words():
    """French scheduling words pick a day and a time of day."""
    from agent_runtime.runtime.graph_builder import _describe_time_choice, _resolve_day_reference

    calendar = "2026-11-03 Tuesday\n2026-11-04 Wednesday\n2026-11-05 Thursday\n2026-11-06 Friday"
    assert _resolve_day_reference("demain", calendar, None) == "2026-11-04"
    assert _resolve_day_reference("après-demain", calendar, None) == "2026-11-05"
    assert _resolve_day_reference("aujourd'hui", calendar, None) == "2026-11-03"
    assert _resolve_day_reference("vendredi", calendar, None) == "2026-11-06"
    assert _describe_time_choice("plutôt l'après-midi") == ("tarde", None)
    assert _describe_time_choice("le matin")[0] == "manana"
    assert _describe_time_choice("le dernier")[1] == -1
