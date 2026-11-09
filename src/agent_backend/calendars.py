"""Calendar discovery from environment variables, shared by every company's tool plugin.

A company's calendars are declared in its ``.env`` by naming variables with the
company prefix (``FA``, ``BN``, ...) and a calendar key (``IVF``, ``FT``, ...)::

    <PREFIX>_GHL_CALENDAR_ID_<KEY>          GoHighLevel calendar
    <PREFIX>_GOOGLE_CLIENT_ID_<KEY>         Google OAuth client
    <PREFIX>_GOOGLE_CLIENT_SECRET_<KEY>
    <PREFIX>_GOOGLE_REFRESH_TOKEN_<KEY>
    <PREFIX>_GOOGLE_CALENDAR_ID_<KEY>       Google calendar
    <PREFIX>_DURATION_MINUTES_<KEY>         appointment length
    <PREFIX>_INTERVAL_MINUTES_<KEY>         minimum distance between the starts of offered slots (0 = no limit)
    <PREFIX>_PRE_BUFFER_MINUTES_<KEY>       free time required before an appointment
    <PREFIX>_POST_BUFFER_MINUTES_<KEY>      free time required after an appointment
    <PREFIX>_MIN_NOTICE_MINUTES_<KEY>       minimum notice before a slot (unset = the company's own rule)
    <PREFIX>_DATE_RANGE_DAYS_<KEY>          how many days ahead slots are offered

Any non-empty variable of that list declares the calendar ``<KEY>``; the key is what
tools receive as ``calendar_type``. The Gmail sender variables
(``<PREFIX>_GOOGLE_CLIENT_ID_GMAIL`` ...) are not calendars: ``GMAIL`` is a reserved key.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "CALENDAR_VARIABLES",
    "RESERVED_KEYS",
    "GHL_READABLE_FIELDS",
    "CalendarSettings",
    "calendar_env_pattern",
    "discover_calendar_keys",
    "load_calendar_settings",
    "load_calendars",
]

CALENDAR_VARIABLES: tuple[str, ...] = (
    "GHL_CALENDAR_ID",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_CALENDAR_ID",
    "DURATION_MINUTES",
    "INTERVAL_MINUTES",
    "PRE_BUFFER_MINUTES",
    "POST_BUFFER_MINUTES",
    "MIN_NOTICE_MINUTES",
    "DATE_RANGE_DAYS",
)
# Fields a company can leave to the GoHighLevel calendar (variable empty) instead of fixing them in the .env.
GHL_READABLE_FIELDS: tuple[str, ...] = (
    "duration_minutes",
    "pre_buffer_minutes",
    "post_buffer_minutes",
    "min_notice_minutes",
    "date_range_days",
)
_FIELD_VARIABLE = {
    "duration_minutes": "DURATION_MINUTES",
    "pre_buffer_minutes": "PRE_BUFFER_MINUTES",
    "post_buffer_minutes": "POST_BUFFER_MINUTES",
    "min_notice_minutes": "MIN_NOTICE_MINUTES",
    "date_range_days": "DATE_RANGE_DAYS",
}
# Keys that belong to something else and must never be read as a calendar.
RESERVED_KEYS: frozenset[str] = frozenset({"GMAIL"})


@dataclass
class CalendarSettings:
    """Credentials, ids and timings of one calendar.

    Attributes:
        google_client_id: Google OAuth client id.
        google_client_secret: Google OAuth client secret.
        google_refresh_token: Google OAuth refresh token.
        calendar_id: Google calendar id.
        ghl_calendar_id: GoHighLevel calendar id.
        duration_minutes: Appointment length.
        interval_minutes: Minimum distance between the starts of offered slots; 0 offers every slot.
        pre_buffer_minutes: Free time required before an appointment.
        post_buffer_minutes: Free time required after an appointment.
        min_notice_minutes: Minimum notice before a slot, or None to use the company's own rule.
        date_range_days: How many days ahead slots are offered.
        read_from_ghl: Names of the fields above whose variable was left empty and that
            GoHighLevel tools must take from the GHL calendar itself (the numeric fields then
            hold only a fallback for when GHL cannot be read).
    """

    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    calendar_id: str
    ghl_calendar_id: str
    duration_minutes: int = 30
    interval_minutes: int = 0
    pre_buffer_minutes: int = 0
    post_buffer_minutes: int = 0
    min_notice_minutes: int | None = None
    date_range_days: int = 14
    read_from_ghl: frozenset[str] = frozenset()


def calendar_env_pattern(prefix: str) -> re.Pattern[str]:
    """Builds the regular expression that recognizes a company's calendar variables.

    Args:
        prefix: Company variable prefix, e.g. ``"FA"``.

    Returns:
        A compiled pattern whose first group is the calendar key.
    """
    names = "|".join(CALENDAR_VARIABLES)
    return re.compile(rf"^{re.escape(prefix)}_(?:{names})_([A-Z0-9][A-Z0-9_]*)$")


def discover_calendar_keys(
    prefix: str,
    environ: Mapping[str, str] | None = None,
    builtin: Iterable[str] = (),
) -> list[str]:
    """Finds the calendar keys declared in the environment.

    Args:
        prefix: Company variable prefix, e.g. ``"FA"``.
        environ: Variables to scan. Defaults to ``os.environ``.
        builtin: Keys that always exist, even without a variable.

    Returns:
        Upper-case keys: the built-in ones first, then the rest alphabetically.
        A key counts only when at least one of its variables is non-empty;
        reserved keys (``GMAIL``) are skipped.
    """
    env = os.environ if environ is None else environ
    pattern = calendar_env_pattern(prefix)
    fixed = [k.upper() for k in builtin]
    found = {m.group(1) for name, value in env.items() if value and (m := pattern.match(name))}
    return [*fixed, *sorted(found - set(fixed) - RESERVED_KEYS)]


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Reads an integer variable.

    Args:
        env: Variables to read.
        name: Variable name.
        default: Value when the variable is unset or empty.

    Returns:
        The parsed value.

    Raises:
        ValueError: The variable is set to something that is not a whole number.
    """
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def _read_optional_int(env: Mapping[str, str], name: str, default: int | None) -> int | None:
    """Reads an integer variable that may stay unset.

    Args:
        env: Variables to read.
        name: Variable name.
        default: Value when the variable is unset or empty.

    Returns:
        The parsed value, or ``default``.

    Raises:
        ValueError: The variable is set to something that is not a whole number.
    """
    if not (env.get(name) or "").strip():
        return default
    return _read_int(env, name, 0)


def load_calendar_settings(
    prefix: str,
    key: str,
    *,
    duration_minutes: int = 30,
    interval_minutes: int = 0,
    pre_buffer_minutes: int = 0,
    post_buffer_minutes: int = 0,
    min_notice_minutes: int | None = None,
    date_range_days: int = 14,
    calendar_id: str = "",
    read_unset_from_ghl: bool = False,
    environ: Mapping[str, str] | None = None,
) -> CalendarSettings:
    """Reads one calendar's variables.

    Args:
        prefix: Company variable prefix.
        key: Calendar key.
        duration_minutes: Default appointment length.
        interval_minutes: Default minimum distance between slot starts.
        pre_buffer_minutes: Default buffer before an appointment.
        post_buffer_minutes: Default buffer after an appointment.
        min_notice_minutes: Default minimum notice; None keeps the company's own rule.
        date_range_days: Default horizon in days.
        calendar_id: Default Google calendar id.
        read_unset_from_ghl: When True, a duration, buffer, minimum-notice or date-range
            variable left empty is recorded in ``read_from_ghl`` so GoHighLevel tools read
            it from the GHL calendar.
        environ: Variables to read. Defaults to ``os.environ``.

    Returns:
        The calendar's settings, with defaults for anything unset.

    Raises:
        ValueError: A numeric variable holds a non-numeric value.
    """
    env = os.environ if environ is None else environ

    def var(stem: str) -> str:
        return env.get(f"{prefix}_{stem}_{key}", "")

    from_ghl = frozenset(
        field
        for field in GHL_READABLE_FIELDS
        if read_unset_from_ghl and not (env.get(f"{prefix}_{_FIELD_VARIABLE[field]}_{key}") or "").strip()
    )
    return CalendarSettings(
        google_client_id=var("GOOGLE_CLIENT_ID"),
        google_client_secret=var("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=var("GOOGLE_REFRESH_TOKEN"),
        calendar_id=var("GOOGLE_CALENDAR_ID") or calendar_id,
        ghl_calendar_id=var("GHL_CALENDAR_ID"),
        duration_minutes=_read_int(env, f"{prefix}_DURATION_MINUTES_{key}", duration_minutes),
        interval_minutes=_read_int(env, f"{prefix}_INTERVAL_MINUTES_{key}", interval_minutes),
        pre_buffer_minutes=_read_int(env, f"{prefix}_PRE_BUFFER_MINUTES_{key}", pre_buffer_minutes),
        post_buffer_minutes=_read_int(env, f"{prefix}_POST_BUFFER_MINUTES_{key}", post_buffer_minutes),
        min_notice_minutes=_read_optional_int(env, f"{prefix}_MIN_NOTICE_MINUTES_{key}", min_notice_minutes),
        date_range_days=_read_int(env, f"{prefix}_DATE_RANGE_DAYS_{key}", date_range_days),
        read_from_ghl=from_ghl,
    )


def load_calendars(
    prefix: str,
    builtin: Iterable[str] = (),
    *,
    duration_minutes: int = 30,
    interval_minutes: int = 0,
    pre_buffer_minutes: int = 0,
    post_buffer_minutes: int = 0,
    min_notice_minutes: int | None = None,
    date_range_days: int = 14,
    calendar_id_defaults: Mapping[str, str] | None = None,
    read_unset_from_ghl: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, CalendarSettings]:
    """Reads every calendar a company declares.

    Args:
        prefix: Company variable prefix.
        builtin: Keys that always exist.
        duration_minutes: Company default appointment length.
        interval_minutes: Company default minimum distance between slot starts.
        pre_buffer_minutes: Company default buffer before an appointment.
        post_buffer_minutes: Company default buffer after an appointment.
        min_notice_minutes: Company default minimum notice; None keeps the company's own rule.
        date_range_days: Company default horizon in days.
        calendar_id_defaults: Default Google calendar id per key (e.g. ``{"FT": "primary"}``).
        read_unset_from_ghl: See ``load_calendar_settings``.
        environ: Variables to read. Defaults to ``os.environ``.

    Returns:
        Settings by upper-case key, in discovery order.
    """
    id_defaults = {k.upper(): v for k, v in (calendar_id_defaults or {}).items()}
    return {
        key: load_calendar_settings(
            prefix,
            key,
            duration_minutes=duration_minutes,
            interval_minutes=interval_minutes,
            pre_buffer_minutes=pre_buffer_minutes,
            post_buffer_minutes=post_buffer_minutes,
            min_notice_minutes=min_notice_minutes,
            date_range_days=date_range_days,
            calendar_id=id_defaults.get(key, ""),
            read_unset_from_ghl=read_unset_from_ghl,
            environ=environ,
        )
        for key in discover_calendar_keys(prefix, environ, builtin)
    }
