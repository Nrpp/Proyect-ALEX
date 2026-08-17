"""
Web plugin - lets ALEX read the actual content of a web page when asked
("mira esta pagina...", "que dice tal sitio", a link pasted in chat/voice).

No API key, no search engine integration (a keyless scraping-based search
was tried and dropped - see PR description; it's a shaky foundation to
build a "confirm before trusting" step on top of). Just a straight
GET + HTML-to-text extraction, same trust model as a person clicking a
link themselves: whatever the page returns is what gets read.
"""
from __future__ import annotations

import logging
from html.parser import HTMLParser

import httpx

from alex.config import get_settings
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 6000
# Tags whose contents are never meaningful page text.
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class _TextExtractor(HTMLParser):
    """Pulls the <title> and visible body text out of an HTML document,
    collapsing whitespace as it goes - good enough for an LLM to read a
    page's substance, not a faithful rendering."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        (self.title_parts if self._in_title else self.text_parts).append(stripped)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def extract_readable_text(html: str) -> tuple[str, str]:
    """Returns (title, body_text) from raw HTML. Never raises - malformed
    HTML just yields whatever HTMLParser managed to salvage."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        log.exception("HTML parsing failed, returning partial extraction")
    return extractor.title, extractor.text


def _truncate(text: str) -> str:
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + f"\n... (truncado, {len(text) - MAX_CONTENT_CHARS} caracteres mas)"


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Abre una URL y devuelve el titulo y el texto legible de la pagina, para poder responder "
        "preguntas sobre su contenido. Solo paginas publicas (sin login). Usa esto cuando el usuario "
        "pida revisar/leer/resumir una pagina web o un enlace concreto."
    )
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL completa, ej. 'https://example.com'."}},
        "required": ["url"],
    }

    def __init__(self, timeout_seconds: int, transport: httpx.BaseTransport | None = None):
        self._timeout = timeout_seconds
        self._transport = transport

    async def run(self, url: str) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, content="La URL debe empezar por http:// o https://.")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True, transport=self._transport,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ALEX-assistant/1.0)"},
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as e:
            return ToolResult(success=False, content=f"No se pudo acceder a la pagina: {e}")

        if resp.status_code >= 400:
            return ToolResult(success=False, content=f"La pagina respondio con error {resp.status_code}.")

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text" not in content_type:
            return ToolResult(success=False, content=f"El contenido no es texto/HTML legible (tipo: {content_type or 'desconocido'}).")

        title, text = extract_readable_text(resp.text)
        body = _truncate(text)
        header = f"Titulo: {title}\n\n" if title else ""
        return ToolResult(success=True, content=f"{header}{body}" or "(pagina sin texto legible)", data={"url": url, "title": title})


class WebPlugin(Plugin):
    id = "web"
    name = "Web"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        ctx.register_tool(WebFetchTool(settings.web_fetch_timeout_seconds))
        log.info("Web plugin ready")


PLUGIN = WebPlugin
