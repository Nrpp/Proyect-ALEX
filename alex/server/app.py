"""
FastAPI application: REST API + WebSocket, the front door clients use to
talk to ALEX. Kept deliberately small - almost everything delegates to
ALEXCore. Owns process lifecycle (startup/shutdown) via FastAPI's lifespan.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from alex.config import BASE_DIR, Settings, get_settings
from alex.core.core import ALEXCore
from alex.core.errors import AlexError
from alex.server.auth import require_token, require_token_ws
from alex.server.ws import ConnectionManager

log = logging.getLogger(__name__)

WEB_CONSOLE_DIR = BASE_DIR / "clients" / "web_console"


class ChatRequest(BaseModel):
    text: str
    conversation_id: str | None = None


class ConfirmRequest(BaseModel):
    approved: bool


class NotificationStatusRequest(BaseModel):
    status: str


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    core = ALEXCore(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await core.start()

        voice_task: asyncio.Task | None = None
        if settings.voice_enabled:
            try:
                from alex.voice.pipeline import VoicePipeline

                pipeline = VoicePipeline(core, settings)
                _app.state.voice_pipeline = pipeline
                voice_task = asyncio.create_task(pipeline.run())
            except Exception:
                log.exception("Voice pipeline failed to start - ALEX will run without voice")

        yield

        if voice_task is not None:
            _app.state.voice_pipeline.stop()
            voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await voice_task
        await core.shutdown()

    app = FastAPI(title="ALEX", version="0.1.0", lifespan=lifespan)
    app.state.core = core

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    connections = ConnectionManager(core)
    app.state.connections = connections

    @app.exception_handler(AlexError)
    async def alex_error_handler(_request, exc: AlexError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"error": exc.code, "message": exc.message})

    # --------------------------------------------------------------- #
    # Health (no auth - used by systemd/monitoring/curl on localhost)
    # --------------------------------------------------------------- #
    @app.get("/health")
    async def health():
        return await core.health()

    # --------------------------------------------------------------- #
    # Chat (text in / text out - same path voice uses after STT)
    # --------------------------------------------------------------- #
    @app.post("/chat", dependencies=[Depends(require_token)])
    async def chat(req: ChatRequest):
        return await core.handle_user_message(req.text, conversation_id=req.conversation_id, channel="api")

    # --------------------------------------------------------------- #
    # Pending action confirmation (CONFIRM-level tools)
    # --------------------------------------------------------------- #
    @app.post("/actions/{action_id}/confirm", dependencies=[Depends(require_token)])
    async def confirm_action(action_id: str, req: ConfirmRequest):
        return await core.resolve_pending_action(action_id, req.approved)

    @app.get("/actions/pending", dependencies=[Depends(require_token)])
    async def list_pending_actions():
        return [
            {"id": a.id, "tool_name": a.tool_name, "arguments": a.arguments, "reason": a.reason,
             "created_at": a.created_at}
            for a in core.permissions.list_pending()
        ]

    # --------------------------------------------------------------- #
    # Notifications history (clients can pull on reconnect/startup)
    # --------------------------------------------------------------- #
    @app.get("/notifications", dependencies=[Depends(require_token)])
    async def list_notifications(limit: int = 20, status: str | None = None):
        items = await core.notifications.list_recent(limit=limit, status=status)
        return [n.to_dict() for n in items]

    @app.post("/notifications/{notification_id}/status", dependencies=[Depends(require_token)])
    async def update_notification_status(notification_id: str, req: NotificationStatusRequest):
        ok = await core.notifications.mark_status(notification_id, req.status)
        return {"success": ok}

    # --------------------------------------------------------------- #
    # Reminders (read/cancel - creating one goes through chat, via the
    # set_reminder tool, so the AI can parse relative times like "en 30
    # minutos"; this is for clients that just need to show/manage the
    # existing list, e.g. AlexOS's Alex module)
    # --------------------------------------------------------------- #
    @app.get("/reminders", dependencies=[Depends(require_token)])
    async def list_reminders():
        return await core.memory.list_pending_reminders()

    @app.delete("/reminders/{reminder_id}", dependencies=[Depends(require_token)])
    async def cancel_reminder(reminder_id: str):
        ok = await core.memory.cancel_reminder(reminder_id)
        return {"success": ok}

    # --------------------------------------------------------------- #
    # Web Push (optional - lets the console reach a phone, including an
    # iPhone via its installed PWA, even while the console isn't open)
    # --------------------------------------------------------------- #
    @app.get("/push/vapid_public_key", dependencies=[Depends(require_token)])
    async def get_vapid_public_key():
        return {"configured": bool(settings.vapid_public_key), "public_key": settings.vapid_public_key}

    @app.post("/push/subscribe", dependencies=[Depends(require_token)])
    async def push_subscribe(req: PushSubscribeRequest):
        await core.push_subscriptions.add(req.endpoint, req.keys.p256dh, req.keys.auth)
        return {"success": True}

    @app.post("/push/unsubscribe", dependencies=[Depends(require_token)])
    async def push_unsubscribe(req: PushUnsubscribeRequest):
        await core.push_subscriptions.remove(req.endpoint)
        return {"success": True}

    # --------------------------------------------------------------- #
    # WebSocket - persistent, real-time channel for clients
    # --------------------------------------------------------------- #
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        if not await require_token_ws(websocket):
            return
        client_id = websocket.query_params.get("client_id") or str(uuid.uuid4())
        await connections.handle_connection(websocket, client_id)

    # --------------------------------------------------------------- #
    # Web console - a static HUD-style chat client served straight from
    # ALEX itself, at /console/. No build step: it's plain HTML/CSS/JS that
    # talks to the same WS/REST API any other client uses (see
    # clients/protocol.md). Not auth-gated (it holds no secrets itself -
    # the token is entered by the user and used client-side), same trust
    # model as clients/desktop_minimal.
    # --------------------------------------------------------------- #
    if WEB_CONSOLE_DIR.exists():
        app.mount("/console", StaticFiles(directory=str(WEB_CONSOLE_DIR), html=True), name="console")

    return app
