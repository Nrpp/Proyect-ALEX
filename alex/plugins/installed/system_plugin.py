"""
System plugin - gives ALEX visibility into the Raspberry Pi it runs on.

Contributes:
  - a READ tool `system_status` the model can call when asked "how's the Pi doing?"
  - a background check every 60s that raises system.* events (CPU temp, disk,
    memory) into the Event Engine, so problems become proactive notifications
    instead of something you only find out by asking.

This is the reference example for how a plugin adds both a tool AND
autonomous event-driven behaviour without touching the Core.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")

CPU_TEMP_WARN_C = 75.0
DISK_WARN_PERCENT = 90.0
MEM_WARN_PERCENT = 90.0


def _read_cpu_temp_c() -> float | None:
    try:
        if _THERMAL_ZONE.exists():
            return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        pass
    try:
        import psutil

        temps = psutil.sensors_temperatures()
        for entries in temps.values():
            if entries:
                return entries[0].current
    except Exception:
        pass
    return None


def _snapshot() -> dict:
    import psutil

    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_temp_c": _read_cpu_temp_c(),
        "memory_percent": mem.percent,
        "disk_percent": disk.percent,
        "uptime_seconds": time.time() - psutil.boot_time(),
    }


class SystemStatusTool(Tool):
    name = "system_status"
    description = "Devuelve el estado actual de la Raspberry Pi: CPU, temperatura, memoria, disco y uptime."
    permission_level = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> ToolResult:
        snap = _snapshot()
        hours = snap["uptime_seconds"] / 3600
        temp_str = f"{snap['cpu_temp_c']:.1f}C" if snap["cpu_temp_c"] is not None else "N/D"
        summary = (
            f"CPU {snap['cpu_percent']:.0f}% (temp {temp_str}), "
            f"memoria {snap['memory_percent']:.0f}%, disco {snap['disk_percent']:.0f}%, "
            f"encendido hace {hours:.1f}h."
        )
        return ToolResult(success=True, content=summary, data=snap)


class SystemPlugin(Plugin):
    id = "system"
    name = "System Monitor"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        ctx.register_tool(SystemStatusTool())
        ctx.schedule_interval(lambda: self._check(ctx), 60.0, "system_plugin_check")
        log.info("System plugin ready (checking every 60s)")

    async def _check(self, ctx: PluginContext) -> None:
        try:
            snap = _snapshot()
        except Exception:
            log.exception("System check failed")
            return

        if snap["cpu_temp_c"] is not None and snap["cpu_temp_c"] >= CPU_TEMP_WARN_C:
            await ctx.emit_event(Event(
                source="system", type="system.cpu_temp_high",
                title="Temperatura de la CPU alta",
                body=f"La CPU esta a {snap['cpu_temp_c']:.1f}C. Revisa la ventilacion.",
                severity=0.8, dedupe_key="system:cpu_temp",
            ))
        if snap["disk_percent"] >= DISK_WARN_PERCENT:
            await ctx.emit_event(Event(
                source="system", type="system.disk_high",
                title="Poco espacio en disco",
                body=f"El disco esta al {snap['disk_percent']:.0f}% de uso.",
                severity=0.7, dedupe_key="system:disk",
            ))
        if snap["memory_percent"] >= MEM_WARN_PERCENT:
            await ctx.emit_event(Event(
                source="system", type="system.error",
                title="Memoria RAM casi agotada",
                body=f"La RAM esta al {snap['memory_percent']:.0f}% de uso.",
                severity=0.7, dedupe_key="system:memory",
            ))


PLUGIN = SystemPlugin
