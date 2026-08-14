"""
WebSocket connection manager and message protocol.

See clients/protocol.md for the full wire format. In short: every message is
JSON with a "type" field. The server pushes "notification" messages
whenever the NotificationManager creates one (proactive, unsolicited) and
answers client-initiated messages ("chat.message", "action.confirm") with a
matching reply.
"""
from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

from alex.core.core import ALEXCore
from alex.core.errors import AlexError

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, core: ALEXCore):
        self._core = core
        self._clients: set[WebSocket] = set()
        core.event_bus.subscribe("notification.created", self._on_notification)

    async def _on_notification(self, notification) -> None:
        await self.broadcast({"type": "notification", "notification": notification.to_dict()})

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def handle_connection(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        log.info("Client connected: %s (total=%d)", client_id, len(self._clients))
        try:
            await websocket.send_json({"type": "hello", "assistant_name": self._core.settings.assistant_name})
            while True:
                data = await websocket.receive_json()
                await self._dispatch(websocket, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("Error on connection %s", client_id)
        finally:
            self._clients.discard(websocket)
            log.info("Client disconnected: %s (total=%d)", client_id, len(self._clients))

    async def _dispatch(self, websocket: WebSocket, data: dict) -> None:
        msg_type = data.get("type")
        try:
            if msg_type == "chat.message":
                result = await self._core.handle_user_message(
                    data.get("text", ""), conversation_id=data.get("conversation_id"), channel="app"
                )
                await websocket.send_json({"type": "chat.reply", **result})

            elif msg_type == "action.confirm":
                result = await self._core.resolve_pending_action(
                    data["action_id"], bool(data.get("approved", False))
                )
                await websocket.send_json({"type": "action.result", "action_id": data["action_id"], **result})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({"type": "error", "message": f"Unknown message type '{msg_type}'"})
        except AlexError as e:
            await websocket.send_json({"type": "error", "message": e.message, "code": e.code})
        except KeyError as e:
            await websocket.send_json({"type": "error", "message": f"Missing field: {e}"})
