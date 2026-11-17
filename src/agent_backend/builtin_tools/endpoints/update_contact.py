"""Built-in tool: updates the data of a GoHighLevel contact."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.ghl import GhlUpdateContact, GhlUpdateContactResponse
from agent_backend.builtin_tools.services.ghl_contacts import CONTACT_FIELDS, update_contact_service

router = APIRouter()


@router.post("/update_contact", response_model=GhlUpdateContactResponse)
async def update_contact(req: GhlUpdateContact):
    """update_contact.

    Herramienta para actualizar los datos de un contacto de GoHighLevel (nombre, correo, teléfono, dirección,
    fecha de nacimiento, país, asignación, no molestar) y varios campos personalizados en una sola llamada.

    - Solo se envía lo que se da; el resto del contacto no cambia.
    - No cambia las etiquetas: para eso están `add_tags` y `remove_tags`.
    - Los campos personalizados pueden darse por nombre si se envía `location_id`.
    """
    result = await update_contact_service(
        contact_id=req.contact_id,
        location_id=req.location_id,
        fields={name: getattr(req, name) for name in CONTACT_FIELDS},
        custom_fields=req.custom_fields,
    )
    return GhlUpdateContactResponse(**result)
