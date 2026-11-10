"""
Module.

    Reglas de negocio puras para validar y normalizar una solicitud de callback
    (llamada de vuelta). No sabe nada de HTTP, no envía correos ni crea eventos
    de calendario — eso queda a cargo de una acción del flujo GHL que consuma
    esta salida ya normalizada, ya que el mecanismo de notificación es
    específico de cada cliente (credencial de Gmail, contact center, etc.) y
    esta herramienta vive en tools.utils, sin lógica ni credencial de un
    cliente en particular.
"""

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_VALID_REASONS = {"no_availability", "booking_failed", "user_requested", "ambiguous_data", "technical_error"}

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAYS = set(_DAY_NAMES[:5])
_WEEKEND = set(_DAY_NAMES[5:])

_VALID_TIME_WINDOWS = {"morning", "midday", "afternoon", "evening"}


def _is_present(val: Any) -> bool:
    return val is not None and str(val).strip() != ""


def _split_list(raw: str | list[str] | None) -> list[str]:
    """Normalize input (comma-separated string or list) to a non-empty, lowercased list of strings.
    """
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    return [str(item).strip().lower() for item in items if str(item).strip()]


def _normalize_preferred_days(raw: str | list[str] | None) -> tuple[list[str], str | None]:
    """Accepts individual days and 'weekdays'/'weekend'/'any' shortcuts.

    Returns (ordered_days, error).
    """
    tokens = _split_list(raw)
    if not tokens:
        return [], None

    days = set()
    for token in tokens:
        if token == "any":
            return [], None
        elif token == "weekdays":
            days |= _WEEKDAYS
        elif token == "weekend":
            days |= _WEEKEND
        elif token in _DAY_NAMES:
            days.add(token)
        else:
            return [], f"Invalid day in preferred_days: '{token}'"

    return [d for d in _DAY_NAMES if d in days], None


def _normalize_time_window(raw: str | None) -> tuple[str | None, str | None]:
    if not _is_present(raw):
        return None, None
    token = str(raw).strip().lower()
    if token == "any":
        return None, None
    if token in _VALID_TIME_WINDOWS:
        return token, None
    return None, f"Invalid time window in preferred_time_window: '{token}'"


def _is_valid_timezone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


def _rejected(error_message: str) -> dict[str, Any]:
    return {
        "contact_name": None,
        "contact_phone": None,
        "contact_email": None,
        "reason": None,
        "context": None,
        "preferred_days": None,
        "preferred_time_window": None,
        "iana_timezone": None,
        "errors": error_message,
    }


def prepare_callback_request(
    raw_contact_name: str | None,
    raw_contact_phone: str | None,
    raw_contact_email: str | None,
    raw_reason: str | None,
    raw_context: str | None,
    raw_preferred_days: str | list[str] | None,
    raw_preferred_time_window: str | None,
    raw_timezone: str | None,
) -> dict[str, Any]:
    """Validate and normalize a callback request.

    No side effects.

    An invalid/incomplete input is a normal business result (errors explains why),
    not an exception — same convention as calculate_bmi and check_documentation.
    """
    contact_name = raw_contact_name.strip() if _is_present(raw_contact_name) else None
    contact_phone = raw_contact_phone.strip() if _is_present(raw_contact_phone) else None
    contact_email = raw_contact_email.strip() if _is_present(raw_contact_email) else None

    if not contact_name:
        return _rejected("contact_name is required")

    if not contact_phone and not contact_email:
        return _rejected("You must provide at least contact_phone or contact_email")

    reason = raw_reason.strip().lower() if _is_present(raw_reason) else None
    if reason not in _VALID_REASONS:
        return _rejected(f"invalid reason. Allowed values: {', '.join(sorted(_VALID_REASONS))}")

    if not _is_present(raw_timezone):
        return _rejected("timezone is required")
    timezone = raw_timezone.strip()
    if not _is_valid_timezone(timezone):
        return _rejected(f"invalid timezone: '{timezone}'")

    preferred_days, days_error = _normalize_preferred_days(raw_preferred_days)
    if days_error:
        return _rejected(days_error)

    preferred_time_window, window_error = _normalize_time_window(raw_preferred_time_window)
    if window_error:
        return _rejected(window_error)

    context = raw_context.strip() if _is_present(raw_context) else None

    return {
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "contact_email": contact_email,
        "reason": reason,
        "context": context,
        "preferred_days": preferred_days,
        "preferred_time_window": preferred_time_window,
        "iana_timezone": timezone,
        "errors": None,
    }
