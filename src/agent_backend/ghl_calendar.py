"""Cliente HTTP para calendarios y citas de GoHighLevel.

Responsabilidades:
- Consultar calendarios y disponibilidad.
- Crear, consultar, actualizar, cancelar y eliminar citas.
- Resolver contactos mediante upsert.
- Extraer el enlace de Google Meet devuelto por GHL.

No contiene:
- Carga de variables de entorno.
- Reglas de negocio.
- Envío de correos.
- Sincronización propia con Google.
- Reintentos automáticos de escritura.

Errores:
- httpx.HTTPStatusError: GHL devolvió una respuesta HTTP de error.
- httpx.RequestError: fallo de conexión o timeout.
- ValueError: argumentos inválidos o respuesta inesperada.

IMPORTANTE:
Si una escritura falla por timeout o por un error de servidor,
la operación podría haberse procesado. No reintentar a ciegas.
"""

from datetime import datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
DEFAULT_TIMEOUT = 30.0


# ============================================================
# UTILIDADES INTERNAS
# ============================================================


def _encode_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("El identificador no puede estar vacío.")

    return quote(value.strip(), safe="")


def _validate_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} debe ser datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe incluir información de zona horaria.")


def _validate_range(start_dt: datetime, end_dt: datetime) -> None:
    _validate_datetime(start_dt, "start_dt")
    _validate_datetime(end_dt, "end_dt")

    if end_dt <= start_dt:
        raise ValueError("end_dt debe ser posterior a start_dt.")


def _parse_slot(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _validate_datetime(parsed, "slot")
    return parsed


async def _request(
    access_token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Ejecuta una solicitud y devuelve un objeto JSON.

    Permite reutilizar un AsyncClient creado por el endpoint.
    Si no se proporciona, crea y cierra uno para esta solicitud.
    """
    if not access_token or not access_token.strip():
        raise ValueError("access_token no puede estar vacío.")

    headers = {
        "Authorization": f"Bearer {access_token.strip()}",
        "Version": API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async def execute(http_client: httpx.AsyncClient) -> dict[str, Any]:
        response = await http_client.request(
            method=method,
            url=f"{BASE_URL}{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )

        # No transformar un error de API en una lista vacía o False.
        response.raise_for_status()

        if not response.content:
            return {}

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"GHL devolvió una respuesta JSON inesperada para {path}.")

        return data

    if client is not None:
        return await execute(client)

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as owned_client:
        return await execute(owned_client)


# ============================================================
# CALENDARIOS
# ============================================================


async def list_calendars(
    access_token: str,
    location_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Consulta los calendarios de una subcuenta. Devuelve el JSON de GHL."""
    return await _request(
        access_token,
        "GET",
        "/calendars/",
        params={"locationId": location_id},
        client=client,
    )


async def get_calendar(
    access_token: str,
    calendar_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Consulta la configuración de un calendario."""
    return await _request(
        access_token,
        "GET",
        f"/calendars/{_encode_id(calendar_id)}",
        client=client,
    )


# ============================================================
# DISPONIBILIDAD
# ============================================================


async def get_free_slots(
    access_token: str,
    calendar_id: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone: str = "America/Bogota",
    *,
    user_id: str | None = None,
    duration_minutes: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Consulta disponibilidad y devuelve el JSON completo de GHL.

    duration_minutes se envía como ``duration`` y debe coincidir con una duración
    activa del calendario en GHL; si es None, GHL usa la duración por defecto.

    Los timestamps enviados a GHL están en milisegundos.
    Usa rangos acotados que cumplan los límites de la API.
    """
    _validate_range(start_dt, end_dt)

    params: dict[str, Any] = {
        "startDate": int(start_dt.timestamp() * 1000),
        "endDate": int(end_dt.timestamp() * 1000),
        "timezone": timezone,
    }

    if user_id:
        params["userId"] = user_id
    if duration_minutes:
        params["duration"] = int(duration_minutes)

    return await _request(
        access_token,
        "GET",
        f"/calendars/{_encode_id(calendar_id)}/free-slots",
        params=params,
        client=client,
    )


async def get_available_slots(
    access_token: str,
    calendar_id: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone: str = "America/Bogota",
    *,
    user_id: str | None = None,
    duration_minutes: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Devuelve los horarios ISO disponibles, ordenados y sin duplicados.

    No aplica políticas de negocio ni reserva los horarios.
    La separación entre slots no determina la duración de las citas.
    """
    data = await get_free_slots(
        access_token=access_token,
        calendar_id=calendar_id,
        start_dt=start_dt,
        end_dt=end_dt,
        timezone=timezone,
        user_id=user_id,
        duration_minutes=duration_minutes,
        client=client,
    )

    slots = set()

    for day_data in data.values():
        # Ignorar campos como traceId.
        if not isinstance(day_data, dict):
            continue

        day_slots = day_data.get("slots")

        if day_slots is None:
            continue

        if not isinstance(day_slots, list):
            raise ValueError("GHL devolvió un campo slots inesperado.")

        for slot in day_slots:
            if not isinstance(slot, str):
                raise ValueError("GHL devolvió un horario no válido.")

            # Validar antes de devolverlo al consumidor.
            _parse_slot(slot)
            slots.add(slot)

    return sorted(slots, key=_parse_slot)


# ============================================================
# CONTACTOS
# ============================================================


async def upsert_contact(
    access_token: str,
    location_id: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Crea o actualiza un contacto.

    La coincidencia depende de la configuración de duplicados
    de la subcuenta. Puede actualizar datos de un contacto existente.

    Devuelve el JSON completo, normalmente con data["contact"]["id"].
    """
    if not email and not phone:
        raise ValueError("Debes proporcionar email o phone.")

    payload: dict[str, Any] = {
        "locationId": location_id,
    }

    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone
    if name:
        payload["name"] = name

    return await _request(
        access_token,
        "POST",
        "/contacts/upsert",
        payload=payload,
        client=client,
    )


# ============================================================
# CITAS
# ============================================================


async def create_appointment(
    access_token: str,
    calendar_id: str,
    location_id: str,
    contact_id: str,
    start_dt: datetime,
    end_dt: datetime,
    title: str,
    *,
    appointment_status: str = "new",
    to_notify: bool = False,
    assigned_user_id: str | None = None,
    address: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Crea una cita y devuelve el JSON de GHL.

    No consulta disponibilidad previamente.
    GHL valida la reserva según las reglas del calendario.

    Si Google Meet está configurado, GHL puede devolver el enlace
    en "address". No se garantiza que esté disponible inmediatamente.

    Si quieres que GHL determine la ubicación y el staff,
    omite address y assigned_user_id.
    """
    _validate_range(start_dt, end_dt)

    payload: dict[str, Any] = {
        "calendarId": calendar_id,
        "locationId": location_id,
        "contactId": contact_id,
        "startTime": start_dt.isoformat(),
        "endTime": end_dt.isoformat(),
        "title": title,
        "appointmentStatus": appointment_status,
        "toNotify": to_notify,
    }

    if assigned_user_id is not None:
        payload["assignedUserId"] = assigned_user_id

    if address is not None:
        payload["address"] = address

    return await _request(
        access_token,
        "POST",
        "/calendars/events/appointments",
        payload=payload,
        client=client,
    )


async def get_appointment(
    access_token: str,
    appointment_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Obtiene una cita utilizando su ID de GHL, no el de Google."""
    return await _request(
        access_token,
        "GET",
        f"/calendars/events/appointments/{_encode_id(appointment_id)}",
        client=client,
    )


async def list_events(
    access_token: str,
    location_id: str,
    calendar_id: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Consulta eventos del calendario en un rango.

    Devuelve el JSON completo de GHL, incluido el campo "events".
    Esta consulta puede incluir otros tipos de eventos, no solo citas.
    """
    _validate_range(start_dt, end_dt)

    return await _request(
        access_token,
        "GET",
        "/calendars/events",
        params={
            "locationId": location_id,
            "calendarId": calendar_id,
            "startTime": int(start_dt.timestamp() * 1000),
            "endTime": int(end_dt.timestamp() * 1000),
        },
        client=client,
    )


async def update_appointment(
    access_token: str,
    appointment_id: str,
    *,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    title: str | None = None,
    appointment_status: str | None = None,
    assigned_user_id: str | None = None,
    address: str | None = None,
    to_notify: bool | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Actualiza una cita mediante PUT.

    Solo envía campos proporcionados.
    Para reprogramar, esta librería exige inicio y fin juntos.
    """
    payload: dict[str, Any] = {}

    if start_dt is not None or end_dt is not None:
        if start_dt is None or end_dt is None:
            raise ValueError("Para reprogramar debes proporcionar start_dt y end_dt.")

        _validate_range(start_dt, end_dt)

        payload["startTime"] = start_dt.isoformat()
        payload["endTime"] = end_dt.isoformat()

    if title is not None:
        payload["title"] = title

    if appointment_status is not None:
        payload["appointmentStatus"] = appointment_status

    if assigned_user_id is not None:
        payload["assignedUserId"] = assigned_user_id

    if address is not None:
        payload["address"] = address

    if to_notify is not None:
        payload["toNotify"] = to_notify

    if not payload:
        raise ValueError("Debes proporcionar al menos un campo a actualizar.")

    return await _request(
        access_token,
        "PUT",
        f"/calendars/events/appointments/{_encode_id(appointment_id)}",
        payload=payload,
        client=client,
    )


async def cancel_appointment(
    access_token: str,
    appointment_id: str,
    *,
    to_notify: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Marca la cita como cancelada sin eliminarla.

    Preferible a DELETE cuando necesitas conservar trazabilidad.
    """
    return await update_appointment(
        access_token=access_token,
        appointment_id=appointment_id,
        appointment_status="cancelled",
        to_notify=to_notify,
        client=client,
    )


async def delete_appointment(
    access_token: str,
    appointment_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Elimina el evento de GHL.

    No equivale a marcar una cita como cancelada.
    Devuelve True si GHL responde exitosamente.
    Un 404 u otro error HTTP se propaga, no se oculta.
    """
    await _request(
        access_token,
        "DELETE",
        f"/calendars/events/{_encode_id(appointment_id)}",
        client=client,
    )

    return True


# ============================================================
# INTERPRETACIÓN DE RESPUESTAS
# ============================================================


def extract_appointment(data: dict[str, Any]) -> dict[str, Any]:
    """Extrae la cita de una respuesta directa o envuelta.

    Acepta:
        {"id": "...", ...}
        {"appointment": {"id": "...", ...}}
        {"event": {"id": "...", ...}}
    """
    if not isinstance(data, dict):
        raise ValueError("La respuesta debe ser un diccionario.")

    if isinstance(data.get("appointment"), dict):
        return data["appointment"]

    if isinstance(data.get("event"), dict):
        return data["event"]

    return data


def get_meet_link(data: dict[str, Any]) -> str | None:
    """Extrae un enlace de Google Meet del campo address.

    No crea enlaces ni consulta Google Calendar.
    Devuelve None cuando el campo no contiene un enlace de Meet.
    """
    appointment = extract_appointment(data)
    address = appointment.get("address")

    if not isinstance(address, str):
        return None

    value = address.strip()
    parsed = urlparse(value)

    if parsed.scheme == "https" and parsed.hostname == "meet.google.com" and parsed.path not in {"", "/"}:
        return value

    return None
