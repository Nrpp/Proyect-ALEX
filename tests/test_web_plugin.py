from __future__ import annotations

import httpx
import pytest

from alex.plugins.installed.web_plugin import WebFetchTool, extract_readable_text
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_web_fetch_tool_is_read_level():
    assert WebFetchTool(10).permission_level == PermissionLevel.READ


async def test_extract_readable_text_pulls_title_and_body():
    html = "<html><head><title> Hola Mundo </title></head><body><h1>Titulo</h1><p>Texto de prueba.</p></body></html>"
    title, text = extract_readable_text(html)
    assert title == "Hola Mundo"
    assert "Titulo" in text
    assert "Texto de prueba." in text


async def test_extract_readable_text_skips_script_and_style():
    html = "<html><body><script>alert('x')</script><style>.a{}</style><p>Visible</p></body></html>"
    _, text = extract_readable_text(html)
    assert "alert" not in text
    assert "Visible" in text


async def test_extract_readable_text_never_raises_on_malformed_html():
    title, text = extract_readable_text("<html><p>unclosed <b>tags")
    assert isinstance(title, str)
    assert "unclosed" in text


async def test_run_rejects_non_http_urls_without_making_a_request():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should have been made")

    tool = WebFetchTool(10, transport=_transport(unreachable))
    result = await tool.run(url="ftp://example.com")
    assert result.success is False
    assert "http" in result.content


async def test_run_returns_title_and_text_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>Pagina de prueba</title></head><body><p>Contenido real.</p></body></html>",
        )

    tool = WebFetchTool(10, transport=_transport(handler))
    result = await tool.run(url="https://example.com")

    assert result.success is True
    assert "Pagina de prueba" in result.content
    assert "Contenido real." in result.content
    assert result.data["title"] == "Pagina de prueba"


async def test_run_surfaces_http_errors_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/html"}, text="not found")

    tool = WebFetchTool(10, transport=_transport(handler))
    result = await tool.run(url="https://example.com/missing")

    assert result.success is False
    assert "404" in result.content


async def test_run_rejects_non_text_content_types():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    tool = WebFetchTool(10, transport=_transport(handler))
    result = await tool.run(url="https://example.com/doc.pdf")

    assert result.success is False
    assert "application/pdf" in result.content


async def test_run_handles_connection_errors_gracefully():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    tool = WebFetchTool(10, transport=_transport(handler))
    result = await tool.run(url="https://unreachable.example")

    assert result.success is False
    assert "no se pudo" in result.content.lower() or "boom" in result.content.lower()
