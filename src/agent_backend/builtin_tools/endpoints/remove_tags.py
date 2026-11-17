"""Built-in tool: removes tags from a GoHighLevel contact."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.ghl import GhlAddTags, GhlRemoveTagsResponse
from agent_backend.builtin_tools.services.ghl_tags import remove_tags_service

router = APIRouter()


@router.post("/remove_tags", response_model=GhlRemoveTagsResponse)
async def remove_tags(req: GhlAddTags):
    """remove_tags.

    Herramienta para quitar etiquetas (tags) de un contacto de GoHighLevel.

    - Solo quita las que se nombran; las demás etiquetas del contacto se conservan.
    - GHL ignora las que el contacto no tiene, así que pedir una que no está no es un error.
    - Devuelve las etiquetas que le quedan (`tags`) y las que se quitaron ahora (`tags_removed`).
    """
    result = await remove_tags_service(tags=req.tags, contact_id=req.contact_id, location_id=req.location_id)
    return GhlRemoveTagsResponse(**result)
