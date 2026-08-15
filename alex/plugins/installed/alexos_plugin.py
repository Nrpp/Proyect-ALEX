"""
AlexOS bridge plugin - lets ALEX read and act on AlexOS (the personal-OS
dashboard, a separate project usually running on this same Raspberry Pi).
AlexOS's REST API has no authentication of its own (single-user personal
device, LAN-only by design - see its docs/ARCHITECTURE.md), so only a
base URL is needed here, no token.

Three tools, generic rather than one wrapper per AlexOS module, because
AlexOS modules are added/removed independently of ALEX and a hardcoded
wrapper per module would go stale the moment AlexOS changes:

  alexos_list_modules - discovers what's actually installed right now
                         (name/description/routes), so ALEX can figure
                         out what's possible instead of guessing paths.
  alexos_get           - READ: any GET under /api/v1/... (read light/
                          task/server state, notification history, ...).
  alexos_action        - CONFIRM: any POST/PATCH/DELETE under /api/v1/...
                          (turn on a light, restart a container, add a
                          task, ...) - always confirmed, since these are
                          real side effects on physical devices or system
                          state, same reasoning as run_shell_command.
"""
from __future__ import annotations

import json
import logging

import httpx

from alex.config import get_settings
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

MAX_RESPONSE_CHARS = 4000


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESPONSE_CHARS:
        return text
    return text[:MAX_RESPONSE_CHARS] + f"\n... (truncado, {len(text) - MAX_RESPONSE_CHARS} caracteres mas)"


class AlexOSListModulesTool(Tool):
    name = "alexos_list_modules"
    description = (
        "Lista los modulos instalados en AlexOS ahora mismo (nombre, descripcion, rutas API). "
        "Usa esto primero para saber que hay disponible antes de usar alexos_get o alexos_action."
    )
    permission_level = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._base_url = base_url
        self._transport = transport

    async def run(self) -> ToolResult:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10, transport=self._transport) as client:
            resp = await client.get("/api/v1/modules")
        resp.raise_for_status()
        modules = resp.json()
        if not modules:
            return ToolResult(success=True, content="AlexOS no tiene modulos instalados.")
        lines = []
        for entry in modules:
            manifest = entry.get("manifest", {})
            name = manifest.get("name", "?")
            routes = ", ".join(f"/api/v1/modules/{name}{route}" for route in manifest.get("routes", []))
            lines.append(f"- {name}: {manifest.get('description', '')} (rutas: {routes or 'ninguna'})")
        return ToolResult(success=True, content="\n".join(lines), data={"modules": modules})


class AlexOSGetTool(Tool):
    name = "alexos_get"
    description = (
        "Hace una peticion GET a la API de AlexOS (el panel/OS personal, normalmente en esta misma "
        "Raspberry Pi). 'path' debe empezar por '/api/v1/', ej. '/api/v1/modules/room/lights' o "
        "'/api/v1/notifications'. Usa alexos_list_modules primero si no sabes que rutas existen."
    )
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Ruta, ej. '/api/v1/modules/servers/stats'."}},
        "required": ["path"],
    }

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._base_url = base_url
        self._transport = transport

    async def run(self, path: str) -> ToolResult:
        if not path.startswith("/api/v1/"):
            return ToolResult(success=False, content="La ruta debe empezar por '/api/v1/'.")
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10, transport=self._transport) as client:
            resp = await client.get(path)
        if resp.status_code >= 400:
            return ToolResult(
                success=False, content=f"AlexOS respondio con error {resp.status_code}: {_truncate(resp.text)}"
            )
        data, content = _parse_response(resp)
        return ToolResult(success=True, content=content, data={"response": data})


class AlexOSActionTool(Tool):
    name = "alexos_action"
    description = (
        "Ejecuta una accion en AlexOS (POST/PATCH/DELETE) - enciende/apaga algo, cambia un valor, "
        "borra algo, etc. Requiere confirmacion porque puede tener efectos reales (dispositivos "
        "fisicos, contenedores, datos). 'path' debe empezar por '/api/v1/'. 'body' es el JSON a "
        "enviar, opcional segun la accion."
    )
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta, ej. '/api/v1/modules/room/lights/light.salon'."},
            "method": {"type": "string", "description": "POST, PATCH o DELETE.", "enum": ["POST", "PATCH", "DELETE"]},
            "body": {"type": "object", "description": "Cuerpo JSON opcional para la peticion."},
        },
        "required": ["path", "method"],
    }

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._base_url = base_url
        self._transport = transport

    async def run(self, path: str, method: str, body: dict | None = None) -> ToolResult:
        if not path.startswith("/api/v1/"):
            return ToolResult(success=False, content="La ruta debe empezar por '/api/v1/'.")
        method = method.upper()
        if method not in ("POST", "PATCH", "DELETE"):
            return ToolResult(success=False, content="Metodo invalido, usa POST, PATCH o DELETE.")
        async with httpx.AsyncClient(base_url=self._base_url, timeout=15, transport=self._transport) as client:
            resp = await client.request(method, path, json=body)
        if resp.status_code >= 400:
            return ToolResult(
                success=False, content=f"AlexOS respondio con error {resp.status_code}: {_truncate(resp.text)}"
            )
        _, content = _parse_response(resp)
        return ToolResult(success=True, content=f"Hecho: {method} {path}. {content}", data={})


def _parse_response(resp: httpx.Response) -> tuple[object | None, str]:
    try:
        data = resp.json()
    except ValueError:
        return None, _truncate(resp.text) or "(sin contenido)"
    return data, _truncate(json.dumps(data, ensure_ascii=False))


class AlexOSPlugin(Plugin):
    id = "alexos"
    name = "AlexOS"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        base_url = settings.alexos_base_url.rstrip("/")
        ctx.register_tool(AlexOSListModulesTool(base_url))
        ctx.register_tool(AlexOSGetTool(base_url))
        ctx.register_tool(AlexOSActionTool(base_url))
        log.info("AlexOS plugin ready (%s)", base_url)


PLUGIN = AlexOSPlugin
