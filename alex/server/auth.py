"""
Shared-secret bearer token auth.

ALEX is designed to live on the local network only (see docs/ARCHITECTURE.md
for the "no unnecessary Internet exposure" stance). This token is the
minimum bar so a device on the LAN can't talk to ALEX without the secret
from `.env`; use Tailscale for anything beyond the LAN rather than opening
a port on your router.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, WebSocket, status

from alex.config import Settings, get_settings

log = logging.getLogger(__name__)


def _valid(token: str | None, settings: Settings) -> bool:
    if not settings.api_token:
        # No token configured: explicitly insecure, only acceptable for local dev.
        return True
    return bool(token) and hmac.compare_digest(token, settings.api_token)


async def require_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not _valid(token, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


async def require_token_ws(websocket: WebSocket) -> bool:
    settings = get_settings()
    token = websocket.query_params.get("token")
    if token is None:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
    if not _valid(token, settings):
        await websocket.close(code=4401)
        return False
    return True
