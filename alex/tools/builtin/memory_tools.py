"""
Memory tools - the ONLY interface the LLM has to persistent storage.

The model never sees a database connection or SQL. It calls these tools,
which call MemoryManager, which owns the actual SQLite access. This keeps
memory access observable (every read/write is a logged tool call) and lets
the PermissionManager gate destructive operations (forgetting requires
confirmation) without any of that logic living in the model layer.
"""
from __future__ import annotations

from alex.memory.manager import MemoryManager
from alex.tools.base import PermissionLevel, Tool, ToolResult


class RememberTool(Tool):
    name = "memory_remember"
    description = (
        "Guarda un recuerdo a largo plazo (un hecho, evento, detalle de un proyecto, etc.) "
        "para poder recuperarlo en conversaciones futuras."
    )
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "El contenido a recordar, en una o dos frases."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas opcionales."},
            "project": {"type": "string", "description": "Proyecto relacionado, si aplica."},
            "importance": {"type": "number", "description": "0 a 1, cuanto de importante es este recuerdo."},
        },
        "required": ["content"],
    }

    def __init__(self, memory: MemoryManager):
        self._memory = memory

    async def run(self, content: str, tags: list[str] | None = None, project: str | None = None,
                   importance: float = 0.5) -> ToolResult:
        memory_id = await self._memory.remember(content, tags=tags, project=project, importance=importance)
        return ToolResult(success=True, content=f"Recuerdo guardado (#{memory_id}).", data={"id": memory_id})


class RecallMemoryTool(Tool):
    name = "memory_recall"
    description = "Busca en la memoria a largo plazo recuerdos relevantes para una consulta."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Que buscar en la memoria."},
            "project": {"type": "string", "description": "Filtrar por proyecto, opcional."},
        },
        "required": ["query"],
    }

    def __init__(self, memory: MemoryManager):
        self._memory = memory

    async def run(self, query: str, project: str | None = None) -> ToolResult:
        results = await self._memory.recall(query, project=project)
        if not results:
            return ToolResult(success=True, content="No se encontraron recuerdos relacionados.")
        summary = "\n".join(f"- ({m.id}) {m.content}" for m in results)
        return ToolResult(success=True, content=summary, data={"results": [r.__dict__ for r in results]})


class ForgetMemoryTool(Tool):
    name = "memory_forget"
    description = "Elimina permanentemente un recuerdo guardado por su id. Accion destructiva."
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {"memory_id": {"type": "integer", "description": "Id del recuerdo a olvidar."}},
        "required": ["memory_id"],
    }

    def __init__(self, memory: MemoryManager):
        self._memory = memory

    async def run(self, memory_id: int) -> ToolResult:
        ok = await self._memory.forget(memory_id)
        msg = f"Recuerdo #{memory_id} olvidado." if ok else f"No existia el recuerdo #{memory_id}."
        return ToolResult(success=ok, content=msg)


class SetFactTool(Tool):
    name = "memory_set_fact"
    description = "Guarda o actualiza un hecho estructurado clave-valor sobre el usuario o su vida."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Identificador corto del hecho, ej. 'cumpleanos'."},
            "value": {"type": "string", "description": "Valor del hecho."},
            "category": {"type": "string", "description": "Categoria, ej. 'personal', 'trabajo'."},
        },
        "required": ["key", "value"],
    }

    def __init__(self, memory: MemoryManager):
        self._memory = memory

    async def run(self, key: str, value: str, category: str = "general") -> ToolResult:
        await self._memory.set_fact(key, value, category=category)
        return ToolResult(success=True, content=f"Hecho guardado: {key} = {value}.")


class SetPreferenceTool(Tool):
    name = "memory_set_preference"
    description = "Guarda una preferencia del usuario sobre como debe comportarse el asistente."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Nombre de la preferencia."},
            "value": {"type": "string", "description": "Valor de la preferencia."},
        },
        "required": ["key", "value"],
    }

    def __init__(self, memory: MemoryManager):
        self._memory = memory

    async def run(self, key: str, value: str) -> ToolResult:
        await self._memory.set_preference(key, value)
        return ToolResult(success=True, content=f"Preferencia guardada: {key} = {value}.")
