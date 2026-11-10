"""GoHighLevel scheduling tools shared by every company.

``build_ghl_scheduling_router`` returns a FastAPI router with the five tools an agent uses to
schedule appointments in a GHL calendar. A company plugin only supplies a few hooks (how to find
its calendars and rules, how to notify its team); the logic lives here once::

    router = build_ghl_scheduling_router(GhlSchedulingHooks(prefix="BN", get_settings=..., ...))

Tools (all take ``calendar_type``): ``get-available-slots-ghl``, ``book-appointment-ghl``,
``find-appointment-ghl``, ``edit-appointment-ghl``, ``cancel-appointment-ghl``.

GHL computes the free slots with the settings of its calendar. These tools only *discard* the slots
that break the company's parameters (see ``agent_backend.slot_filters``) and the opening hours of the
calendar, and validate the same rules again when booking or rescheduling.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter

from agent_backend import ghl_calendar as ghl
from agent_backend.ghl_schedule import Schedule, resolve_schedule
from agent_backend.scheduling_schemas import (
    AppointmentInfo,
    BookAppointmentRequest,
    BookAppointmentResponse,
    CancelAppointmentRequest,
    CancelAppointmentResponse,
    EditAppointmentRequest,
    EditAppointmentResponse,
    FindAppointmentRequest,
    FindAppointmentResponse,
    Slot,
    SlotsRequest,
    SlotsResponse,
)
from agent_backend.slot_filters import Busy, conflicts_with_busy, parse_busy, thin_by_interval

logger = logging.getLogger(__name__)

__all__ = ["GHL_MAX_RANGE_DAYS", "GhlSchedulingHooks", "build_ghl_scheduling_router", "load_busy"]

# GET /calendars/{id}/free-slots rejects ranges longer than this (GoHighLevel documentation).
GHL_MAX_RANGE_DAYS = 31


@dataclass
class GhlSchedulingHooks:
    """What a company plugin supplies to the shared scheduling tools.

    Attributes:
        prefix: Company variable prefix, used in error messages (``"BN"``).
        get_settings: Returns the plugin settings: ``ghl_token``, ``ghl_location_id`` and anything the hooks need.
        resolve_calendar: ``(settings, calendar_type)`` -> calendar context or None. The context has ``key``,
            ``tool`` (``CalendarSettings``), ``booking`` (business-hour and title rules) and ``hours``
            (``window(weekday, day)``, ``is_lunch(start, end)``, ``is_holiday(year, month, day)``).
        unknown_calendar_message: ``(settings, calendar_type)`` -> error text for an unknown calendar.
        default_earliest: ``now`` -> first moment a slot may start when no minimum notice is configured.
        notify_booking: Optional ``async (settings, policy, *, contact_name, contact_phone, start_dt, timezone)``
            that tells the team about a booking; returns an error text or None.
        format_start: ``datetime`` -> text shown to the user for an appointment time.
        business_tz: Timezone the opening hours are written in.
    """

    prefix: str
    get_settings: Callable[[], Any]
    resolve_calendar: Callable[[Any, str | None], Any]
    unknown_calendar_message: Callable[[Any, str | None], str]
    default_earliest: Callable[[datetime], datetime]
    notify_booking: Callable[..., Awaitable[str | None]] | None = None
    format_start: Callable[[datetime], str] = lambda dt: dt.strftime("%Y-%m-%d %H:%M")
    business_tz: str = "America/Bogota"


async def load_busy(
    list_events: Callable[..., Awaitable[Any]],
    settings: Any,
    tool: Any,
    start: datetime,
    end: datetime,
    *,
    exclude_event_id: str | None = None,
) -> list[Busy] | None:
    """Reads the existing appointments of a calendar as busy intervals.

    Args:
        list_events: ``ghl_calendar.list_events`` (passed in so callers can substitute it).
        settings: Plugin settings (token and location).
        tool: Calendar settings (GHL calendar id).
        start: Start of the range to read.
        end: End of the range to read.
        exclude_event_id: An event to ignore, e.g. the one being rescheduled.

    Returns:
        The busy intervals, or None when GHL could not be queried (callers then rely on GHL's own
        validation instead of failing the request).
    """
    try:
        data = await list_events(
            access_token=settings.ghl_token,
            location_id=settings.ghl_location_id,
            calendar_id=tool.ghl_calendar_id,
            start_dt=start,
            end_dt=end,
        )
    except Exception as exc:
        logger.warning("GHL list_events failed; buffers are not checked: %s", exc)
        return None
    events = data.get("events", []) if isinstance(data, dict) else []
    return parse_busy(e for e in events if not (exclude_event_id and e.get("id") == exclude_event_id))


def _weekday(moment: datetime) -> int:
    """Weekday with the project convention: 0 = Sunday ... 6 = Saturday."""
    return moment.isoweekday() % 7


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def build_ghl_scheduling_router(hooks: GhlSchedulingHooks) -> APIRouter:
    """Builds the router with the five GHL scheduling tools.

    Args:
        hooks: The company's hooks.

    Returns:
        A router; mount it in the plugin's router.
    """
    router = APIRouter()
    tz = ZoneInfo(hooks.business_tz)

    def resolve(calendar_type: str | None) -> tuple[Any, Any, str | None]:
        """Finds the calendar and checks the configuration every GHL call needs."""
        settings = hooks.get_settings()
        cal = hooks.resolve_calendar(settings, calendar_type)
        if cal is None:
            return settings, None, hooks.unknown_calendar_message(settings, calendar_type)
        if not settings.ghl_token:
            return settings, cal, "Missing GHL_TOKEN in environment"
        if not settings.ghl_location_id:
            return settings, cal, "Missing GHL_LOCATION_ID in environment"
        if not cal.tool.ghl_calendar_id:
            return settings, cal, f"Missing {hooks.prefix}_GHL_CALENDAR_ID_{cal.key} in environment"
        return settings, cal, None

    def earliest_start(now: datetime, schedule: Schedule) -> datetime:
        if schedule.min_notice_minutes is not None:
            return now + timedelta(minutes=schedule.min_notice_minutes)
        return hooks.default_earliest(now)

    def in_hours(cal: Any, start: datetime, end: datetime) -> bool:
        local_start, local_end = start.astimezone(tz), end.astimezone(tz)
        if cal.hours.is_holiday(local_start.year, local_start.month, local_start.day):
            return False
        window = cal.hours.window(_weekday(local_start), local_start.day)
        if not window:
            return False
        h1, m1, h2, m2 = window
        start_min = local_start.hour * 60 + local_start.minute
        end_min = local_end.hour * 60 + local_end.minute
        if start_min < h1 * 60 + m1 or end_min > h2 * 60 + m2:
            return False
        return not cal.hours.is_lunch(local_start, local_end)

    def duration_to_send(cal: Any, schedule: Schedule) -> int | None:
        # When the duration comes from GHL itself there is nothing to ask for: GHL uses its default.
        return (
            None
            if "duration_minutes" in cal.tool.read_from_ghl and "duration_minutes" in schedule.from_ghl
            else schedule.duration_minutes
        )

    # ------------------------------------------------------------------ slots
    @router.post("/get-available-slots-ghl", response_model=SlotsResponse)
    async def get_available_slots_ghl(req: SlotsRequest):
        user_tz = (req.iana_timezone or "").strip() or hooks.business_tz

        def fail(message: str) -> SlotsResponse:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=message)

        try:
            settings, cal, error = resolve(req.calendar_type)
            if error:
                return fail(error)
            tool = cal.tool
            schedule = await resolve_schedule(tool, settings.ghl_token)
            if "date_range_days" not in schedule.from_ghl and schedule.date_range_days > GHL_MAX_RANGE_DAYS:
                return fail(
                    f"{hooks.prefix}_DATE_RANGE_DAYS_{cal.key} is {schedule.date_range_days}; GoHighLevel free-slots accepts at most {GHL_MAX_RANGE_DAYS} days"
                )

            now = datetime.now(UTC)
            earliest = earliest_start(now, schedule)
            end_date = earliest + timedelta(days=min(schedule.date_range_days, GHL_MAX_RANGE_DAYS))
            duration = timedelta(minutes=schedule.duration_minutes)

            free = await ghl.get_available_slots(
                settings.ghl_token,
                tool.ghl_calendar_id,
                earliest,
                end_date,
                hooks.business_tz,
                duration_minutes=duration_to_send(cal, schedule),
            )
            starts = [datetime.fromisoformat(iso.replace("Z", "+00:00")) for iso in free]
            starts = [s for s in starts if s >= earliest and in_hours(cal, s, s + duration)]

            if schedule.pre_buffer_minutes or schedule.post_buffer_minutes:
                busy = await load_busy(
                    ghl.list_events,
                    settings,
                    tool,
                    earliest - timedelta(days=1),
                    end_date + timedelta(days=1),
                )
                if busy:
                    starts = [
                        s
                        for s in starts
                        if not conflicts_with_busy(
                            s, s + duration, busy, schedule.pre_buffer_minutes, schedule.post_buffer_minutes
                        )
                    ]

            slots = []
            for start in thin_by_interval(starts, schedule.interval_minutes):
                end = start + duration
                slots.append(
                    Slot(
                        start_co=start.astimezone(tz).isoformat(),
                        end_co=end.astimezone(tz).isoformat(),
                        start_local=start.astimezone(ZoneInfo(user_tz)).isoformat(),
                        end_local=end.astimezone(ZoneInfo(user_tz)).isoformat(),
                    )
                )
            return SlotsResponse(success=True, iana_timezone=user_tz, available_slots=slots, errors=None)
        except Exception as exc:
            return fail(str(exc))

    # ------------------------------------------------------------------- book
    @router.post("/book-appointment-ghl", response_model=BookAppointmentResponse)
    async def book_appointment_ghl(req: BookAppointmentRequest):
        def fail(message: str, reason: str | None = None) -> BookAppointmentResponse:
            return BookAppointmentResponse(success=False, reason=reason, errors=message)

        try:
            settings, cal, error = resolve(req.calendar_type)
            if error:
                return fail(error)
            policy, tool = cal.booking, cal.tool
            schedule = await resolve_schedule(tool, settings.ghl_token)
            try:
                start_dt = policy.parse_start_date(req.start_date)
            except ValueError:
                return fail("start_date is not a valid ISO 8601 date", "invalid_start_date")
            duration = timedelta(minutes=schedule.duration_minutes)
            end_dt = start_dt + duration
            now = datetime.now(UTC)

            if start_dt <= now:
                return fail("The date cannot be in the past", "past_date")
            local = start_dt.astimezone(tz)
            if not policy.is_valid_business_hour(_weekday(local), local.hour, local.minute):
                return fail("The requested time is outside business hours", "invalid_hour")

            contact_name = policy.format_contact_name(req.contact_name)
            contact_email = (req.contact_email or "").strip().lower()
            contact_phone = (req.contact_phone or "").strip()
            if not contact_email and not contact_phone:
                return fail("contact_email or contact_phone is required", "invalid_contact")

            if start_dt < earliest_start(now, schedule):
                return fail("The requested time does not meet the minimum advance notice", "invalid_hour")
            if local.date() > (now.astimezone(tz) + timedelta(days=schedule.date_range_days)).date():
                return fail("The requested date is beyond the booking window", "invalid_hour")
            if cal.hours.is_holiday(local.year, local.month, local.day):
                return fail("The requested date is a holiday", "invalid_hour")

            # GHL decides what is free: the start must be one of its free slots.
            try:
                free = await ghl.get_available_slots(
                    settings.ghl_token,
                    tool.ghl_calendar_id,
                    start_dt - timedelta(hours=12),
                    end_dt + timedelta(hours=12),
                    hooks.business_tz,
                    duration_minutes=duration_to_send(cal, schedule),
                )
            except Exception as exc:
                logger.warning("GHL free-slots check failed: %s", exc)
                return fail(f"Could not verify availability in GHL: {exc}", "creation_failed")
            if start_dt not in {datetime.fromisoformat(s.replace("Z", "+00:00")) for s in free}:
                return fail("That time is no longer available", "slot_taken")

            # Existing appointments block their own time plus the pre/post buffers.
            busy = await load_busy(
                ghl.list_events,
                settings,
                tool,
                start_dt - timedelta(minutes=schedule.post_buffer_minutes),
                end_dt + timedelta(minutes=schedule.pre_buffer_minutes),
            )
            if busy and conflicts_with_busy(
                start_dt, end_dt, busy, schedule.pre_buffer_minutes, schedule.post_buffer_minutes
            ):
                return fail("That time is no longer available", "slot_taken")

            upsert = await ghl.upsert_contact(
                settings.ghl_token,
                settings.ghl_location_id,
                email=contact_email or None,
                phone=contact_phone or None,
                name=contact_name or None,
            )
            contact_id = (upsert.get("contact") or {}).get("id")
            if not contact_id:
                return fail("Failed to resolve/create the contact in GHL", "creation_failed")

            title = f"{policy.EVENT_TITLE_PREFIX}{policy.TITLE_SEPARATOR}{contact_name}{policy.TITLE_SEPARATOR}{contact_phone}"
            try:
                created = await ghl.create_appointment(
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
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                try:
                    detail = exc.response.json().get("message")
                except Exception:
                    detail = exc.response.text if exc.response is not None else None
                if status == 400:
                    return fail(
                        "That time is no longer available" + (f". GHL: {detail}" if detail else ""),
                        "slot_taken",
                    )
                return fail(f"GHL error {status}: {detail}", "creation_failed")

            appointment = ghl.extract_appointment(created)
            event_id = appointment.get("id")
            if not event_id:
                return fail(
                    "Failed to create the appointment. The booking was not completed", "creation_failed"
                )
            meet_link = ghl.get_meet_link(created)

            notify_error = None
            if hooks.notify_booking:
                notify_error = await hooks.notify_booking(
                    settings,
                    policy,
                    contact_name=contact_name,
                    contact_phone=contact_phone,
                    start_dt=start_dt,
                    timezone=(req.iana_timezone or hooks.business_tz).strip(),
                )
            return BookAppointmentResponse(
                success=True, event_id=event_id, event_link=None, meet_link=meet_link, errors=notify_error
            )
        except Exception as exc:
            return fail(str(exc))

    # ------------------------------------------------------------------- find
    @router.post("/find-appointment-ghl", response_model=FindAppointmentResponse)
    async def find_appointment_ghl(req: FindAppointmentRequest):
        def fail(message: str) -> FindAppointmentResponse:
            return FindAppointmentResponse(success=False, errors=message)

        try:
            settings, cal, error = resolve(req.calendar_type)
            if error:
                return fail(error)
            name = (req.contact_name or "").strip()
            phone = (req.contact_phone or "").strip()
            email = (req.contact_email or "").strip().lower()
            if not (name or phone or email):
                return fail("You must provide at least a name, phone, or email to search.")
            if email and ("@" not in email or "." not in email.split("@")[-1]):
                return fail(f"The email '{email}' is not in a valid format.")
            client_tz = ZoneInfo((req.iana_timezone or hooks.business_tz).strip())

            now = datetime.now(UTC)
            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            contact_id = None
            if email or phone:
                upsert = await ghl.upsert_contact(
                    settings.ghl_token,
                    settings.ghl_location_id,
                    email=email or None,
                    phone=phone or None,
                    name=name or None,
                )
                contact_id = (upsert.get("contact") or {}).get("id")
            data = await ghl.list_events(
                access_token=settings.ghl_token,
                location_id=settings.ghl_location_id,
                calendar_id=cal.tool.ghl_calendar_id,
                start_dt=time_min,
                end_dt=time_min + timedelta(days=36),
            )
            keywords = [w for w in name.lower().split() if len(w) > 2]
            found = []
            for event in data.get("events", []) if isinstance(data, dict) else []:
                if str(event.get("appointmentStatus", event.get("status", ""))).lower() == "cancelled":
                    continue
                title = event.get("title") or ""
                lowered = title.lower()
                same_contact = (
                    bool(contact_id) and (event.get("contactId") or event.get("contact_id")) == contact_id
                )
                by_title = (
                    (bool(keywords) and all(k in lowered for k in keywords))
                    or (bool(email) and email in lowered)
                    or (len(_digits(phone)) >= 7 and _digits(phone) in _digits(title))
                )
                raw_start = event.get("startTime") or event.get("start_time")
                if not (same_contact or by_title) or not raw_start:
                    continue
                start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00")).astimezone(client_tz)
                found.append(
                    AppointmentInfo(
                        event_id=event.get("id", ""), summary=title, start_time=hooks.format_start(start)
                    )
                )
            if found:
                return FindAppointmentResponse(success=True, appointments=found)
            return fail(f"No appointments found for {name or email or phone} in the next month.")
        except Exception as exc:
            return fail(str(exc))

    # ------------------------------------------------------------------- edit
    @router.post("/edit-appointment-ghl", response_model=EditAppointmentResponse)
    async def edit_appointment_ghl(req: EditAppointmentRequest):
        def fail(message: str) -> EditAppointmentResponse:
            return EditAppointmentResponse(success=False, errors=message)

        try:
            settings, cal, error = resolve(req.calendar_type)
            if error:
                return fail(error)
            tool, policy = cal.tool, cal.booking
            schedule = await resolve_schedule(tool, settings.ghl_token)
            now = datetime.now(UTC)
            start_dt = end_dt = None
            applied_duration = req.new_duration

            if req.new_start_date:
                try:
                    start_dt = policy.parse_start_date(req.new_start_date)
                except ValueError:
                    return fail("new_start_date is not a valid ISO 8601 date")
                if start_dt <= now:
                    return fail("The new date cannot be in the past")
                local = start_dt.astimezone(tz)
                if not policy.is_valid_business_hour(_weekday(local), local.hour, local.minute):
                    return fail("The requested new time is outside business hours")
                if start_dt < earliest_start(now, schedule):
                    return fail("The requested new time does not meet the minimum advance notice")
                minutes = (
                    policy.parse_duration_minutes(req.new_duration, schedule.duration_minutes)
                    if req.new_duration
                    else schedule.duration_minutes
                )
                applied_duration = str(minutes)
                end_dt = start_dt + timedelta(minutes=minutes)
                busy = await load_busy(
                    ghl.list_events,
                    settings,
                    tool,
                    start_dt - timedelta(minutes=schedule.post_buffer_minutes),
                    end_dt + timedelta(minutes=schedule.pre_buffer_minutes),
                    exclude_event_id=req.event_id,
                )
                if busy and conflicts_with_busy(
                    start_dt, end_dt, busy, schedule.pre_buffer_minutes, schedule.post_buffer_minutes
                ):
                    return fail("The requested new time is already taken by another appointment.")

            updated = await ghl.update_appointment(
                access_token=settings.ghl_token,
                appointment_id=req.event_id,
                start_dt=start_dt,
                end_dt=end_dt,
            )
            if not isinstance(updated, dict):
                return fail("Could not update the event. Please verify the event_id.")

            message, shown = "The appointment has been successfully updated.", None
            if start_dt:
                shown = hooks.format_start(
                    start_dt.astimezone(ZoneInfo((req.iana_timezone or hooks.business_tz).strip()))
                )
                message = f"The appointment has been rescheduled to {shown}."
            return EditAppointmentResponse(
                success=True, message=message, new_start_time=shown, new_duration=applied_duration
            )
        except Exception as exc:
            return fail(str(exc))

    # ----------------------------------------------------------------- cancel
    @router.post("/cancel-appointment-ghl", response_model=CancelAppointmentResponse)
    async def cancel_appointment_ghl(req: CancelAppointmentRequest):
        try:
            settings, cal, error = resolve(req.calendar_type)
            if error:
                return CancelAppointmentResponse(success=False, errors=error)
            if await ghl.delete_appointment(settings.ghl_token, req.event_id):
                return CancelAppointmentResponse(
                    success=True, message="The appointment has been successfully canceled."
                )
            return CancelAppointmentResponse(
                success=False, errors="Could not delete the event. Please verify the event_id."
            )
        except Exception as exc:
            return CancelAppointmentResponse(success=False, errors=str(exc))

    return router
