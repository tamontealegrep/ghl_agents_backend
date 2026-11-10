from fastapi import APIRouter

from .endpoints import (
    book_appointment_google,
    cancel_appointment_google,
    edit_appointment_google,
    find_appointment_google,
    get_available_slots_google,
    get_available_slots_ghl,
    book_appointment_ghl,
    resolve_event_link_ghl,
    cancel_appointment_ghl,
    edit_appointment_ghl,
    find_appointment_ghl,
    health,
    check_visa,
    calendars,
)
# No cross-app aliasing: utils endpoints live under /tools/v1 exclusively.

api_router = APIRouter()
api_router.include_router(get_available_slots_ghl.router, tags=["get_available_slots_ghl"])
api_router.include_router(book_appointment_ghl.router, tags=["book_appointment_ghl"])
api_router.include_router(resolve_event_link_ghl.router, tags=["resolve_event_link_ghl"])
api_router.include_router(find_appointment_ghl.router, tags=["find_appointment_ghl"])
api_router.include_router(cancel_appointment_ghl.router, tags=["cancel_appointment_ghl"])
api_router.include_router(edit_appointment_ghl.router, tags=["edit_appointment_ghl"])
api_router.include_router(book_appointment_google.router, tags=["book_appointment_google"])
api_router.include_router(cancel_appointment_google.router, tags=["cancel_appointment_google"])
api_router.include_router(edit_appointment_google.router, tags=["edit_appointment_google"])
api_router.include_router(find_appointment_google.router, tags=["find_appointment_google"])
api_router.include_router(get_available_slots_google.router, tags=["get_available_slots_google"])
api_router.include_router(calendars.router, tags=["calendars"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(check_visa.router, tags=["visa_check"])

# Para agregar un endpoint nuevo:
#   1. crear tools.family_aims/api/v1/endpoints/mi_endpoint.py con su APIRouter
#   2. importarlo arriba y añadir: api_router.include_router(mi_endpoint.router, tags=["mi_endpoint"])

## No snake_case aliases — only kebab-case endpoints defined in each module's router.
