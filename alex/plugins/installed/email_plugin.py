"""
Email plugin - reads and sends Gmail messages using an app password
(https://myaccount.google.com/apppasswords, requires 2FA on the Google
account) over IMAP (read) and SMTP (send). Deliberately app password rather
than full OAuth: it's a few minutes of setup instead of registering a Cloud
project, and neither reading nor sending mail needs broader API scopes.

Sending is CONFIRM-gated (same reasoning as run_shell_command / alexos_action:
a real, externally-visible side effect once approved). IMAP/SMTP calls are
blocking, so every call runs off the event loop via run_in_executor.
"""
from __future__ import annotations

import email
import imaplib
import logging
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

from alex.config import get_settings
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _decode(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(
        chunk.decode(enc or "utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        for chunk, enc in parts
    )


IMAP_TIMEOUT_SECONDS = 15


def _connect(address: str, app_password: str) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, timeout=IMAP_TIMEOUT_SECONDS)
    conn.login(address, app_password)
    conn.select("INBOX")
    return conn


def _fetch_unread(address: str, app_password: str, limit: int) -> list[dict]:
    conn = _connect(address, app_password)
    try:
        _status, data = conn.uid("search", None, "UNSEEN")
        uids = data[0].split()[-limit:]
        results = []
        for uid in reversed(uids):
            _status, msg_data = conn.uid("fetch", uid, "(RFC822.HEADER)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            results.append({
                "uid": uid.decode(),
                "subject": _decode(msg.get("Subject", "(sin asunto)")),
                "from": _decode(msg.get("From", "")),
            })
        return results
    finally:
        conn.logout()


def _mark_read(address: str, app_password: str, uid: str) -> None:
    conn = _connect(address, app_password)
    try:
        conn.uid("store", uid, "+FLAGS", "\\Seen")
    finally:
        conn.logout()


def _send(address: str, app_password: str, to: str, subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=IMAP_TIMEOUT_SECONDS) as conn:
        conn.login(address, app_password)
        conn.sendmail(address, [to], msg.as_string())


class EmailCheckUnreadTool(Tool):
    name = "email_check_unread"
    description = "Consulta los correos no leidos mas recientes de la bandeja de entrada."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Maximo de correos a devolver (por defecto 10)."}},
        "required": [],
    }

    def __init__(self, address: str, app_password: str, loop_executor):
        self._address = address
        self._app_password = app_password
        self._run = loop_executor

    async def run(self, limit: int = 10) -> ToolResult:
        messages = await self._run(_fetch_unread, self._address, self._app_password, limit)
        if not messages:
            return ToolResult(success=True, content="No hay correos sin leer.")
        summary = "\n".join(f"- ({m['uid']}) {m['from']}: {m['subject']}" for m in messages)
        return ToolResult(success=True, content=summary, data={"messages": messages})


class EmailMarkReadTool(Tool):
    name = "email_mark_read"
    description = "Marca un correo como leido por su uid (obtenido con email_check_unread)."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {"uid": {"type": "string", "description": "Uid del mensaje."}},
        "required": ["uid"],
    }

    def __init__(self, address: str, app_password: str, loop_executor):
        self._address = address
        self._app_password = app_password
        self._run = loop_executor

    async def run(self, uid: str) -> ToolResult:
        await self._run(_mark_read, self._address, self._app_password, uid)
        return ToolResult(success=True, content=f"Correo {uid} marcado como leido.")


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

    def __init__(self, address: str, app_password: str, loop_executor):
        self._address = address
        self._app_password = app_password
        self._run = loop_executor

    async def run(self, to: str, subject: str, body: str) -> ToolResult:
        await self._run(_send, self._address, self._app_password, to, subject, body)
        return ToolResult(success=True, content=f"Correo enviado a {to}.")


class EmailPlugin(Plugin):
    id = "email"
    name = "Email (Gmail)"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not settings.gmail_address or not settings.gmail_app_password:
            log.warning(
                "Email plugin enabled but ALEX_GMAIL_ADDRESS/ALEX_GMAIL_APP_PASSWORD are not set - "
                "no tools registered. See docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        import asyncio

        loop = asyncio.get_event_loop()

        async def run_blocking(fn, *args):
            return await loop.run_in_executor(None, fn, *args)

        self._address = settings.gmail_address
        self._app_password = settings.gmail_app_password
        self._run_blocking = run_blocking
        self._last_notified_uid = 0

        ctx.register_tool(EmailCheckUnreadTool(self._address, self._app_password, run_blocking))
        ctx.register_tool(EmailMarkReadTool(self._address, self._app_password, run_blocking))
        ctx.register_tool(EmailSendTool(self._address, self._app_password, run_blocking))
        ctx.schedule_interval(
            lambda: self._check(ctx), settings.gmail_check_interval_seconds, "email_plugin_check"
        )
        log.info("Email plugin ready (%s, checking every %ss)", self._address, settings.gmail_check_interval_seconds)

    async def _check(self, ctx: PluginContext) -> None:
        try:
            messages = await self._run_blocking(_fetch_unread, self._address, self._app_password, 10)
        except Exception:
            log.exception("Email check failed")
            return

        new_messages = [m for m in messages if int(m["uid"]) > self._last_notified_uid]
        if not new_messages:
            return
        self._last_notified_uid = max(int(m["uid"]) for m in messages)

        latest = new_messages[0]
        body = f"{latest['from']}: {latest['subject']}"
        if len(new_messages) > 1:
            body += f" (+{len(new_messages) - 1} mas)"
        await ctx.emit_event(Event(
            source="email", type="email.new", title="Correo nuevo", body=body,
            severity=0.5, dedupe_key=f"email:{self._last_notified_uid}",
        ))


PLUGIN = EmailPlugin
