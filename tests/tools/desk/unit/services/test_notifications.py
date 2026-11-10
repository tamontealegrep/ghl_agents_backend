import asyncio
from datetime import UTC, datetime

import pytest
from desk.services import notifications
from desk.services.notifications import join_errors, notify_booking


class _Gmail:
    google_client_id = google_client_secret = google_refresh_token = "x"
    sender_email = "sender@example.org"


class _Settings:
    gmail = _Gmail()
    notification_email = "team@example.org"


def _run(settings, **overrides):
    kwargs = dict(
        calendar="IVF",
        contact_name="Ana <b>Perez</b>",
        contact_email="ana@gmail.com",
        contact_phone="+570000000",
        start_dt=datetime(2027, 3, 3, 14, 0, tzinfo=UTC),
        timezone="America/Bogota",
        event_link="https://cal/e",
        meet_link=None,
    )
    kwargs.update(overrides)
    return asyncio.run(notify_booking(settings, **kwargs))


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def _token(*args, **kwargs):
        return "token"

    async def _send(token, sender, to, subject, html):
        calls.append({"to": to, "sender": sender, "subject": subject, "html": html})
        return {}

    monkeypatch.setattr(notifications, "get_access_token", _token)
    monkeypatch.setattr(notifications, "send_email", _send)
    return calls


def test_nothing_is_sent_when_notification_email_is_not_set(sent):
    class _Off(_Settings):
        notification_email = ""

    assert _run(_Off()) is None
    assert sent == []


def test_email_goes_to_the_configured_address_with_booking_details(sent):
    assert _run(_Settings()) is None
    [mail] = sent
    assert mail["to"] == "team@example.org" and mail["sender"] == "sender@example.org"
    assert "IVF" in mail["subject"]
    assert "+570000000" in mail["html"] and "https://cal/e" in mail["html"]
    assert "09:00" in mail["html"] or "9:00" in mail["html"]  # 14:00 UTC = 09:00 Bogota


def test_user_supplied_text_is_html_escaped(sent):
    _run(_Settings())
    assert "<b>Perez</b>" not in sent[0]["html"]
    assert "&lt;b&gt;Perez&lt;/b&gt;" in sent[0]["html"]


def test_missing_gmail_credentials_are_reported_not_raised(sent):
    class _NoGmail(_Settings):
        class gmail:
            google_client_id = google_client_secret = google_refresh_token = sender_email = ""

    message = _run(_NoGmail())
    assert "FA_NOTIFICATION_EMAIL" in message and "Missing Gmail credentials" in message
    assert sent == []


def test_send_failure_is_reported_not_raised(monkeypatch, sent):
    async def _boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications, "send_email", _boom)
    assert "smtp down" in _run(_Settings())


def test_join_errors_skips_empty_values():
    assert join_errors(None, "", "a", "b") == "a; b"
    assert join_errors(None, "") is None


def test_several_addresses_receive_one_message(sent):
    class _Many(_Settings):
        notification_email = "a@example.org, b@example.org;c@example.org"

    assert _run(_Many()) is None
    assert len(sent) == 1
    assert sent[0]["to"] == "a@example.org, b@example.org, c@example.org"


def test_invalid_addresses_are_skipped_and_reported(sent):
    class _Mixed(_Settings):
        notification_email = "ok@example.org, nope"

    message = _run(_Mixed())
    assert sent[0]["to"] == "ok@example.org"
    assert "nope" in message


def test_only_invalid_addresses_send_nothing_and_say_why(sent):
    class _Bad(_Settings):
        notification_email = "nope"

    assert "nope" in _run(_Bad())
    assert sent == []
