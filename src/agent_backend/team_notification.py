"""The optional e-mail that tells a company's team an appointment was booked."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from agent_backend.recipients import split_recipients

__all__ = ["join_errors", "send_team_notification"]


def join_errors(*messages: Optional[str]) -> Optional[str]:
    """Joins the non-empty messages.

    Args:
        *messages: Error texts; ``None`` and empty strings are skipped.

    Returns:
        The messages separated by ``"; "``, or None when there are none.
    """
    kept = [m for m in messages if m]
    return "; ".join(kept) if kept else None


async def send_team_notification(
    *,
    variable: str,
    prefix: str,
    notification_email: str,
    gmail: Any,
    subject: str,
    render_body: Callable[[], str],
    get_access_token: Callable[..., Awaitable[Optional[str]]],
    send_email: Callable[..., Awaitable[Any]],
) -> Optional[str]:
    """Sends the team notification of a booking; never raises.

    Args:
        variable: Name of the variable that holds the recipients (for messages), e.g. ``BN_NOTIFICATION_EMAIL``.
        prefix: Company variable prefix, for the missing-Gmail message.
        notification_email: Raw value of that variable: one or several comma-separated addresses.
        gmail: The company's Gmail settings (client id, secret, refresh token, sender).
        subject: Subject of the message.
        render_body: Builds the HTML body; called only when there is something to send.
        get_access_token: Exchanges the Gmail refresh token for an access token.
        send_email: Sends the message (``token, sender, to, subject, html``).

    Returns:
        None when nothing was configured or the e-mail was sent; otherwise text describing why the
        notification failed or which configured addresses were invalid.
    """
    recipients, invalid = split_recipients(notification_email)
    bad_note = f"; ignored invalid address(es) in {variable}: {', '.join(invalid)}" if invalid else ""
    if not recipients:
        return f"Notification not sent{bad_note}" if invalid else None
    try:
        if not (gmail.google_client_id and gmail.google_client_secret and gmail.google_refresh_token and gmail.sender_email):
            raise RuntimeError(f"Missing Gmail credentials ({prefix}_GOOGLE_CLIENT_ID_GMAIL / {prefix}_GMAIL_SENDER_EMAIL, etc.) in environment")
        token = await get_access_token(gmail.google_client_id, gmail.google_client_secret, gmail.google_refresh_token)
        if not token:
            raise RuntimeError("Failed to obtain Gmail access token")
        await send_email(token, gmail.sender_email, ", ".join(recipients), subject, render_body())
    except Exception as exc:
        return f"The appointment was created but the notification to {variable} failed: {exc}{bad_note}"
    return f"Notification sent{bad_note}" if invalid else None
