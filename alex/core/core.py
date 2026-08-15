"""
ALEXCore - the central orchestrator.

Wires together Memory, AI, Tools/Permissions, Plugins, Events and
Notifications, and exposes the handful of entry points the server (API/WS)
and voice pipeline actually call:

  - handle_user_message(text, ...)   -> one conversational turn
  - resolve_pending_action(id, ok)   -> user confirmed/cancelled a CONFIRM tool
  - raise_event(event)               -> feed an Event into the Event Engine
  - health()                         -> for the /health endpoint

Nothing outside this file knows how memory/AI/tools/plugins fit together -
that keeps every other module independently testable and swappable.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from alex.ai.base import AIProvider, ChatMessage, ToolCall
from alex.ai.prompts import build_system_prompt
from alex.ai.router import build_ai_provider
from alex.config import Settings
from alex.core.errors import AlexError, ConfirmationRequired, PermissionDenied, ToolError
from alex.core.event_bus import EventBus
from alex.events.engine import EventEngine
from alex.events.models import Event
from alex.memory.db import Database
from alex.memory.manager import MemoryManager
from alex.notifications.manager import NotificationManager
from alex.plugins.base import PluginContext
from alex.plugins.loader import PluginManager
from alex.tools.builtin import get_builtin_tools
from alex.tools.permissions import PermissionManager
from alex.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class ALEXCore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = EventBus()
        self.db = Database(settings.db_path)
        self.memory: MemoryManager | None = None
        self.permissions = PermissionManager(blocked_tools=settings.blocked_tools)
        self.tools = ToolRegistry(self.permissions)
        self.ai: AIProvider = build_ai_provider(settings)
        self.notifications: NotificationManager | None = None
        self.events: EventEngine | None = None
        self.plugins = PluginManager()
        self.scheduler = AsyncIOScheduler()
        self._started = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        await self.db.connect()
        self.memory = MemoryManager(
            self.db,
            recent_messages=self.settings.memory_recent_messages,
            max_facts_in_prompt=self.settings.memory_max_facts_in_prompt,
        )
        self.notifications = NotificationManager(self.db, self.event_bus)
        self.events = EventEngine(
            self.notifications,
            self.event_bus,
            notify_threshold=0.65,
            cooldown_seconds=1800,
        )

        for tool in get_builtin_tools(self.memory, self.settings):
            self.tools.register(tool)

        await self._load_plugins()

        self.scheduler.start()
        self._started = True
        log.info(
            "ALEX Core started (provider=%s, plugins=%s, tools=%d)",
            self.ai.name, [p.id for p in self.plugins.all()], len(self.tools.specs()),
        )

    async def shutdown(self) -> None:
        log.info("Shutting down ALEX Core...")
        await self.event_bus.publish("system.shutdown", None)
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            log.exception("Scheduler shutdown failed")
        await self.plugins.shutdown_all()
        await self.db.close()
        self._started = False
        log.info("ALEX Core stopped cleanly")

    async def health(self) -> dict:
        ai_ok = await self.ai.health_check() if self._started else False
        return {
            "status": "ok" if self._started else "starting",
            "ai_provider": self.ai.name,
            "ai_reachable": ai_ok,
            "plugins": [p.id for p in self.plugins.all()],
            "tools": self.tools.names(),
            "voice_enabled": self.settings.voice_enabled,
        }

    async def _load_plugins(self) -> None:
        for plugin_id in self.settings.enabled_plugins:
            try:
                await self.plugins.load(plugin_id, self._make_plugin_context, plugin_config={})
            except AlexError as e:
                log.error("Skipping plugin '%s': %s", plugin_id, e.message)

    def _make_plugin_context(self, plugin_config: dict) -> PluginContext:
        return PluginContext(
            event_bus=self.event_bus,
            memory=self.memory,
            register_tool=self.tools.register,
            emit_event=self.raise_event,
            schedule_interval=self._schedule_interval,
            plugin_config=plugin_config,
        )

    def _schedule_interval(self, func, seconds: float, job_id: str) -> None:
        # Plugins pass a lambda wrapping a bound async method (e.g.
        # `lambda: self._check(ctx)`). A bare lambda is NOT itself a
        # coroutine function even though calling it returns one, so
        # APScheduler's AsyncIOExecutor can't tell it needs awaiting - it
        # runs the lambda in a worker thread and discards the resulting
        # coroutine object unawaited (silently, no error - just a
        # "coroutine was never awaited" RuntimeWarning at GC time, and the
        # plugin's check logic never actually running). Wrapping in a real
        # `async def` fixes this for every plugin at once.
        async def runner() -> None:
            await func()

        self.scheduler.add_job(runner, "interval", seconds=seconds, id=job_id, replace_existing=True)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    async def raise_event(self, event: Event) -> None:
        await self.events.handle(event)

    # ------------------------------------------------------------------ #
    # Conversation
    # ------------------------------------------------------------------ #
    async def handle_user_message(
        self, text: str, *, conversation_id: str | None = None, channel: str = "voice"
    ) -> dict:
        """
        Runs one full conversational turn: memory context -> AI -> tool loop
        (respecting permissions) -> final reply, persisted to memory.
        Returns {"conversation_id", "reply", "pending_action_id"} - the last
        key is set only if the turn stopped to ask for a confirmation.
        """
        if conversation_id is None:
            conversation_id = await self.memory.latest_conversation_id(channel)
            if conversation_id is None:
                conversation_id = await self.memory.start_conversation(channel)

        await self.memory.add_message(conversation_id, "user", text)
        context = await self.memory.build_context_bundle(conversation_id, text)
        system_prompt = build_system_prompt(self.settings.assistant_name, self.settings.owner_name, context)

        messages: list[ChatMessage] = [
            ChatMessage(role=m.role, content=m.content) for m in context["recent_messages"]
        ]
        tool_specs = self.tools.specs()

        try:
            reply_text, pending_action_id = await asyncio.wait_for(
                self._run_conversation_loop(messages, tool_specs, system_prompt),
                timeout=self.settings.ai_turn_timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Bounds the WHOLE turn (all hops combined), not just one AI call -
            # a model that loops through several tool calls without ever
            # finishing could otherwise still hang past ai_request_timeout_seconds.
            log.warning(
                "Conversational turn exceeded ai_turn_timeout_seconds=%ds, aborting",
                self.settings.ai_turn_timeout_seconds,
            )
            reply_text = "Esto esta tardando demasiado. Intentalo de nuevo, quizas con una peticion mas simple."
            pending_action_id = None

        if reply_text:
            await self.memory.add_message(conversation_id, "assistant", reply_text)
        await self.event_bus.publish("message.outgoing", {"conversation_id": conversation_id, "text": reply_text})

        return {
            "conversation_id": conversation_id,
            "reply": reply_text,
            "pending_action_id": pending_action_id,
        }

    async def _run_conversation_loop(
        self, messages: list[ChatMessage], tool_specs: list, system_prompt: str
    ) -> tuple[str, str | None]:
        """The AI -> tool -> AI hop loop, extracted so the whole thing can be
        wrapped in a single overall timeout by the caller (see
        ai_turn_timeout_seconds) - bounding total turn latency regardless of
        how many hops the model takes, not just the latency of one hop."""
        pending_action_id: str | None = None
        reply_text = ""

        for _hop in range(self.settings.ai_max_tool_hops):
            try:
                response = await asyncio.wait_for(
                    self.ai.complete(
                        messages,
                        system=system_prompt,
                        tools=tool_specs,
                        max_tokens=self.settings.ai_max_tokens,
                        temperature=self.settings.ai_temperature,
                    ),
                    timeout=self.settings.ai_request_timeout_seconds,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "AI provider '%s' timed out after %ds on hop %d",
                    self.ai.name, self.settings.ai_request_timeout_seconds, _hop,
                )
                reply_text = (
                    "El proveedor de IA esta tardando demasiado en responder. "
                    "Intentalo de nuevo en un momento."
                )
                break

            if not response.wants_tool_call:
                reply_text = response.content or ""
                break

            messages.append(ChatMessage(role="assistant", content=response.content or "", tool_calls=response.tool_calls))

            stop_for_confirmation = False
            for call in response.tool_calls:
                tool_message, confirm_action_id = await self._run_tool_call(call)
                if tool_message is None:
                    # ConfirmationRequired: bail out of the loop entirely for this turn.
                    pending_action_id = confirm_action_id
                    tool = self.tools.get(call.name)
                    reply_text = (
                        f"Antes de hacerlo necesito tu confirmacion: {tool.description if tool else call.name}. "
                        f"Te he enviado una notificacion para confirmar o cancelar."
                    )
                    await self.notifications.create(
                        source="alex",
                        title="Confirmacion necesaria",
                        body=reply_text,
                        priority=2,
                        actions=[
                            {"id": "confirm", "label": "Confirmar", "action_id": pending_action_id},
                            {"id": "cancel", "label": "Cancelar", "action_id": pending_action_id},
                        ],
                    )
                    stop_for_confirmation = True
                    break
                messages.append(tool_message)

            if stop_for_confirmation:
                break
        else:
            reply_text = reply_text or "He hecho varias comprobaciones pero necesito que me lo repitas de otra forma."

        return reply_text, pending_action_id

    async def _run_tool_call(self, call: ToolCall) -> tuple[ChatMessage | None, str | None]:
        """Returns (tool-result ChatMessage, None), or (None, action_id) on ConfirmationRequired."""
        try:
            result = await self.tools.execute(call.name, call.arguments)
            msg = ChatMessage(role="tool", content=result.content, tool_call_id=call.id, name=call.name)
            return msg, None
        except ConfirmationRequired as e:
            return None, e.action_id
        except PermissionDenied as e:
            msg = ChatMessage(role="tool", content=f"Denegado: {e.message}", tool_call_id=call.id, name=call.name)
            return msg, None
        except ToolError as e:
            msg = ChatMessage(role="tool", content=f"Error: {e.message}", tool_call_id=call.id, name=call.name)
            return msg, None

    # ------------------------------------------------------------------ #
    # Confirmation resolution (called from the API when the user confirms/cancels)
    # ------------------------------------------------------------------ #
    async def resolve_pending_action(self, action_id: str, approved: bool) -> dict:
        action = self.permissions.pop_pending(action_id)
        if action is None:
            return {"success": False, "message": "Esa accion ya no esta pendiente o no existe."}

        if not approved:
            await self.notifications.create(
                source="alex", title="Accion cancelada",
                body=f"Se cancelo: {action.tool_name}", priority=0,
            )
            return {"success": True, "message": "Accion cancelada."}

        try:
            result = await self.tools.execute_confirmed(action.tool_name, action.arguments)
        except ToolError as e:
            await self.notifications.create(
                source="alex", title="La accion fallo", body=e.message, priority=2,
            )
            return {"success": False, "message": e.message}

        await self.notifications.create(
            source="alex", title="Accion completada", body=result.content, priority=1,
        )
        conversation_id = await self.memory.latest_conversation_id("voice")
        if conversation_id:
            await self.memory.add_message(conversation_id, "assistant", f"Hecho: {result.content}")
        return {"success": True, "message": result.content}
