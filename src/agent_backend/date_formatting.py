"""Full date and time formatting (Spanish, English, Portuguese) for the e-mails and replies of the scheduling tools.

Own day and month tables are used because Node's ``Intl.DateTimeFormat`` output cannot be matched portably."""
from datetime import datetime

_WEEKDAYS_ES = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_WEEKDAYS_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_WEEKDAYS_PT = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"]
_MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _weekday_index(dt: datetime) -> int:
    """dt.weekday(): Lunes=0..Domingo=6 -> indice Domingo=0..Sabado=6 (para las tablas de arriba).
    """
    return (dt.weekday() + 1) % 7


def format_full_date(dt: datetime, language: str) -> str:
    """Fecha en prosa completa, ej. 'Martes, 8 de abril de 2026' (ES/PT) o 'Tuesday, April 8, 2026' (EN).
    """
    idx = _weekday_index(dt)
    if language == "ES":
        text = f"{_WEEKDAYS_ES[idx]}, {dt.day} de {_MONTHS_ES[dt.month - 1]} de {dt.year}"
        return text[0].upper() + text[1:]
    if language == "PT":
        text = f"{_WEEKDAYS_PT[idx]}, {dt.day} de {_MONTHS_PT[dt.month - 1]} de {dt.year}"
        return text[0].upper() + text[1:]
    return f"{_WEEKDAYS_EN[idx]}, {_MONTHS_EN[dt.month - 1]} {dt.day}, {dt.year}"


def format_booking_time(dt: datetime, language: str) -> str:
    """Hora local: 12h am/pm en español (ej. '03:30 pm'), 24h en inglés/portugués (ej. '15:30').
    """
    if language == "ES":
        hour12 = dt.hour % 12 or 12
        period = "am" if dt.hour < 12 else "pm"
        return f"{hour12:02d}:{dt.minute:02d} {period}"
    return f"{dt.hour:02d}:{dt.minute:02d}"
