from fastapi import APIRouter, Request
import json
import datetime
from pathlib import Path
from agent_backend.builtin_tools.schemas.input_payload import InputPayloadResponse
from agent_backend.channels.ghl.request import GhlAgentRequest

router = APIRouter()

# Centralizar logs en backups para reverse engineering
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
LOG_FILE = ROOT_DIR / "backups" / "discovery_payloads.jsonl"

@router.post("/input-payload", response_model=InputPayloadResponse)
async def receive_payload(request: Request):
    """receive_payload.

    Endpoint de utilidad para capturar y loguear cualquier payload enviado por GHL.
    Útil para ingeniería inversa de webhooks y disparadores.
    """
    try:
        body = await request.body()
        payload = await request.json() if body else {}
    except Exception:
        payload = {"raw_body": body.decode("utf-8", errors="replace") if body else "empty"}

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Capturar metadatos útiles para ingeniería inversa
    log_entry = {
        "timestamp": timestamp,
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "query_params": dict(request.query_params),
        "client_host": request.client.host if request.client else "unknown",
        "payload": payload
    }
    
    # Asegurar que el directorio existe
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Guardar en archivo de log raw
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
            
        # Usar el modelo centralizado para validar y mapear (Ingeniería Inversa Real)
        req = GhlAgentRequest(**payload)
        
        summary = {
            "keys_count": len(payload.keys()) if isinstance(payload, dict) else 0,
            "has_contact": bool(req.contact_id),
            "has_message": bool(req.message),
            "channel": req.channel,
            "ghl_type_id": (payload.get("message") or {}).get("type") if isinstance(payload.get("message"), dict) else None
        }
        
        return InputPayloadResponse(
            success=True,
            message=f"Payload capturado con éxito en {LOG_FILE.name}",
            received_keys=list(payload.keys()) if isinstance(payload, dict) else [],
            payload_summary=summary
        )
    except Exception as e:
        return InputPayloadResponse(
            success=False,
            message=f"Error al guardar payload: {str(e)}",
            received_keys=list(payload.keys()) if isinstance(payload, dict) else ["error"],
            payload_summary={"error": str(e)}
        )
