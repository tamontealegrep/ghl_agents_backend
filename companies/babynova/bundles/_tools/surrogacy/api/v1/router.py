from fastapi import APIRouter

from .endpoints import (
    book_appointment,
    calendars,
    ghl_scheduling,
    cancel_appointment,
    edit_appointment,
    find_appointment,
    check_documentation,
    health,
    get_available_slots,
    surrogate_classification,
)
from agent_backend.builtin_tools.endpoints import calculate_bmi, time_now

api_router = APIRouter()
api_router.include_router(get_available_slots.router, tags=["get_available_slots"])
api_router.include_router(book_appointment.router, tags=["book_appointment"])
api_router.include_router(find_appointment.router, tags=["find_appointment"])
api_router.include_router(cancel_appointment.router, tags=["cancel_appointment"])
api_router.include_router(edit_appointment.router, tags=["edit_appointment"])
api_router.include_router(surrogate_classification.router, tags=["surrogate_classification"])
api_router.include_router(check_documentation.router, tags=["check_documentation"])
api_router.include_router(calendars.router, tags=["calendars"])
api_router.include_router(ghl_scheduling.router, tags=["ghl_scheduling"])
api_router.include_router(health.router, tags=["health"])

# Para agregar un endpoint nuevo:
#   1. crear tools.surrogacy/api/v1/endpoints/mi_endpoint.py con su APIRouter
#   2. importarlo arriba y aÃ±adir: api_router.include_router(mi_endpoint.router, tags=["mi_endpoint"])

