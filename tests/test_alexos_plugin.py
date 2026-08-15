from __future__ import annotations

import httpx
import pytest

from alex.plugins.installed.alexos_plugin import AlexOSActionTool, AlexOSGetTool, AlexOSListModulesTool
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


def _transport(handler):
    return httpx.MockTransport(handler)


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request should have been made, got {request.method} {request.url}")


async def test_get_tool_is_read_level():
    assert AlexOSGetTool("http://x").permission_level == PermissionLevel.READ


async def test_action_tool_is_confirm_gated():
    assert AlexOSActionTool("http://x").permission_level == PermissionLevel.CONFIRM


async def test_list_modules_tool_is_read_level():
    assert AlexOSListModulesTool("http://x").permission_level == PermissionLevel.READ


async def test_get_rejects_paths_outside_api_v1_without_making_a_request():
    tool = AlexOSGetTool("http://alexos.local", transport=_transport(_unreachable))
    result = await tool.run(path="/etc/passwd")
    assert result.success is False
    assert "/api/v1/" in result.content


async def test_get_returns_json_content_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/modules/servers/stats"
        return httpx.Response(200, json={"cpu": 12, "ram": 40})

    tool = AlexOSGetTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run(path="/api/v1/modules/servers/stats")

    assert result.success is True
    assert result.data["response"] == {"cpu": 12, "ram": 40}
    assert "12" in result.content


async def test_get_surfaces_http_errors_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="AlexOS is unreachable")

    tool = AlexOSGetTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run(path="/api/v1/notifications")

    assert result.success is False
    assert "503" in result.content


async def test_action_rejects_paths_outside_api_v1_without_making_a_request():
    tool = AlexOSActionTool("http://alexos.local", transport=_transport(_unreachable))
    result = await tool.run(path="/not/api", method="POST")
    assert result.success is False
    assert "/api/v1/" in result.content


async def test_action_rejects_invalid_methods_without_making_a_request():
    tool = AlexOSActionTool("http://alexos.local", transport=_transport(_unreachable))
    result = await tool.run(path="/api/v1/modules/room/lights", method="GET")
    assert result.success is False
    assert "Metodo invalido" in result.content


async def test_action_posts_body_and_reports_success():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"on": True})

    tool = AlexOSActionTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run(path="/api/v1/modules/room/lights/light.salon", method="patch", body={"on": True})

    assert result.success is True
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/v1/modules/room/lights/light.salon"
    assert b'"on":true' in seen["body"]
    assert "Hecho" in result.content


async def test_action_surfaces_http_errors_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    tool = AlexOSActionTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run(path="/api/v1/modules/room/lights/nope", method="DELETE")

    assert result.success is False
    assert "404" in result.content


async def test_list_modules_formats_manifest_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/modules"
        return httpx.Response(
            200,
            json=[
                {
                    "manifest": {
                        "name": "room",
                        "description": "Lights and scenes.",
                        "routes": ["/lights", "/scenes"],
                    },
                    "hasBackend": True,
                    "hasFrontend": True,
                }
            ],
        )

    tool = AlexOSListModulesTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run()

    assert result.success is True
    assert "room" in result.content
    assert "/api/v1/modules/room/lights" in result.content
    assert len(result.data["modules"]) == 1


async def test_list_modules_handles_empty_install():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    tool = AlexOSListModulesTool("http://alexos.local", transport=_transport(handler))
    result = await tool.run()

    assert result.success is True
    assert "no tiene modulos" in result.content.lower()
