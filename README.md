# Project ALEX

ALEX is Nicolas's permanent personal AI assistant: a 24/7 backend service
designed to run on a Raspberry Pi 4, with a real memory, real tools gated by
a permission system, a plugin architecture for integrations, an event
engine that decides what's actually worth interrupting you for, and a
local, always-listening voice pipeline (wake word -> STT -> AI/tools/memory
-> TTS). Any device on your network can connect as a client over WebSocket
to chat with ALEX and receive proactive notifications.

This is not a chatbot demo - every component listed below is real,
implemented, and wired to the others. See `docs/ARCHITECTURE.md` for the
full design rationale and `docs/INSTALL_RASPBERRY_PI.md` for step-by-step
setup and verification on real hardware.

## What's here

- **Core** (`alex/core/`) - orchestrator, event bus, error handling.
- **AI layer** (`alex/ai/`) - provider-agnostic interface; ships with NVIDIA
  NIM (free tier, default) and Anthropic Claude, swappable via config.
- **Memory** (`alex/memory/`) - SQLite-backed conversation history,
  long-term searchable memories, facts, preferences, reminders - accessed
  only through `MemoryManager`, never raw SQL from anywhere else.
- **Tools & permissions** (`alex/tools/`) - READ / WRITE / CONFIRM / BLOCKED
  levels; the LLM cannot execute a `CONFIRM` tool without you approving it
  through a notification.
- **Plugins** (`alex/plugins/`) - add integrations without touching the
  Core. Ships with `system` (Pi health monitoring), `reminders`, and
  optional integrations for `home_assistant`, `email` (Gmail/IMAP),
  `google_calendar`, `google_tasks` and `ms_todo` (Microsoft To Do) - see
  `docs/INSTALL_RASPBERRY_PI.md` section 10 for credential setup. Also
  ships `system_exec` - a CONFIRM-gated `run_shell_command` tool that gives
  ALEX full shell access to the Pi when you approve a command. High risk,
  not enabled by default; read section 11 before turning it on.
- **Events & notifications** (`alex/events/`, `alex/notifications/`) - rule
  based importance scoring decides ignore/store/notify, with per-event-type
  cooldowns so you don't get spammed.
- **Voice** (`alex/voice/`) - openWakeWord (local wake word) + faster-whisper
  (local STT) + Piper (local TTS). No audio leaves the device.
- **Server** (`alex/server/`) - FastAPI REST + WebSocket API, token-authed,
  LAN-first.
- **Clients** (`clients/`) - `protocol.md` defines the wire contract;
  `desktop_minimal/` is a working cross-platform popup-notification client;
  `web_console/` is a HUD-style browser chat client, served directly by
  ALEX at `/console/`.

## Quick start (development machine, no Pi needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set ALEX_API_TOKEN and ALEX_NVIDIA_API_KEY (or ALEX_ANTHROPIC_API_KEY)
python -m alex.main
```

Then:

```bash
curl http://localhost:8787/health
curl -X POST http://localhost:8787/chat \
  -H "Authorization: Bearer $(grep ALEX_API_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola Alex"}'
```

Run the test suite:

```bash
pip install pytest pytest-asyncio
pytest -q
```

## Deploying on a Raspberry Pi 4

See **`docs/INSTALL_RASPBERRY_PI.md`** for the full guide: system
dependencies, the systemd service (auto-start on boot, auto-restart on
crash), voice setup (microphone, Piper voice download, wake word training),
and a checklist to verify memory, tools, notifications and the desktop
client all actually work on your hardware.

## Configuration

All configuration is environment variables (see `.env.example` for the full
annotated list), loaded from `.env` - never commit that file. Key ones:

| Variable | Purpose |
|---|---|
| `ALEX_API_TOKEN` | Shared secret clients must present. Generate with `openssl rand -hex 32`. |
| `ALEX_AI_PROVIDER` | `nvidia` (default, free tier) or `anthropic`. |
| `ALEX_ENABLED_PLUGINS` | JSON list of plugin ids to load, e.g. `["system","reminders"]`. |
| `ALEX_VOICE_ENABLED` | `true` to start the wake-word/STT/TTS pipeline. |

## Extending ALEX

- **New integration** (calendar, Microsoft To Do, email, Home Assistant,
  ...): add a module under `alex/plugins/installed/`, implement `Plugin`,
  register your tools/event handlers in `setup()`. No Core changes needed -
  see `alex/plugins/installed/reminders_plugin.py` as the reference.
- **New client** (native Windows app, avatar UI, AlexOS): implement
  `clients/protocol.md` against the WebSocket/REST API. The desktop
  overlay client is the minimal reference implementation.
- **New AI provider**: implement `alex.ai.base.AIProvider` and register it
  in `alex.ai.router.build_ai_provider`.

## Status

First functional version: backend is fully wired end-to-end (memory, AI
tool-calling loop with permission gating, plugins, event-driven
notifications, WebSocket push, voice pipeline). No graphical interface yet
by design - see `docs/ARCHITECTURE.md` for what's intentionally deferred.
