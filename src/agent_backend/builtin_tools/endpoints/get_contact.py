"""Built-in tool: reads the data of a GoHighLevel contact."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.ghl import GhlGetContact, GhlGetContactResponse
from agent_backend.builtin_tools.services.ghl_contacts import get_contact_service

router = APIRouter()


@router.post("/get_contact", response_model=GhlGetContactResponse)
async def get_contact(req: GhlGetContact):
    """get_contact.

    Herramienta para leer los datos de un contacto de GoHighLevel: los campos normales (nombre, correo, teléfono,
    dirección, país...), las etiquetas y los campos personalizados con valor.

    - Solo lee: no cambia nada del contacto.
    - Los campos personalizados vienen por nombre cuando se puede leer su definición en la ubicación.
    """
    result = await get_contact_service(contact_id=req.contact_id, location_id=req.location_id)
    return GhlGetContactResponse(**result)
