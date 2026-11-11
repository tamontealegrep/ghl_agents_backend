"""Link that adds an appointment to the patient's own Google Calendar.

GoHighLevel gives no event link, so the confirmation e-mail's button builds one: Google's
"create event" URL carries the title, the time and the video-call link, needs no credentials
and works the same whichever advisor the round robin picked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

TITLES = {
    "ES": "Cita con Family Aims",
    "EN": "Appointment with Family Aims",
    "PT": "Consulta com a Family Aims",
}
DETAILS = {
    "ES": "Enlace de la videollamada: {meet}",
    "EN": "Video call link: {meet}",
    "PT": "Link da videochamada: {meet}",
}


def build_add_to_calendar_link(
    start_dt: datetime, end_dt: datetime, language: str, meet_link: str | None = None
) -> str:
    """Builds the Google Calendar "add this event" URL for an appointment.

    Args:
        start_dt: Appointment start, timezone-aware.
        end_dt: Appointment end, timezone-aware.
        language: ``ES``, ``EN`` or ``PT`` (any case); anything else falls back to ``ES``.
        meet_link: Video-call link, put in the location and the description when there is one.

    Returns:
        The URL; opening it shows the event ready to be saved.
    """
    lang = (language or "ES").upper()
    if lang not in TITLES:
        lang = "ES"

    def stamp(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    params = {"action": "TEMPLATE", "text": TITLES[lang], "dates": f"{stamp(start_dt)}/{stamp(end_dt)}"}
    if meet_link:
        params["location"] = meet_link
        params["details"] = DETAILS[lang].format(meet=meet_link)
    return "https://calendar.google.com/calendar/render?" + urlencode(params)
