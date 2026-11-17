"""Built-in tool: adds tags to a GoHighLevel contact."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.ghl import GhlAddTags, GhlAddTagsResponse
from agent_backend.builtin_tools.services.ghl_tags import add_tags_service

router = APIRouter()


@router.post("/add_tags", response_model=GhlAddTagsResponse)
async def add_tags(req: GhlAddTags):
    """add_tags.

    Herramienta para agregar etiquetas (tags) a un contacto de GoHighLevel.

    - GHL las pasa a minúsculas, crea las que la ubicación aún no tiene e ignora las que el contacto ya tiene.
    - Devuelve todas las etiquetas del contacto (`tags`) y las que se agregaron ahora (`tags_added`).
    - Si falla, `success` es false y `errors` dice por qué.
    """
    result = await add_tags_service(tags=req.tags, contact_id=req.contact_id, location_id=req.location_id)
    return GhlAddTagsResponse(**result)
