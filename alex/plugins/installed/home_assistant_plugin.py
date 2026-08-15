"""
Home Assistant plugin - lets ALEX read device/sensor state and call
services (turn things on/off, lock/unlock, etc.) on an existing Home
Assistant instance over its REST API.

Requires ALEX_HOME_ASSISTANT_URL and ALEX_HOME_ASSISTANT_TOKEN (a
long-lived access token generated from your HA user profile page) to be
set - if either is missing, setup() logs a warning and registers no tools
rather than failing the whole plugin load.

Calling a service is CONFIRM-level: Home Assistant controls physical
devices (locks, climate, media, lights...), so ALEX always asks before
acting rather than trying to classify which services are "safe" per call.
"""
from __future__ import annotations

import logging

import httpx

from alex.config import get_settings
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)


class HAGetStateTool(Tool):
    name = "ha_get_state"
    description = "Consulta el estado actual de una entidad de Home Assistant (luz, sensor, interruptor, etc.)."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Id de la entidad, ej. 'light.salon'."}
        },
        "required": ["entity_id"],
    }

    def __init__(self, base_url: str, token: str):
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {token}"}

    async def run(self, entity_id: str) -> ToolResult:
        async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=10) as client:
            resp = await client.get(f"/api/states/{entity_id}")
        if resp.status_code == 404:
            return ToolResult(success=False, content=f"No existe la entidad '{entity_id}'.")
        resp.raise_for_status()
        data = resp.json()
        return ToolResult(
            success=True,
            content=f"{entity_id}: {data['state']}",
            data={"state": data["state"], "attributes": data.get("attributes", {})},
        )


class HAListEntitiesTool(Tool):
    name = "ha_list_entities"
    description = "Lista entidades de Home Assistant, opcionalmente filtradas por dominio (ej. 'light', 'sensor')."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Dominio a filtrar, ej. 'light'. Vacio para todas."}
        },
        "required": [],
    }

    def __init__(self, base_url: str, token: str):
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {token}"}

    async def run(self, domain: str = "") -> ToolResult:
        async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=10) as client:
            resp = await client.get("/api/states")
        resp.raise_for_status()
        entities = resp.json()
        if domain:
            entities = [e for e in entities if e["entity_id"].startswith(f"{domain}.")]
        entities = entities[:30]
        if not entities:
            return ToolResult(success=True, content="No se encontraron entidades.")
        summary = "\n".join(f"- {e['entity_id']}: {e['state']}" for e in entities)
        return ToolResult(success=True, content=summary, data={"entities": entities})


class HACallServiceTool(Tool):
    name = "ha_call_service"
    description = (
        "Ejecuta una accion en Home Assistant (encender/apagar, subir persianas, cambiar temperatura, etc.). "
        "Requiere confirmacion porque controla dispositivos fisicos reales."
    )
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Dominio del servicio, ej. 'light', 'switch', 'lock'."},
            "service": {"type": "string", "description": "Servicio a llamar, ej. 'turn_on', 'turn_off', 'lock'."},
            "entity_id": {"type": "string", "description": "Entidad objetivo, ej. 'light.salon'."},
        },
        "required": ["domain", "service", "entity_id"],
    }

    def __init__(self, base_url: str, token: str):
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {token}"}

    async def run(self, domain: str, service: str, entity_id: str) -> ToolResult:
        async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=10) as client:
            resp = await client.post(f"/api/services/{domain}/{service}", json={"entity_id": entity_id})
        if resp.status_code >= 400:
            return ToolResult(success=False, content=f"Home Assistant rechazo la accion ({resp.status_code}).")
        return ToolResult(success=True, content=f"Hecho: {domain}.{service} sobre {entity_id}.")


class HomeAssistantPlugin(Plugin):
    id = "home_assistant"
    name = "Home Assistant"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not settings.home_assistant_url or not settings.home_assistant_token:
            log.warning(
                "Home Assistant plugin enabled but ALEX_HOME_ASSISTANT_URL/ALEX_HOME_ASSISTANT_TOKEN "
                "are not set - no tools registered. See docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        base_url = settings.home_assistant_url.rstrip("/")
        token = settings.home_assistant_token
        ctx.register_tool(HAGetStateTool(base_url, token))
        ctx.register_tool(HAListEntitiesTool(base_url, token))
        ctx.register_tool(HACallServiceTool(base_url, token))
        log.info("Home Assistant plugin ready (%s)", base_url)


PLUGIN = HomeAssistantPlugin
