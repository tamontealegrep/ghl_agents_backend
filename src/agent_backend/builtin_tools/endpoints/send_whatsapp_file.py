"""Built-in tool: sends a file to a GoHighLevel contact on WhatsApp."""

from agent_backend.builtin_tools.schemas.whatsapp import GhlSendWhatsappFile, GhlSendWhatsappResponse
from agent_backend.builtin_tools.services.ghl_whatsapp import send_whatsapp_file_service


async def send_whatsapp_file(req: GhlSendWhatsappFile):
    """send_whatsapp_file.

    Herramienta para enviar un archivo (imagen, video, audio o documento) a un contacto por WhatsApp.

    - El archivo se envía por URL pública; el tipo se deduce de la extensión si no se indica.
    - Devuelve `message_id` y `conversation_id`; si falla, `success` es false y `errors` dice por qué.
    """
    result = await send_whatsapp_file_service(
        contact_id=req.contact_id,
        file_url=req.file_url,
        file_type=req.file_type,
        file_name=req.file_name,
        message=req.message,
        location_id=req.location_id,
        from_number=req.from_number,
    )
    return GhlSendWhatsappResponse(**result)
