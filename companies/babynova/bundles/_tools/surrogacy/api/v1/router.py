from fastapi import APIRouter

from agent_backend.builtin_tools.endpoints import health
from agent_backend.calendars_router import build_calendars_router

from ...core import config
from .endpoints import (
    book_appointment_google,
    cancel_appointment_google,
    check_adres,
    check_documentation,
    edit_appointment_google,
    find_appointment_google,
    get_available_slots_google,
    ghl_scheduling,
    surrogate_classification,
)

api_router = APIRouter()
api_router.include_router(get_available_slots_google.router, tags=["get_available_slots_google"])
api_router.include_router(book_appointment_google.router, tags=["book_appointment_google"])
api_router.include_router(find_appointment_google.router, tags=["find_appointment_google"])
api_router.include_router(cancel_appointment_google.router, tags=["cancel_appointment_google"])
api_router.include_router(edit_appointment_google.router, tags=["edit_appointment_google"])
api_router.include_router(surrogate_classification.router, tags=["surrogate_classification"])
api_router.include_router(check_documentation.router, tags=["check_documentation"])
api_router.include_router(check_adres.router, tags=["check_adres"])
api_router.include_router(build_calendars_router(lambda: config.get_settings()), tags=["calendars"])
api_router.include_router(ghl_scheduling.router, tags=["ghl_scheduling"])
api_router.include_router(health.router, tags=["health"])

# Para agregar un endpoint nuevo:
#   1. crear tools.surrogacy/api/v1/endpoints/mi_endpoint.py con su APIRouter
#   2. importarlo arriba y aÃ±adir: api_router.include_router(mi_endpoint.router, tags=["mi_endpoint"])
