"""Sending e-mail through the Gmail API. No business rules."""
import base64
from email.message import EmailMessage

import httpx


async def send_email(access_token: str, sender: str, to: str, subject: str, html_body: str) -> dict:
    """Envía un correo HTML vía Gmail API (users.messages.send), autenticado con el access_token de la cuenta que envía.
    """
    message = EmailMessage()
    message["To"] = to
    message["From"] = sender
    message["Subject"] = subject
    message.set_content("Este correo requiere un cliente compatible con HTML.")
    message.add_alternative(html_body, subtype="html")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()
