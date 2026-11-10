import datetime
import os
import traceback
from functools import lru_cache
from typing import Any

import requests
from fastapi import APIRouter, HTTPException

from agent_backend.channels.ghl.client import (
    DEFAULT_TOKEN_ENVS,
    GHL_FILTER_TYPE_MAP,
    GHL_OUTBOUND_CHANNEL_MAP,
)
from agent_backend.channels.ghl.request import GhlAgentRequest
from agent_backend.channels.ghl.text import normalize_channel

router = APIRouter()

BASE_URL = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
GHL_VERSION = os.getenv("GHL_VERSION", "v3")


@lru_cache
def _allowed_phones() -> set[str]:
    raw = os.getenv("ECHO_ALLOWED_PHONES", "")
    return {number.strip() for number in raw.split(",") if number.strip()}


def _resolve_ghl_token() -> str:
    token = next((v for v in (os.getenv(env, "").strip() for env in DEFAULT_TOKEN_ENVS) if v), "")

    if token:
        return token

    try:
        from app import GHL_TOKEN as root_token

        return (root_token or "").strip()
    except Exception:
        return ""


def _build_headers() -> dict[str, str]:
    token = _resolve_ghl_token()
    return {
        "Authorization": f"Bearer {token}",
        "Version": GHL_VERSION,
    }


def _send_echo(contact_id: str, channel: str, message: str, reply_message_id: str | None) -> dict[str, Any]:
    channel_key = normalize_channel(channel)
    send_type = GHL_OUTBOUND_CHANNEL_MAP.get(channel_key)
    if not send_type:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported channel for sending: {channel}. Supported: {sorted(GHL_OUTBOUND_CHANNEL_MAP)}",
        )

    payload: dict[str, Any] = {
        "type": send_type,
        "contactId": contact_id,
        "message": message,
        "status": "pending",
    }
    if reply_message_id:
        payload["replyMessageId"] = reply_message_id

    response = requests.post(
        f"{BASE_URL}/conversations/messages",
        headers={**_build_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()


def _extract_messages_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    messages = data.get("messages")
    if isinstance(messages, dict):
        inner = messages.get("messages", [])
        return inner if isinstance(inner, list) else []
    if isinstance(messages, list):
        return messages
    return []


def _parse_iso_z(value: str | None) -> datetime.datetime:
    if not value:
        return datetime.datetime.min
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.datetime.min


def _append_log(record: dict[str, Any]) -> None:
    return None


def _append_trace(step: str, data: dict[str, Any]) -> None:
    return None


def _get_messages(conversation_id: str, limit: int, type_param: str | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if type_param:
        params["type"] = type_param

    response = requests.get(
        f"{BASE_URL}/conversations/{conversation_id}/messages",
        headers=_build_headers(),
        params=params,
        timeout=60,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return _extract_messages_list(response.json())


def _find_or_create_conversation(contact_id: str, location_id: str) -> str:
    search = requests.get(
        f"{BASE_URL}/conversations/search",
        headers=_build_headers(),
        params={"locationId": location_id, "contactId": contact_id},
        timeout=60,
    )
    if search.status_code != 200:
        raise HTTPException(status_code=search.status_code, detail=search.text)

    conversations = search.json().get("conversations", [])
    if conversations:
        conversation = conversations[0]
        conversation_id = conversation.get("id") or conversation.get("conversationId")
        if conversation_id:
            return str(conversation_id)

    create_response = requests.post(
        f"{BASE_URL}/conversations/",
        headers={**_build_headers(), "Content-Type": "application/json"},
        json={"locationId": location_id, "contactId": contact_id},
        timeout=60,
    )
    if create_response.status_code not in (200, 201):
        raise HTTPException(status_code=create_response.status_code, detail=create_response.text)

    created = create_response.json().get("conversation", {})
    conversation_id = created.get("id") or created.get("conversationId")
    if not conversation_id:
        raise HTTPException(status_code=502, detail="Could not obtain conversationId")

    return str(conversation_id)


def _log_exception(status: str, payload: dict[str, Any], error: Exception) -> None:
    _append_log(
        {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "status": status,
            "raw_payload": payload,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
        }
    )


@router.post("/echo")
def echo(payload: dict[str, Any]):
    try:
        _append_trace(
            "received_payload",
            {
                "keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
                "payload_preview": payload if isinstance(payload, dict) else str(payload),
            },
        )

        ghl_token = _resolve_ghl_token()
        if not ghl_token:
            raise HTTPException(
                status_code=500,
                detail=("GHL_TOKEN is missing in environment or not defined in app.py"),
            )

        # Usar GhlAgentRequest para normalizar la entrada
        req = GhlAgentRequest(**payload)

        contact_id = req.contact_id
        location_id = req.location_id
        incoming_text = req.message
        channel = normalize_channel(req.channel)

        # Extraer teléfono para el filtro
        contact_obj = req.contact or {}
        phone = (
            str(contact_obj.get("phone") or "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        _append_trace(
            "extracted_fields",
            {
                "contact_id": contact_id,
                "location_id": location_id,
                "channel": channel or None,
                "incoming_text": incoming_text,
                "phone": phone,
                "token_source": "env_or_app_py",
            },
        )

        # Filtro de telefonos permitidos
        allowed_phones = _allowed_phones()
        if phone not in allowed_phones:
            _append_log(
                {
                    "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                    "status": "phone_not_allowed",
                    "phone": phone,
                    "raw_payload": payload,
                }
            )
            return {
                "ok": True,
                "echoSent": False,
                "reason": f"Phone {phone} is not in the allowed list",
            }

        if not contact_id:
            raise HTTPException(status_code=400, detail="contact_id/contactId not found in payload")
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id/location.id not found in payload")

        _append_trace(
            "searching_conversation",
            {
                "contact_id": contact_id,
                "location_id": location_id,
            },
        )
        conversation_id = _find_or_create_conversation(contact_id, location_id)

        _append_trace(
            "conversation_ready",
            {
                "conversation_id": conversation_id,
            },
        )

        type_param = GHL_FILTER_TYPE_MAP.get(channel)
        _append_trace(
            "fetching_messages",
            {
                "conversation_id": conversation_id,
                "type_param": type_param,
            },
        )
        messages = (
            _get_messages(conversation_id, limit=10, type_param=type_param)
            if type_param
            else _get_messages(conversation_id, limit=10, type_param=None)
        )
        inbound_messages = [message for message in messages if message.get("direction") == "inbound"]

        _append_trace(
            "messages_loaded",
            {
                "total_messages": len(messages),
                "inbound_messages": len(inbound_messages),
                "message_ids": [message.get("id") for message in messages[:10]],
            },
        )

        if not inbound_messages and type_param is not None:
            _append_trace(
                "retrying_without_type_filter",
                {
                    "conversation_id": conversation_id,
                    "previous_type_param": type_param,
                },
            )
            messages = _get_messages(conversation_id, limit=10, type_param=None)
            inbound_messages = [message for message in messages if message.get("direction") == "inbound"]

            _append_trace(
                "messages_loaded_without_filter",
                {
                    "total_messages": len(messages),
                    "inbound_messages": len(inbound_messages),
                    "message_ids": [message.get("id") for message in messages[:10]],
                },
            )

        if not inbound_messages:
            _append_log(
                {
                    "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                    "status": "no_inbound_messages_found",
                    "raw_payload": payload,
                    "contact_id": contact_id,
                    "location_id": location_id,
                    "conversation_id": conversation_id,
                    "channel": channel or None,
                    "incoming_text": incoming_text,
                }
            )
            return {
                "ok": True,
                "echoSent": False,
                "reason": "No inbound messages found for this conversation",
                "contactId": contact_id,
                "locationId": location_id,
                "conversationId": conversation_id,
            }

        last_message = max(inbound_messages, key=lambda item: _parse_iso_z(item.get("dateAdded")))
        last_body = str(last_message.get("body") or last_message.get("message") or "").strip()
        if not last_body:
            last_body = str(incoming_text or f"(sin body) messageId={last_message.get('id')}")

        _append_trace(
            "selected_last_inbound",
            {
                "message_id": last_message.get("id"),
                "dateAdded": last_message.get("dateAdded"),
                "direction": last_message.get("direction"),
                "messageType": last_message.get("messageType"),
                "body": last_body,
            },
        )

        echo_text = f"[ECHO] {last_body}"
        _append_trace(
            "sending_echo",
            {
                "contact_id": contact_id,
                "channel": channel or None,
                "reply_message_id": last_message.get("id"),
                "echo_text": echo_text,
            },
        )
        sent_message = _send_echo(
            contact_id=contact_id,
            channel=channel or "LIVE_CHAT",
            message=echo_text,
            reply_message_id=last_message.get("id"),
        )

        _append_trace(
            "echo_sent",
            {
                "sent_message_keys": sorted(sent_message.keys()) if isinstance(sent_message, dict) else None,
                "sent_message_preview": sent_message,
            },
        )

        _append_log(
            {
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "status": "echo_sent",
                "raw_payload": payload,
                "contact_id": contact_id,
                "location_id": location_id,
                "conversation_id": conversation_id,
                "channel": channel or None,
                "incoming_text": incoming_text,
                "last_inbound_message": last_message,
                "echo_text": echo_text,
                "sent_message": sent_message,
            }
        )

        return {
            "ok": True,
            "echoSent": True,
            "contactId": contact_id,
            "locationId": location_id,
            "conversationId": conversation_id,
            "channel": channel or None,
            "incomingText": incoming_text,
            "lastMessage": {
                "id": last_message.get("id"),
                "dateAdded": last_message.get("dateAdded"),
                "body": last_body,
                "direction": last_message.get("direction"),
                "messageType": last_message.get("messageType"),
            },
            "echoText": echo_text,
            "sentMessage": sent_message,
        }
    except HTTPException:
        raise
    except requests.RequestException as error:
        _append_trace(
            "request_exception",
            {
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        _log_exception("request_exception", payload, error)
        raise HTTPException(status_code=502, detail=f"Network error calling GHL: {error}") from error
    except Exception as error:
        _append_trace(
            "unexpected_exception",
            {
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        _log_exception("unexpected_exception", payload, error)
        raise HTTPException(status_code=500, detail=f"Unexpected error in echo: {error}") from error
