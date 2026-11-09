from datetime import datetime, timedelta
import asyncio
import logging
from zoneinfo import ZoneInfo
from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.booking import BookAppointmentRequest, BookAppointmentResponse
from ....services.calendars import resolve_calendar, unknown_calendar_message
from ....services import booking_engine as engine
from ....services import date_formatting
from ....services import slot_engine as engine_slots
from ....services.email_templates import render_email_template
from ....services.gmail import send_email
from ....services.notifications import join_errors, notify_booking
from ....services.slot_rules import earliest_start, load_busy
from agent_backend.slot_filters import conflicts_with_busy
from ....services.ghl_calendar import (
    get_available_slots as ghl_get_available_slots,
    list_events as ghl_list_events,
    get_appointment as ghl_get_appointment,
    upsert_contact as ghl_upsert_contact,
    create_appointment as ghl_create_appointment,
    extract_appointment,
    get_meet_link,
)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/book-appointment-ghl", response_model=BookAppointmentResponse)
async def book_appointment_ghl(req: BookAppointmentRequest):
    settings = get_settings()
    gmail = settings.gmail

    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return BookAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    calendar_type, tool, policy, env_suffix = cal.key, cal.tool, cal.booking, cal.key

    try:
        now = datetime.now(ZoneInfo("UTC"))

        try:
            start_dt = engine.parse_start_date(req.start_date)
        except ValueError:
            return BookAppointmentResponse(success=False, reason="invalid_start_date", errors="start_date is not a valid ISO 8601 date")

        # Duración tomada desde .env (no del request) como se solicitó
        duration_minutes = int(tool.duration_minutes)
        end_dt = engine.compute_end_date(start_dt, duration_minutes)

        if not engine.is_future(start_dt, now):
            return BookAppointmentResponse(success=False, reason="past_date", errors="The date cannot be in the past")

        weekday = engine.get_weekday_in_tz(start_dt, "America/Bogota") if hasattr(engine, "get_weekday_in_tz") else None
        hour = engine.get_hour_in_tz(start_dt, "America/Bogota") if hasattr(engine, "get_hour_in_tz") else None
        if weekday is None or hour is None:
            # Keep parity with Google endpoint utils
            from ....utils.timezones import get_hour_in_tz, get_weekday_in_tz
            weekday = get_weekday_in_tz(start_dt, "America/Bogota")
            hour = get_hour_in_tz(start_dt, "America/Bogota")
        minute = start_dt.astimezone(ZoneInfo("America/Bogota")).minute
        if not policy.is_valid_business_hour(weekday, hour, minute):
            return BookAppointmentResponse(success=False, reason="invalid_hour", errors="The requested time is outside business hours")

        if not engine.is_valid_email(req.contact_email):
            return BookAppointmentResponse(success=False, reason="invalid_email", errors="The contact email is not valid")

        contact_email = engine.normalize_email(req.contact_email)
        contact_name = engine.format_contact_name(req.contact_name)
        contact_phone = req.contact_phone.strip()
        language = engine.normalize_language(req.language)
        client_tz = (req.iana_timezone or "").strip() or "America/Bogota"

        # Validación de configuración GHL
        if not settings.ghl_token:
            return BookAppointmentResponse(success=False, errors="Missing GHL_TOKEN in environment")
        if not settings.ghl_location_id:
            return BookAppointmentResponse(success=False, errors="Missing GHL_LOCATION_ID in environment")
        if not tool.ghl_calendar_id:
            return BookAppointmentResponse(success=False, errors=f"Missing FA_GHL_CALENDAR_ID_{env_suffix} in environment")

        # Minimum notice and date range of the calendar (same rules as get-available-slots-ghl)
        if start_dt < earliest_start(now, tool):
            return BookAppointmentResponse(success=False, reason="invalid_hour", errors="The requested time does not meet the minimum advance notice")
        if start_dt.astimezone(ZoneInfo("America/Bogota")).date() > (now.astimezone(ZoneInfo("America/Bogota")) + timedelta(days=tool.date_range_days)).date():
            return BookAppointmentResponse(success=False, reason="invalid_hour", errors="The requested date is beyond the booking window")

        # Festivos (misma lista que usa el cálculo de slots)
        local_day = start_dt.astimezone(ZoneInfo("America/Bogota"))
        if engine_slots.is_holiday(local_day.year, local_day.month, local_day.day):
            return BookAppointmentResponse(success=False, reason="invalid_hour", errors="The requested date is a holiday")

        # Disponibilidad real: el inicio debe ser uno de los free-slots de GHL
        try:
            free_slots = await ghl_get_available_slots(
                access_token=settings.ghl_token,
                calendar_id=tool.ghl_calendar_id,
                start_dt=start_dt - timedelta(hours=12),
                end_dt=end_dt + timedelta(hours=12),
                timezone="America/Bogota",
                duration_minutes=duration_minutes,
            )
        except Exception as exc:
            logger.warning("GHL free-slots check failed: %s", exc)
            return BookAppointmentResponse(success=False, reason="creation_failed", errors=f"Could not verify availability in GHL: {exc}")
        free_starts = {datetime.fromisoformat(s.replace("Z", "+00:00")) for s in free_slots}
        if start_dt not in free_starts:
            return BookAppointmentResponse(success=False, reason="slot_taken", errors="That time is no longer available")

        # Existing appointments block their own time plus the pre/post buffers of the calendar.
        busy = await load_busy(
            ghl_list_events, settings, tool,
            start_dt - timedelta(minutes=tool.post_buffer_minutes), end_dt + timedelta(minutes=tool.pre_buffer_minutes),
        )
        if busy and conflicts_with_busy(start_dt, end_dt, busy, tool.pre_buffer_minutes, tool.post_buffer_minutes):
            return BookAppointmentResponse(success=False, reason="slot_taken", errors="That time is no longer available")

        # Pre-chequeo B (no bloqueante): consultar eventos en GHL en el rango exacto.
        # Si hay resultados, igual dejamos que GHL valide en create_appointment,
        # porque free-slots es la fuente de verdad para disponibilidad pública.
        try:
            _ = await ghl_list_events(
                access_token=settings.ghl_token,
                location_id=settings.ghl_location_id,
                calendar_id=tool.ghl_calendar_id,
                start_dt=start_dt,
                end_dt=end_dt,
            )
        except Exception:
            pass

        # Resolver contact_id vía upsert (formato original)
        upsert = await ghl_upsert_contact(
            access_token=settings.ghl_token,
            location_id=settings.ghl_location_id,
            email=contact_email or None,
            phone=contact_phone or None,
            name=contact_name or None,
        )
        contact_obj = upsert.get("contact") or {}
        contact_id = contact_obj.get("id")
        if not contact_id:
            return BookAppointmentResponse(success=False, reason="creation_failed", errors="Failed to resolve/create the contact in GHL")

        # Crear la cita en GHL
        title = f"Family Aims ({policy.EVENT_SUMMARY_TAG}) and {contact_name}"
        try:
            created = await ghl_create_appointment(
                access_token=settings.ghl_token,
                calendar_id=tool.ghl_calendar_id,
                location_id=settings.ghl_location_id,
                contact_id=contact_id,
                start_dt=start_dt,
                end_dt=end_dt,
                title=title,
                appointment_status="confirmed",
                to_notify=False,
            )
        except Exception as exc:
            # Intentamos distinguir si es por conflicto/validación y exponer el mensaje real de GHL
            import httpx
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                err_text = None
                try:
                    payload = exc.response.json()
                    # GHL suele incluir message, details o errors
                    err_text = payload.get("message") or payload.get("error") or str(payload)
                except Exception:
                    err_text = exc.response.text

                if status == 400:
                    # Si viene texto, inclúyelo para diagnosticar (duración/reglas/owner-constraints)
                    msg = "That time is no longer available"
                    if err_text:
                        msg = f"{msg}. GHL: {err_text}"
                    return BookAppointmentResponse(success=False, reason="slot_taken", errors=msg)
                # Otros errores devuelven el status y mensaje bruto
                return BookAppointmentResponse(success=False, reason="creation_failed", errors=f"GHL error {status}: {err_text}")
            # Error no HTTP
            return BookAppointmentResponse(success=False, reason="creation_failed", errors=str(exc))

        appointment = extract_appointment(created)
        event_id = appointment.get("id")
        meet_link = get_meet_link(created)

        # Intentar obtener el enlace del evento en Google Calendar (htmlLink)
        event_link = None
        try:
            if meet_link and tool.google_client_id and tool.google_client_secret and tool.google_refresh_token and tool.calendar_id:
                from ....services.google_calendar import (
                    get_access_token as google_get_access_token,
                    find_synced_google_event,
                )
                gcal_token = await google_get_access_token(tool.google_client_id, tool.google_client_secret, tool.google_refresh_token)
                if gcal_token:
                    synced = await find_synced_google_event(
                        access_token=gcal_token,
                        calendar_id=tool.calendar_id,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        meet_link=meet_link,
                        attempts=4,
                    )
                    if isinstance(synced, dict):
                        event_link = synced.get("htmlLink")
                        # Si GCal ya tiene Meet y GHL aún no, úsalo como fallback
                        if not meet_link:
                            m = synced.get("hangoutLink")
                            if not m:
                                for ep in (synced.get("conferenceData") or {}).get("entryPoints", []) or []:
                                    if ep.get("entryPointType") == "video" and isinstance(ep.get("uri"), str):
                                        m = ep.get("uri")
                                        break
                            if m:
                                meet_link = m
            # Fallback: si no hay meet_link, intenta resolver por ventana temporal y título
            if not event_link and tool.google_client_id and tool.google_client_secret and tool.google_refresh_token and tool.calendar_id:
                from ....services.google_calendar import (
                    get_access_token as google_get_access_token,
                    list_events as gcal_list_events,
                )
                gcal_token = await google_get_access_token(tool.google_client_id, tool.google_client_secret, tool.google_refresh_token)
                if gcal_token:
                    events = await gcal_list_events(
                        access_token=gcal_token,
                        calendar_id=tool.calendar_id,
                        time_min=start_dt - timedelta(minutes=5),
                        time_max=end_dt + timedelta(minutes=5),
                    )
                    # Prefer exact start match; else a single candidate with expected summary pattern
                    candidates = []
                    for ev in events:
                        if ev.get("status") == "cancelled":
                            continue
                        summary = (ev.get("summary") or "").lower()
                        expected_prefix = f"family aims ({policy.EVENT_SUMMARY_TAG.lower()}) and"
                        if expected_prefix in summary and contact_name.lower() in summary:
                            candidates.append(ev)
                    exact_start = []
                    for ev in candidates:
                        ev_start = (ev.get("start") or {}).get("dateTime")
                        if not isinstance(ev_start, str):
                            continue
                        try:
                            ev_dt = datetime.fromisoformat(ev_start.replace("Z", "+00:00"))
                            if ev_dt == start_dt:
                                exact_start.append(ev)
                        except Exception:
                            continue
                    picked = exact_start[0] if len(exact_start) == 1 else (candidates[0] if len(candidates) == 1 else None)
                    if isinstance(picked, dict):
                        event_link = picked.get("htmlLink")
                        # También extrae Meet si GHL aún no lo tiene
                        if not meet_link:
                            m = picked.get("hangoutLink")
                            if not m:
                                for ep in (picked.get("conferenceData") or {}).get("entryPoints", []) or []:
                                    if ep.get("entryPointType") == "video" and isinstance(ep.get("uri"), str):
                                        m = ep.get("uri")
                                        break
                            if m:
                                meet_link = m
        except Exception as exc:
            # Si falla la sincronización/búsqueda, continuamos sin event_link
            logger.warning("Google Calendar sync lookup failed: %s", exc)

        # Poll corto a GHL por si el Meet aparece en address tras la creación
        if not meet_link and event_id:
            try:
                for attempt in range(3):  # ~1+2+4s = 7s máx
                    await asyncio.sleep(1 << attempt)
                    refreshed = await ghl_get_appointment(settings.ghl_token, event_id)
                    m = get_meet_link(refreshed)
                    if m:
                        meet_link = m
                        break
            except Exception:
                pass

        if not event_id:
            return BookAppointmentResponse(success=False, reason="creation_failed", errors="Failed to create the appointment. The booking was not completed")

        notify_error = await notify_booking(
            settings, calendar=calendar_type, contact_name=contact_name, contact_email=contact_email,
            contact_phone=contact_phone, start_dt=start_dt, timezone=client_tz, event_link=event_link, meet_link=meet_link,
        )

        if policy.EMAIL_TEMPLATE_PREFIX is None:  # this calendar sends no confirmation email
            return BookAppointmentResponse(success=True, event_id=event_id, event_link=event_link, meet_link=meet_link, errors=notify_error)

        # Enviar correo igual que en Google Calendar
        try:
            if not (gmail.google_client_id and gmail.google_client_secret and gmail.google_refresh_token and gmail.sender_email):
                raise RuntimeError("Missing Gmail credentials (FA_GOOGLE_CLIENT_ID_GMAIL / FA_GMAIL_SENDER_EMAIL, etc.) in environment")

            from ....services.google_calendar import get_access_token as google_get_access_token
            gmail_token = await google_get_access_token(gmail.google_client_id, gmail.google_client_secret, gmail.google_refresh_token)
            local_start = start_dt.astimezone(ZoneInfo(client_tz))
            html_body = render_email_template(
                f"{policy.EMAIL_TEMPLATE_PREFIX}_{language.lower()}",
                contact_name=contact_name,
                agent_name=policy.AGENT_NAME,
                booking_date=date_formatting.format_full_date(local_start, language),
                booking_time=date_formatting.format_booking_time(local_start, language),
                meet_link=meet_link or "",
                event_link=event_link or "",
            )
            await send_email(gmail_token, gmail.sender_email, contact_email, engine.EMAIL_SUBJECTS[language], html_body)
        except Exception as email_error:
            return BookAppointmentResponse(
                success=True, event_id=event_id, event_link=event_link, meet_link=meet_link,
                errors=join_errors(f"The appointment was created but email notification failed: {email_error}", notify_error),
            )

        return BookAppointmentResponse(success=True, event_id=event_id, event_link=event_link, meet_link=meet_link, errors=notify_error)

    except Exception as e:
        return BookAppointmentResponse(success=False, errors=str(e))
