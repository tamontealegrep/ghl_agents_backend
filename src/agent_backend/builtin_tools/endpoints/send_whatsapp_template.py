"""Built-in tool: sends an approved WhatsApp template to a GoHighLevel contact."""

from fastapi import Request

from agent_backend.builtin_tools.schemas.whatsapp import GhlSendWhatsappResponse, GhlSendWhatsappTemplate
from agent_backend.builtin_tools.services.ghl_whatsapp import send_whatsapp_template_service
from agent_backend.builtin_tools.services.whatsapp_templates import company_templates_file


async def send_whatsapp_template(req: GhlSendWhatsappTemplate, request: Request):
    """send_whatsapp_template.

    Herramienta para enviar una plantilla de WhatsApp aprobada a un contacto de GoHighLevel.

    - La plantilla se identifica por nombre e idioma; las variables del cuerpo van en `body_variables`.
    - Sirve para escribirle a un contacto que no ha escrito en las últimas 24 horas.
    - Devuelve `message_id` y `conversation_id`; si falla, `success` es false y `errors` dice por qué.
    - El chat del contacto muestra el texto de la plantilla que está en el `shared/whatsapp_templates.yaml` de la compañía.
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
        templates_file=company_templates_file(getattr(request.app.state, "settings", None)),
    )
    return GhlSendWhatsappResponse(**result)
