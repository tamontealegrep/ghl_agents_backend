from fastapi import APIRouter
from agent_backend.builtin_tools.schemas.ghl import GhlCustomFieldUpdate, GhlCustomUpdateResponse
from agent_backend.builtin_tools.services.ghl import update_custom_field_service

router = APIRouter()

@router.post("/update_custom_field", response_model=GhlCustomUpdateResponse)
async def update_custom_field(req: GhlCustomFieldUpdate):
    """update_custom_field.

    Herramienta para actualizar campos o valores personalizados en GoHighLevel.

    - Si se provee `contact_id`: Actualiza un Custom Field del contacto (ej: idioma).
    - Si NO se provee `contact_id` pero sí `location_id`: Actualiza un Custom Value global.

    Permite usar nombres legibles (ej: 'language') en lugar de IDs técnicos si se provee el `location_id`.
    """
    result = await update_custom_field_service(
        name=req.name,
        value=req.value,
        contact_id=req.contact_id,
        location_id=req.location_id
    )
    return GhlCustomUpdateResponse(**result)
