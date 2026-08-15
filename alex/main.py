"""
ALEX entrypoint.

    python -m alex.main

Starts logging, builds the FastAPI app (which owns ALEXCore's lifecycle via
its lifespan handler - see alex/server/app.py) and runs it with uvicorn.
This is what the systemd service (scripts/alex.service) executes.
"""
from __future__ import annotations

import logging

import uvicorn

from alex.config import get_settings
from alex.logging_setup import setup_logging

log = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    setup_logging(settings)

    if not settings.api_token:
        log.warning(
            "ALEX_API_TOKEN is not set - the API/WebSocket are UNAUTHENTICATED. "
            "Set it in .env before exposing ALEX beyond localhost."
        )

    log.info(
        "Starting ALEX for %s (provider=%s, voice=%s) on %s:%d",
        settings.owner_name, settings.ai_provider, settings.voice_enabled, settings.host, settings.port,
    )

    uvicorn.run(
        "alex.server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,  # we own logging via alex.logging_setup
        # Uvicorn's WebSocket ping defaults (20s/20s) can close a connection
        # while a long conversational turn is legitimately still in progress
        # (ALEXCore bounds turns itself via ai_turn_timeout_seconds - this is
        # just defense in depth so the transport doesn't give up first).
        ws_ping_interval=20,
        ws_ping_timeout=120,
    )


if __name__ == "__main__":
    main()
