"""Request and response models of the scheduling tools; shared with every company (see agent_backend)."""

from agent_backend.scheduling_schemas import (  # noqa: F401
    AppointmentInfo,
    BookAppointmentRequest,
    BookAppointmentResponse,
    CancelAppointmentRequest,
    CancelAppointmentResponse,
    EditAppointmentRequest,
    EditAppointmentResponse,
    FindAppointmentRequest,
    FindAppointmentResponse,
)
