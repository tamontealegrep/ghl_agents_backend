"""Full date and time formatting for the e-mails and replies of the scheduling tools.

The day and month names, the date layout and the clock of each language come from `agent_runtime.languages`.
"""

from datetime import datetime

from agent_runtime import languages


def format_full_date(dt: datetime, language: str) -> str:
    """Fecha en prosa completa, ej. 'Martes, 8 de abril de 2026' (ES/PT) o 'Tuesday, April 8, 2026' (EN).

    `language` is a code or a name in any case; a language with no data file is written in English.
    """
    text = languages.resolve(language).full_date(dt.date())
    return text[0].upper() + text[1:]


def format_booking_time(dt: datetime, language: str) -> str:
    """Hora local: 12h am/pm (ej. '03:30 pm') o 24h (ej. '15:30') según el idioma."""
    return languages.resolve(language).format_time(dt.hour, dt.minute)
