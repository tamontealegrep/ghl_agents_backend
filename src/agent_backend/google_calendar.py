"""Google Calendar REST helpers (OAuth token, events, free/busy) shared by every company."""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx

from agent_backend.timezones import parse_iso


async def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
    """Intercambia el refresh token por un access token de Google OAuth.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json().get("access_token")


async def get_free_busy(
    access_token: str, calendar_id: str, time_min: datetime, time_max: datetime
) -> List[Tuple[datetime, datetime]]:
    """Consulta los intervalos ocupados del calendario en Google Calendar dentro del rango dado.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://www.googleapis.com/calendar/v3/freeBusy",
            json={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "timeZone": "UTC",
                "items": [{"id": calendar_id}],
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        cal = (data.get("calendars") or {}).get(calendar_id) or {}
        busy = cal.get("busy") or []
        return [(parse_iso(b["start"]), parse_iso(b["end"])) for b in busy]


async def create_event(
    access_token: str,
    calendar_id: str,
    summary: str,
    description: str,
    start_dt: datetime,
    end_dt: datetime,
    attendee_email: str,
    request_id: str,
) -> dict:
    """Crea un evento en Google Calendar con videollamada de Google Meet y notifica al asistente (sendUpdates=all).
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
            params={"sendUpdates": "all", "conferenceDataVersion": 1},
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Bogota"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Bogota"},
                "attendees": [{"email": attendee_email}],
                "sendUpdates": "all",
                "conferenceData": {
                    "createRequest": {
                        "requestId": request_id,
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def list_events(
    access_token: str, calendar_id: str, time_min: datetime, time_max: datetime, query: Optional[str] = None
) -> List[dict]:
    """Lista eventos en el calendario dado dentro del rango de tiempo, manejando paginación.
    """
    events = []
    page_token = None
    
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            params = {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if query:
                params["q"] = query
            if page_token:
                params["pageToken"] = page_token

            resp = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            events.extend(data.get("items", []))
            
            page_token = data.get("nextPageToken")
            if not page_token:
                break
                
    return events


async def delete_event(access_token: str, calendar_id: str, event_id: str) -> bool:
    """Elimina un evento del calendario.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.delete(
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events/{event_id}",
            params={"sendUpdates": "all"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        # 204 No Content es éxito en DELETE
        return resp.status_code == 204


async def update_event(
    access_token: str,
    calendar_id: str,
    event_id: str,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    summary: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Actualiza parcialmente un evento en Google Calendar (PATCH).
    """
    body = {}
    if summary:
        body["summary"] = summary
    if description:
        body["description"] = description
    if start_dt:
        body["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "America/Bogota"}
    if end_dt:
        body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "America/Bogota"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.patch(
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events/{event_id}",
            params={"sendUpdates": "all"},
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

def normalize_meet_url(value: Optional[str]) -> Optional[str]:
    """Normaliza enlaces de Meet para compararlos sin query parameters."""
    if not value:
        return None

    parsed = urlparse(value.strip())

    if parsed.hostname != "meet.google.com":
        return None

    path = parsed.path.rstrip("/")

    if not path:
        return None

    return f"https://meet.google.com{path}"


async def find_synced_google_event(
    access_token: str,
    calendar_id: str,
    start_dt: datetime,
    end_dt: datetime,
    meet_link: str,
    attempts: int = 4,
) -> Optional[dict]:
    """
    Busca el evento sincronizado desde GHL.

    No crea ni modifica eventos.
    Compara el enlace de Meet y el instante de inicio.
    Hace reintentos limitados porque la sincronización puede tardar.
    """
    expected_meet = normalize_meet_url(meet_link)

    if not expected_meet:
        return None

    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria.")

    for attempt in range(attempts):
        if attempt > 0:
            # Esperas de 1, 2 y 4 segundos con attempts=4.
            await asyncio.sleep(2 ** (attempt - 1))

        events = await list_events(
            access_token=access_token,
            calendar_id=calendar_id,
            time_min=start_dt - timedelta(minutes=5),
            time_max=end_dt + timedelta(minutes=5),
        )

        matches = []

        for event in events:
            if event.get("status") == "cancelled":
                continue

            event_start = (event.get("start") or {}).get("dateTime")

            if not event_start:
                continue

            try:
                event_start_dt = datetime.fromisoformat(
                    event_start.replace("Z", "+00:00")
                )
            except ValueError:
                continue

            if event_start_dt != start_dt:
                continue

            meeting_urls = {
                normalize_meet_url(event.get("hangoutLink"))
            }

            conference_data = event.get("conferenceData") or {}

            for entry in conference_data.get("entryPoints") or []:
                if entry.get("entryPointType") == "video":
                    meeting_urls.add(
                        normalize_meet_url(entry.get("uri"))
                    )

            if expected_meet in meeting_urls:
                matches.append(event)

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            # No elegir arbitrariamente si hubiera duplicados.
            return None

    return None
