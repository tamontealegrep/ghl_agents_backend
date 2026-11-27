"""Spanish labels of a booked appointment, saved in the contact's custom fields and read by the WhatsApp template."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
_MONTHS = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)


def appointment_labels(start: datetime, timezone: str) -> tuple[str, str]:
    """Returns the date and the time of an appointment as the contact reads them, in her time zone.

    The date looks like ``Martes, 16 de NOVIEMBRE de 2026`` and the time like ``08:50 a.m`` (12-hour clock, no final
    period, ``12:00 p.m`` at noon and ``12:30 a.m`` after midnight).

    Args:
        start: Start of the appointment; it must carry a time zone.
        timezone: IANA time zone of the contact.

    Returns:
        ``(appointment_date, appointment_time)``.
    """
    local = start.astimezone(ZoneInfo(timezone))
    date_label = f"{_WEEKDAYS[local.weekday()]}, {local.day} de {_MONTHS[local.month - 1]} de {local.year}"
    hour12 = local.hour % 12 or 12
    time_label = f"{hour12:02d}:{local.minute:02d} {'a.m' if local.hour < 12 else 'p.m'}"
    return date_label, time_label
