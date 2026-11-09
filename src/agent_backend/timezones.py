"""Date and timezone helpers used by the scheduling tools of every company."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def format_iso_with_offset(dt_utc: datetime, tz_name: str) -> str:
    """Aware datetime -> ISO string con el offset de esa zona horaria.
    """
    return dt_utc.astimezone(ZoneInfo(tz_name)).isoformat()


def get_date_key_in_tz(dt_utc: datetime, tz_name: str) -> str:
    """Aware datetime -> clave de fecha 'YYYY-MM-DD' en esa zona horaria.
    """
    return dt_utc.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def get_weekday_in_tz(dt_utc: datetime, tz_name: str) -> int:
    """Igual que el mapeo JS original: Domingo=0, Lunes=1, ..., Sábado=6.
    """
    local = dt_utc.astimezone(ZoneInfo(tz_name))
    iso = local.isoweekday()  # Lunes=1 ... Domingo=7
    return 0 if iso == 7 else iso


def build_business_instant(year: int, month: int, day: int, hour: int, minute: int, tz_name: str) -> datetime:
    """Construye un datetime aware a partir de año/mes/día/hora/minuto en la zona horaria dada.
    """
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz_name))


def add_days(dt: datetime, days: int) -> datetime:
    """Suma (o resta, si days es negativo) días a un datetime, preservando su zona horaria.
    """
    return dt + timedelta(days=days)


def parse_iso(value: str) -> datetime:
    """Parsea un string ISO 8601 (con o sin sufijo 'Z') a un datetime aware.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_hour_in_tz(dt_utc: datetime, tz_name: str) -> int:
    """Hora local (0-23) de ese datetime en la zona horaria dada.
    """
    return dt_utc.astimezone(ZoneInfo(tz_name)).hour


def get_date_in_tz(dt_utc: datetime, tz_name: str) -> date:
    """Fecha (sin hora) de ese datetime en la zona horaria dada.
    """
    return dt_utc.astimezone(ZoneInfo(tz_name)).date()
