"""Built-in tool: sends an approved WhatsApp template to a GoHighLevel contact."""

from agent_backend.builtin_tools.schemas.whatsapp import GhlSendWhatsappResponse, GhlSendWhatsappTemplate
from agent_backend.builtin_tools.services.ghl_whatsapp import send_whatsapp_template_service


async def send_whatsapp_template(req: GhlSendWhatsappTemplate):
    """send_whatsapp_template.

    Herramienta para enviar una plantilla de WhatsApp aprobada a un contacto de GoHighLevel.

    - La plantilla se identifica por nombre e idioma; las variables del cuerpo van en `body_variables`.
    - Sirve para escribirle a un contacto que no ha escrito en las últimas 24 horas.
    - Devuelve `message_id` y `conversation_id`; si falla, `success` es false y `errors` dice por qué.
    """
    result = await send_whatsapp_template_service(
        contact_id=req.contact_id,
        template_name=req.template_name,
        language=req.language,
        location_id=req.location_id,
        body_variables=req.body_variables,
        header_variables=req.header_variables,
        category=req.category,
        from_number_id=req.from_number_id,
        to_number=req.to_number,
    )
    return GhlSendWhatsappResponse(**result)
