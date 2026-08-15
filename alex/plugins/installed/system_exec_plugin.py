"""
System exec plugin - lets ALEX run shell commands on the machine it runs
on. This is by far the most powerful and dangerous capability ALEX can
have: a shell command can read, modify or delete any file the ALEX process
can touch, install/remove software, or change system configuration.

Because of that, `run_shell_command` is CONFIRM-level with NO exceptions
and this plugin is NOT enabled by default - it must be explicitly added to
ALEX_ENABLED_PLUGINS. Every command (approved or not) is logged.

sudo caveat: commands run with no interactive TTY, so anything that prompts
for a password (most `sudo` usage) will simply hang until the timeout and
fail. Running privileged commands from here requires either configuring
narrowly-scoped passwordless sudo for specific binaries (see
docs/INSTALL_RASPBERRY_PI.md), or running that one-off command yourself.
"""
from __future__ import annotations

import asyncio
import logging

from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 180


class RunShellCommandTool(Tool):
    name = "run_shell_command"
    description = (
        "Ejecuta un comando de shell en el sistema donde corre ALEX (la Raspberry Pi). "
        "Acceso total: puede leer, modificar o borrar cualquier archivo, instalar o desinstalar "
        "software, y cambiar la configuracion del sistema. Usalo solo cuando el usuario pida "
        "explicitamente una accion a nivel de sistema (instalar algo, iniciar un servicio, revisar "
        "logs, etc). SIEMPRE requiere confirmacion explicita del usuario antes de ejecutarse - "
        "explica claramente que comando vas a correr y por que antes de pedirlo. Los comandos con "
        "'sudo' que piden contrasena se quedaran colgados y fallaran salvo que el usuario haya "
        "configurado sudo sin contrasena para ese comando concreto."
    )
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "El comando de shell a ejecutar."},
            "timeout_seconds": {
                "type": "integer",
                "description": f"Tiempo maximo de espera, por defecto {DEFAULT_TIMEOUT}s, maximo {MAX_TIMEOUT}s.",
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, timeout_seconds: int = DEFAULT_TIMEOUT) -> ToolResult:
        timeout = max(1, min(timeout_seconds, MAX_TIMEOUT))
        log.warning("EXECUTING SHELL COMMAND: %s (timeout=%ds)", command, timeout)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("Shell command timed out after %ds: %s", timeout, command)
            return ToolResult(
                success=False,
                content=f"El comando supero el tiempo limite ({timeout}s) y se ha cancelado.",
                data={"command": command, "timed_out": True},
            )

        stdout = _truncate(stdout_bytes.decode(errors="replace").strip())
        stderr = _truncate(stderr_bytes.decode(errors="replace").strip())
        exit_code = proc.returncode
        log.warning("Shell command finished (exit=%s): %s", exit_code, command)

        summary_parts = [f"Comando: {command}", f"Codigo de salida: {exit_code}"]
        if stdout:
            summary_parts.append(f"Salida:\n{stdout}")
        if stderr:
            summary_parts.append(f"Errores:\n{stderr}")

        return ToolResult(
            success=(exit_code == 0),
            content="\n".join(summary_parts),
            data={"command": command, "exit_code": exit_code, "stdout": stdout, "stderr": stderr},
        )


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... (truncado, {len(text) - MAX_OUTPUT_CHARS} caracteres mas)"


class SystemExecPlugin(Plugin):
    id = "system_exec"
    name = "System Exec"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        ctx.register_tool(RunShellCommandTool())
        log.warning(
            "System Exec plugin ready - run_shell_command is enabled (CONFIRM-gated). "
            "This gives ALEX full shell access to this machine when you approve a command."
        )


PLUGIN = SystemExecPlugin
