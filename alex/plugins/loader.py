"""
PluginManager - discovers and loads plugins listed in ALEX_ENABLED_PLUGINS.

Plugins live in `alex/plugins/installed/<id>_plugin.py` and must expose a
module-level `PLUGIN` attribute pointing at their `Plugin` subclass. This is
intentionally simple (no entry_points/setuptools plugin discovery) since
ALEX runs as a single deployed app, not a package other people pip-install
plugins into - yet. Swapping to entry-point discovery later is a
loader-only change.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from alex.core.errors import PluginError
from alex.plugins.base import Plugin, PluginContext

log = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

    async def load(self, plugin_id: str, ctx_factory, plugin_config: dict[str, Any]) -> None:
        module_name = f"alex.plugins.installed.{plugin_id}_plugin"
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            raise PluginError(f"No se pudo cargar el plugin '{plugin_id}': {e}") from e

        plugin_cls = getattr(module, "PLUGIN", None)
        if plugin_cls is None or not issubclass(plugin_cls, Plugin):
            raise PluginError(f"El modulo '{module_name}' no define PLUGIN (subclase de Plugin)")

        plugin: Plugin = plugin_cls()
        ctx: PluginContext = ctx_factory(plugin_config)
        try:
            await plugin.setup(ctx)
        except Exception as e:
            raise PluginError(f"Fallo al inicializar el plugin '{plugin_id}': {e}") from e

        self._plugins[plugin.id] = plugin
        log.info("Plugin cargado: %s v%s", plugin.name, plugin.version)

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    async def shutdown_all(self) -> None:
        for plugin in self._plugins.values():
            try:
                await plugin.shutdown()
            except Exception:
                log.exception("Error shutting down plugin %s", plugin.id)
