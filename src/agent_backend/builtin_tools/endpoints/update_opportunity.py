"""Built-in tool: updates the data of a GoHighLevel opportunity."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.ghl import GhlUpdateOpportunity, GhlUpdateOpportunityResponse
from agent_backend.builtin_tools.services.ghl_opportunities import OPPORTUNITY_FIELDS, update_opportunity_service

router = APIRouter()


@router.post("/update_opportunity", response_model=GhlUpdateOpportunityResponse)
async def update_opportunity(req: GhlUpdateOpportunity):
    """update_opportunity.

    Herramienta para actualizar los datos de una oportunidad de GoHighLevel: nombre, pipeline, etapa, estado
    (open, won, lost, abandoned), valor, previsión de cierre, asignación, motivo de pérdida y campos personalizados.

    - Solo se envía lo que se da; el resto de la oportunidad no cambia.
    - Devuelve el estado, el pipeline y la etapa en que quedó.
    """
    result = await update_opportunity_service(
        opportunity_id=req.opportunity_id,
        location_id=req.location_id,
        fields={name: getattr(req, name) for name in OPPORTUNITY_FIELDS},
        custom_fields=req.custom_fields,
    )
    return GhlUpdateOpportunityResponse(**result)
