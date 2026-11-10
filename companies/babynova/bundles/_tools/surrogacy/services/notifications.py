"""Optional e-mail that tells the team an appointment was booked.

Enabled by setting ``BN_NOTIFICATION_EMAIL`` (one or several addresses, comma-separated).
It is sent from the plugin's Gmail account and never makes a booking fail: problems are
returned as text.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from agent_backend.gmail import send_email
from agent_backend.google_calendar import get_access_token
from agent_backend.team_notification import send_team_notification

from .email_templates import render_email_template


async def notify_booking(
    settings: Any,
    policy: Any,
    *,
    contact_name: str,
    contact_phone: str,
    start_dt: datetime,
    timezone: str,
) -> str | None:
    """Tells the addresses in ``BN_NOTIFICATION_EMAIL`` that an appointment was booked.

    Args:
        settings: Plugin settings (``notification_email`` and ``gmail``).
        policy: Booking rules of the calendar (subject prefix, separator, template name).
        contact_name: Patient name.
        contact_phone: Patient phone.
        start_dt: Appointment start, timezone-aware.
        timezone: IANA timezone the date and time are shown in.

    Returns:
        None when nothing was configured or the e-mail was sent; otherwise a text
        describing why the notification failed or which configured addresses were invalid.
    """
    local_start = start_dt.astimezone(ZoneInfo(timezone))

    def body() -> str:
        return render_email_template(
            policy.EMAIL_TEMPLATE_NAME,
            contact_name=escape(contact_name),
            booking_date=local_start.strftime("%Y/%m/%d %H:%M"),
            contact_phone=escape(contact_phone),
        )

    return await send_team_notification(
        variable="BN_NOTIFICATION_EMAIL",
        prefix="BN",
        notification_email=getattr(settings, "notification_email", ""),
        gmail=settings.gmail,
        subject=f"{policy.EMAIL_SUBJECT_PREFIX}{policy.TITLE_SEPARATOR}{contact_name}{policy.TITLE_SEPARATOR}{contact_phone}",
        render_body=body,
        get_access_token=lambda *args: get_access_token(*args),  # resolved at call time (tests replace them)
        send_email=lambda *args: send_email(*args),
    )
