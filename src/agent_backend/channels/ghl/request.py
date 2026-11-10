import warnings
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

try:
    # Silence Pydantic alias warnings for our validated payload model
    from pydantic._internal._generate_schema import UnsupportedFieldAttributeWarning
    warnings.filterwarnings("ignore", category=UnsupportedFieldAttributeWarning)
except Exception:
    pass

from agent_backend.channels.ghl.client import GHL_INBOUND_TYPE_MAP
from agent_backend.channels.ghl.text import normalize_language


class GhlAgentRequest(BaseModel):
    """
Base request shape for any agent triggered by a GHL workflow webhook.

    The GHL webhook payload is the same for every agent regardless of which
        conversational flow consumes it, so this normalization lives here once.
        Agent-specific request models should subclass this instead of
        redefining the fields/validators.
"""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    messageId: str | None = Field(None, description="Unique message ID from GHL")
    conversation_id: str | None = Field(None, alias="conversationId", description="Conversation ID from GHL")
    contact_id: str = Field(..., alias="contactId", description="Contact ID from GHL")
    location_id: str | None = Field(None, alias="locationId", description="Location ID from GHL")
    message: str | dict[str, Any] | None = Field(None, description="The user's message")
    channel: str | None = Field(None, description="Origin channel inferred from GHL")
    contact: dict[str, Any] | None = Field(None, description="Full contact object from GHL")
    chat_history: list[dict[str, Any]] = Field(default_factory=list, alias="chatHistory", description="Optional chat history")
    webhook_url: str | None = Field(None, alias="webhookUrl", description="Webhook URL to send the response")

    @model_validator(mode="before")
    @classmethod
    def fix_ghl_paths(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        trigger_data = normalized.get("triggerData") or {}
        custom_data = normalized.get("customData") or {}
        location = normalized.get("location") or {}
        msg_obj = normalized.get("message") or {}

        # 1. Prioridad Absoluta: Identificadores Raíz
        normalized["contactId"] = normalized.get("contact_id") or normalized.get("contactId") or custom_data.get("contact_id")
        normalized["locationId"] = location.get("id") or custom_data.get("location_id") or normalized.get("locationId")

        # 2. Mensaje y Canal (Prioridad absoluta al message.type numérico como Source of Truth)
        msg_type = msg_obj.get("type") if isinstance(msg_obj, dict) else None
        
        normalized["channel"] = (
            GHL_INBOUND_TYPE_MAP.get(msg_type)
            or normalized.get("channel")
            or custom_data.get("medium")
            or normalized.get("platform")
        )

        if not normalized.get("message"):
            normalized["message"] = (
                msg_obj.get("body") if isinstance(msg_obj, dict) else None
            ) or custom_data.get("conversation_info")

        # 3. Datos de contacto (Extraídos de la raíz del nuevo payload)
        # Reconstruimos el objeto 'contact' para que sea uniforme para el agente
        contact_obj = dict(normalized.get("contact") or {})
        contact_obj["name"] = normalized.get("full_name") or contact_obj.get("name") or custom_data.get("contact_full_name")
        contact_obj["email"] = normalized.get("email") or contact_obj.get("email") or custom_data.get("contact_email")
        contact_obj["phone"] = normalized.get("phone") or contact_obj.get("phone") or custom_data.get("contact_phone")
        contact_obj["first_name"] = (
            normalized.get("first_name")
            or contact_obj.get("first_name")
            or contact_obj.get("firstName")
            or custom_data.get("contact_first_name")
            or (contact_obj["name"] or "").split(" ")[0]
            or None
        )

        if normalized.get("contactId"):
            contact_obj["contact_id"] = normalized.get("contactId")
        if normalized.get("locationId"):
            contact_obj["location_id"] = normalized.get("locationId")

        candidates = [
            normalized.get("language"),
            normalized.get("contact_language"),
            custom_data.get("language"),
            contact_obj.get("language"),
        ]

        lang_code = None
        for candidate in candidates:
            lang_code = normalize_language(candidate)
            if lang_code:
                break

        contact_obj["language"] = lang_code

        normalized["contact"] = contact_obj

        # 4. IDs de Sesión/Workflow (Fallbacks)
        if not normalized.get("conversationId"):
            normalized["conversationId"] = (
                custom_data.get("conversation_id")
                or trigger_data.get("conversationId") 
            )

        if not normalized.get("messageId"):
            normalized["messageId"] = trigger_data.get("messageId") or custom_data.get("message_id")

        if not normalized.get("webhookUrl"):
            normalized["webhookUrl"] = custom_data.get("webhook_url") or trigger_data.get("webhook_url")

        return normalized

    @field_validator("message", mode="before")
    @classmethod
    def extract_message_body(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("body") or value.get("text") or value.get("message") or None
        return str(value)
