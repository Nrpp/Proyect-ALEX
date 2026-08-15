"""
Shared Google OAuth2 refresh-token -> access-token exchange, used by both
the google_calendar and google_tasks plugins (same token endpoint, same
refresh-token grant - no reason to duplicate it per plugin).
"""
from __future__ import annotations

import time

import httpx

from alex.core.errors import ToolError

TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOAuthTokenSource:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at - 60:
            return self._access_token
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(TOKEN_URL, data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            })
        if resp.status_code != 200:
            raise ToolError(f"No se pudo renovar el token de Google: {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.monotonic() + data.get("expires_in", 3600)
        return self._access_token
