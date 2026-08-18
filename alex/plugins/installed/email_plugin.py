"""
Email plugin - reads, marks-read and sends Gmail messages via the Gmail v3
REST API directly over httpx (no Google SDK dependency, consistent with the
google_calendar/google_tasks plugins).

One-time setup required outside ALEX: create an OAuth2 "Desktop app" client
in Google Cloud Console (the same one used for Calendar/Tasks works fine,
just enable the Gmail API on it too), then run `scripts/google_oauth_auth.py
--scopes gmail` on a machine with a browser (NOT the Pi) to mint a refresh
token - see docs/INSTALL_RASPBERRY_PI.md. ALEX only ever holds the
long-lived refresh token + client id/secret; access tokens are minted on
demand via GoogleOAuthTokenSource and cached in memory for their lifetime.
"""
from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

import httpx

from alex.config import get_settings
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.plugins.google_oauth import GoogleOAuthTokenSource
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, address: str):
        self._oauth = GoogleOAuthTokenSource(client_id, client_secret, refresh_token)
        self.address = address

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._oauth.token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=API_BASE, headers=headers, timeout=15) as client:
            return await client.request(method, path, **kwargs)

    async def list_unread(self, limit: int) -> list[dict]:
        resp = await self._request(
            "GET", "/users/me/messages", params={"q": "is:unread", "maxResults": limit}
        )
        resp.raise_for_status()
        refs = resp.json().get("messages", [])
        results = []
        for ref in refs:
            detail = await self._request(
                "GET", f"/users/me/messages/{ref['id']}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From"]},
            )
            detail.raise_for_status()
            payload = detail.json()
            headers = {h["name"]: h["value"] for h in payload.get("payload", {}).get("headers", [])}
            results.append({
                "id": payload["id"],
                "subject": headers.get("Subject", "(sin asunto)"),
                "from": headers.get("From", ""),
            })
        return results

    async def mark_read(self, message_id: str) -> None:
        resp = await self._request(
            "POST", f"/users/me/messages/{message_id}/modify", json={"removeLabelIds": ["UNREAD"]}
        )
        resp.raise_for_status()

    async def send(self, to: str, subject: str, body: str) -> None:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.address
        msg["To"] = to
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = await self._request("POST", "/users/me/messages/send", json={"raw": raw})
        resp.raise_for_status()


class EmailCheckUnreadTool(Tool):
    name = "email_check_unread"
    description = "Consulta los correos no leidos mas recientes de la bandeja de entrada."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Maximo de correos a devolver (por defecto 10)."}},
        "required": [],
    }

    def __init__(self, client: GmailClient):
        self._client = client

    async def run(self, limit: int = 10) -> ToolResult:
        messages = await self._client.list_unread(limit)
        if not messages:
            return ToolResult(success=True, content="No hay correos sin leer.")
        summary = "\n".join(f"- ({m['id']}) {m['from']}: {m['subject']}" for m in messages)
        return ToolResult(success=True, content=summary, data={"messages": messages})


class EmailMarkReadTool(Tool):
    name = "email_mark_read"
    description = "Marca un correo como leido por su id (obtenido con email_check_unread)."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {"message_id": {"type": "string", "description": "Id del mensaje."}},
        "required": ["message_id"],
    }

    def __init__(self, client: GmailClient):
        self._client = client

    async def run(self, message_id: str) -> ToolResult:
        await self._client.mark_read(message_id)
        return ToolResult(success=True, content=f"Correo {message_id} marcado como leido.")


class EmailSendTool(Tool):
    name = "email_send"
    description = "Envia un correo desde la cuenta de Alex. Requiere confirmacion antes de enviarse."
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Direccion de correo del destinatario."},
            "subject": {"type": "string", "description": "Asunto del correo."},
            "body": {"type": "string", "description": "Cuerpo del correo, texto plano."},
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(self, client: GmailClient):
        self._client = client

    async def run(self, to: str, subject: str, body: str) -> ToolResult:
        await self._client.send(to, subject, body)
        return ToolResult(success=True, content=f"Correo enviado a {to}.")


class EmailPlugin(Plugin):
    id = "email"
    name = "Email (Gmail)"
    version = "0.2.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not all([
            settings.gmail_address,
            settings.google_gmail_client_id,
            settings.google_gmail_client_secret,
            settings.google_gmail_refresh_token,
        ]):
            log.warning(
                "Email plugin enabled but Gmail OAuth credentials are not fully set - no tools "
                "registered. Run scripts/google_oauth_auth.py --scopes gmail, see "
                "docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        self._client = GmailClient(
            settings.google_gmail_client_id,
            settings.google_gmail_client_secret,
            settings.google_gmail_refresh_token,
            settings.gmail_address,
        )
        self._seen_ids: set[str] | None = None

        ctx.register_tool(EmailCheckUnreadTool(self._client))
        ctx.register_tool(EmailMarkReadTool(self._client))
        ctx.register_tool(EmailSendTool(self._client))
        ctx.schedule_interval(
            lambda: self._check(ctx), settings.gmail_check_interval_seconds, "email_plugin_check"
        )
        log.info("Email plugin ready (%s, checking every %ss)", settings.gmail_address, settings.gmail_check_interval_seconds)

    async def _check(self, ctx: PluginContext) -> None:
        try:
            messages = await self._client.list_unread(10)
        except Exception:
            log.exception("Email check failed")
            return

        current_ids = {m["id"] for m in messages}
        if self._seen_ids is None:
            # First run: just establish the baseline, don't notify about the
            # existing backlog of unread mail.
            self._seen_ids = current_ids
            return

        new_messages = [m for m in messages if m["id"] not in self._seen_ids]
        self._seen_ids = current_ids
        if not new_messages:
            return

        latest = new_messages[0]
        body = f"{latest['from']}: {latest['subject']}"
        if len(new_messages) > 1:
            body += f" (+{len(new_messages) - 1} mas)"
        await ctx.emit_event(Event(
            source="email", type="email.new", title="Correo nuevo", body=body,
            severity=0.5, dedupe_key=f"email:{latest['id']}",
        ))


PLUGIN = EmailPlugin
