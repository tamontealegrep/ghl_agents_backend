"""Optional internal e-mail sent when an appointment is booked.

Enabled by setting ``FA_NOTIFICATION_EMAIL``. It uses the shared Gmail account of
the plugin and never makes a booking fail: problems are returned as text.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_backend.team_notification import join_errors, send_team_notification  # noqa: F401

from . import date_formatting
from .email_templates import render_email_template
from .gmail import send_email
from .google_calendar import get_access_token

TEMPLATE = "internal_booking_notification"


async def notify_booking(
    settings: Any,
    *,
    calendar: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    start_dt: datetime,
    timezone: str,
    event_link: Optional[str],
    meet_link: Optional[str],
) -> Optional[str]:
    """Tells the addresses in ``FA_NOTIFICATION_EMAIL`` that an appointment was booked.

    Args:
        settings: Plugin settings (``notification_email`` and ``gmail``).
        calendar: Calendar key, e.g. ``"IVF"``.
        contact_name: Patient name.
        contact_email: Patient e-mail.
        contact_phone: Patient phone.
        start_dt: Appointment start, timezone-aware.
        timezone: IANA timezone the date and time are shown in.
        event_link: Link to the calendar event, if any.
        meet_link: Video-call link, if any.

    Returns:
        None when nothing was configured or the e-mail was sent; otherwise a text
        describing why the notification failed or which configured addresses were invalid.
    """
    local = start_dt.astimezone(ZoneInfo(timezone))

    def body() -> str:
        return render_email_template(
            TEMPLATE,
            calendar=escape(calendar),
            contact_name=escape(contact_name),
            contact_email=escape(contact_email),
            contact_phone=escape(contact_phone),
            booking_date=date_formatting.format_full_date(local, "ES"),
            booking_time=date_formatting.format_booking_time(local, "ES"),
            timezone=escape(timezone),
            event_link=escape(event_link or "-"),
            meet_link=escape(meet_link or "-"),
        )

    return await send_team_notification(
        variable="FA_NOTIFICATION_EMAIL",
        prefix="FA",
        notification_email=getattr(settings, "notification_email", ""),
        gmail=settings.gmail,
        subject=f"Nueva cita agendada ({calendar}): {contact_name}",
        render_body=body,
        get_access_token=lambda *args: get_access_token(*args),  # resolved at call time (tests replace them)
        send_email=lambda *args: send_email(*args),
    )
