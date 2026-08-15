# Project ALEX - Architecture

ALEX is a permanent, modular personal AI assistant that runs 24/7 on a
Raspberry Pi 4. This document explains the decisions behind the design and
how the pieces fit together.

## Design principles

1. **The Core never depends on a specific AI vendor, plugin, or client.**
   Everything talks through narrow interfaces (`AIProvider`, `Tool`,
   `Plugin`, the WebSocket protocol) so any piece can be swapped without
   touching the rest.
2. **The LLM never touches storage or side effects directly.** It calls
   Tools; Tools call `MemoryManager` (for data) or plugin code (for
   integrations); the `PermissionManager` gates every tool call. There is no
   path from "the model decided to" to "it happened" that skips permission
   checks.
3. **Local-first where it matters for privacy/latency, cloud where it's
   the only realistic option on this hardware.** Wake word detection and
   speech-to-text run fully on-device. The reasoning LLM does not - a
   Raspberry Pi 4 cannot run a genuinely useful conversational model at
   usable latency, so ALEX uses a hosted provider (NVIDIA NIM's free tier by
   default, or Anthropic Claude) for that step only. Only text (not audio)
   ever leaves the device, and only for that one call.
4. **No unnecessary Internet exposure.** ALEX binds to your LAN, requires a
   bearer token, and is meant to be reached from your own devices only.
   Remote access, when you want it, should go through Tailscale rather than
   port-forwarding.

## Component map

```
                          ┌────────────────────┐
                          │   Clients (WS/API)  │  desktop popup, future
                          │  clients/protocol.md│  Windows/AlexOS/voice UIs
                          └─────────▲───────────┘
                                    │ WebSocket + REST (token auth)
                          ┌─────────┴───────────┐
                          │   alex/server/*      │  FastAPI + WS, auth
                          └─────────▲───────────┘
                                    │
   ┌───────────┐            ┌──────┴───────┐            ┌───────────────┐
   │ Voice      │──text────▶│  ALEXCore     │◀──events──│ Plugins        │
   │ pipeline   │◀──speech──│  (core/core.py)│──tools───▶│ (system,       │
   │ (wake word,│           └──┬──┬──┬──┬────┘           │  reminders...) │
   │  STT, TTS) │              │  │  │  │                └───────────────┘
   └───────────┘               │  │  │  └────────────┐
                       ┌────────┘  │  └───────┐       │
                 ┌─────▼────┐ ┌────▼───┐ ┌────▼────┐ ┌▼──────────────┐
                 │ AI       │ │ Memory  │ │ Tools + │ │ Event Engine + │
                 │ provider │ │ Manager │ │ Perms   │ │ Notifications  │
                 │ (nvidia/ │ │ (SQLite)│ │         │ │                │
                 │ anthropic)│ └─────────┘ └─────────┘ └────────────────┘
                 └──────────┘
```

Everything is orchestrated by `ALEXCore` (`alex/core/core.py`), which is the
only module that knows about all the others. It's built once at startup by
`alex/server/app.py`'s FastAPI lifespan handler.

### Core plumbing (`alex/core/`)

- `event_bus.py` - internal async pub/sub. Decouples the voice pipeline,
  plugins, notifications and the WS layer from each other. E.g. the
  `NotificationManager` doesn't know WebSocket exists; it just publishes
  `"notification.created"` and `alex/server/ws.py` is the subscriber that
  turns that into bytes on a socket.
- `errors.py` - one exception hierarchy (`AlexError` and subclasses) used
  everywhere, so the API layer can catch one type and always respond safely.
- `core.py` - wiring + the conversational turn loop (see below).

### AI layer (`alex/ai/`)

`AIProvider` is an abstract interface (`complete()`, `health_check()`).
`NvidiaProvider` and `AnthropicProvider` implement it against their
respective (very different) tool-calling wire formats, normalizing both
into the same `AIResponse`/`ToolCall` dataclasses. `alex/ai/router.py`
picks one based on `ALEX_AI_PROVIDER`. **Nothing else in the codebase
imports `openai` or `anthropic`** - that's the whole point: switching
providers, or adding a third one later (e.g. a fully local model if
Raspberry Pi hardware ever gets there), only touches this package.

### Memory (`alex/memory/`)

SQLite (via `aiosqlite`), chosen because ALEX is a single-writer,
single-machine, low-throughput workload where SQLite's simplicity and
zero-ops nature win over running a separate DB server on a Pi. WAL mode is
enabled for safe concurrent reads while a write is in flight.

`MemoryManager` is the **only** thing that opens a query against the
database. It exposes:
- conversation history (short-term context, last N turns)
- long-term `memories` (freeform text, full-text searchable via SQLite
  FTS5, used for "remember this" style facts and continuity across
  sessions)
- structured `facts` (key/value, e.g. birthday, job)
- `preferences` (how the user wants ALEX to behave)
- `reminders` (used by the reminders plugin)

The LLM reaches all of this exclusively through **memory tools**
(`memory_remember`, `memory_recall`, `memory_forget`, `memory_set_fact`,
`memory_set_preference` - see `alex/tools/builtin/memory_tools.py`), each
with its own permission level. Forgetting is `CONFIRM`-gated because it's
destructive; saving/reading are not.

### Tools & permissions (`alex/tools/`)

Four permission levels (`alex/tools/base.py::PermissionLevel`):

| Level | Meaning | Example |
|---|---|---|
| `READ` | No side effects | `memory_recall`, `system_status`, `get_current_time` |
| `WRITE` | Easy-to-undo local side effects | `memory_remember`, `set_reminder` |
| `CONFIRM` | Needs explicit user go-ahead | `memory_forget` |
| `BLOCKED` | Never runs, ever | (reserved for future risky tools) |

`ToolRegistry.execute()` is the **only** way a tool body ever runs, and it
always calls `PermissionManager.authorize()` first. For `CONFIRM` tools,
`authorize()` raises `ConfirmationRequired` instead of letting the call
through - `ALEXCore` catches that, creates a notification with
Confirm/Cancel actions, and tells the user in plain language what it wants
to do and why it's waiting. The tool only actually executes once
`ALEXCore.resolve_pending_action()` is called (wired to `POST
/actions/{id}/confirm` and the WS `action.confirm` message) - via
`ToolRegistry.execute_confirmed()`, which is not reachable from the model's
tool-calling path at all. There is no way for the LLM to skip this.

### Plugins (`alex/plugins/`)

A `Plugin` contributes tools, event handlers, and scheduled background work
through a `PluginContext`, without the Core needing to know it exists ahead
of time - enabling it is a config line (`ALEX_ENABLED_PLUGINS`). Seven ship
today:

- **system** (`installed/system_plugin.py`) - a `system_status` READ tool,
  plus a 60s background check that raises `system.*` events when CPU temp,
  disk or memory get close to the limit on the Pi. Enabled by default.
- **reminders** (`installed/reminders_plugin.py`) - `set_reminder` /
  `list_reminders` / `cancel_reminder` tools, plus a 30s background check
  that raises `reminder.due` events when one comes due. Enabled by default.
- **home_assistant** (`installed/home_assistant_plugin.py`) - reads Home
  Assistant entity state and calls services over its REST API (bearer
  token auth). `ha_call_service` is CONFIRM-level since it controls real
  devices; the read tools are not.
- **email** (`installed/email_plugin.py`) - reads/marks-read Gmail over
  IMAP with an app password (no OAuth app registration needed). Background
  check surfaces new mail as a (stored, not pushed by default) event.
- **google_calendar** (`installed/google_calendar_plugin.py`) - lists,
  creates and deletes Calendar events via the Calendar v3 REST API,
  authenticated with a long-lived OAuth2 refresh token minted once via
  `scripts/google_oauth_auth.py` (run on a machine with a browser, not
  the Pi). Background check raises `calendar.upcoming` ~60 minutes before
  an event starts.
- **google_tasks** (`installed/google_tasks_plugin.py`) - lists, creates
  and completes Google Tasks via the Tasks v1 REST API. Shares its OAuth
  token-refresh logic with google_calendar via
  `alex/plugins/google_oauth.py` (same helper script, can even share one
  refresh token if minted with both scopes at once). Background check
  raises `task.due_soon` for tasks due within 24h.
- **ms_todo** (`installed/ms_todo_plugin.py`) - lists/creates/completes
  Microsoft To Do tasks via Graph, authenticated with the OAuth2
  device-code flow (no browser needed on the Pi at all - it notifies you
  with a URL + short code to approve from any device on first run).
  Background check raises `task.due_soon` for tasks due within 24h. Use
  this instead of google_tasks if you're on a Microsoft/Outlook account
  rather than Google's ecosystem.

The five integrations are disabled by default (each needs its own
credentials configured first - see `docs/INSTALL_RASPBERRY_PI.md` section
10) and, notably, add **zero new pip dependencies**: all OAuth/REST calls
go through `httpx` (already a core dependency) rather than each vendor's
SDK, kept consistent with the rest of the codebase's httpx-based AI
providers. Any future integration (music, browser/web, Windows-side
actions...) follows the same pattern: own module under `installed/`, own
tools, own auth handling internally, own event types. The Core, memory,
permission system and API never change to add one.

### Events & notifications (`alex/events/`, `alex/notifications/`)

Any plugin (or the Core itself) can raise an `Event` (source, type, title,
body, a 0..1 severity hint, optional actions). `EventEngine` scores it
(`0.6 * type_weight + 0.4 * source_severity`) and decides:

- score < 0.3 -> **ignored** (logged only)
- score < 0.65 -> **stored** (kept in the notifications table, not pushed)
- score >= 0.65 -> **notify** (pushed to clients), unless the same
  `dedupe_key` notified within the last 30 minutes (cooldown), in which
  case it's downgraded to stored - this is what stops a flapping metric
  from spamming you every minute.

This is intentionally simple, rule-based scoring rather than another LLM
call - it needs to be fast, cheap, and predictable, and "is this the kind
of thing that deserves a popup" is a small, stable set of rules
(reminders/calendar/tasks are high priority by default; routine system info
is low). `NotificationManager` persists the result and publishes
`"notification.created"`; `alex/server/ws.py` broadcasts it to every
connected client.

### Voice (`alex/voice/`)

Pipeline: **wake word (openWakeWord, local) -> record utterance -> STT
(faster-whisper, local) -> `ALEXCore.handle_user_message()` (same code path
as text/API) -> TTS (Piper, local) -> speak reply -> short follow-up window
(keep listening without repeating the wake word) -> back to passive
listening.**

No audio leaves the device at any point; only the transcribed text of your
request reaches whichever AI provider is configured, exactly like typing it
into `/chat` would. See `alex/voice/wakeword.py` for the important caveat
that "Alex" is not a stock openWakeWord keyword and needs a quick one-time
custom model training step (documented in
`docs/INSTALL_RASPBERRY_PI.md`) - `hey_jarvis` is the default keyword until
you do that, purely so the pipeline is testable immediately.

### Server (`alex/server/`)

FastAPI app exposing REST (`/health`, `/chat`, `/actions/*`,
`/notifications*`) and one WebSocket endpoint (`/ws`) - see
`clients/protocol.md` for the full wire protocol. Bearer-token auth
(`ALEX_API_TOKEN`) on everything except `/health`. The FastAPI `lifespan`
handler owns `ALEXCore`'s startup/shutdown (and the voice pipeline's, if
enabled) so a `SIGTERM` from systemd triggers a graceful shutdown (DB
closed, scheduler stopped, plugins given a chance to clean up) rather than
an abrupt kill.

### Clients (`clients/`)

`clients/protocol.md` is the contract. `clients/desktop_minimal/client.py`
is a small, real, cross-platform (Tk-based) reference client: connects over
WebSocket, shows a stacked always-on-top popup for notifications at/above a
configurable priority, supports per-notification actions (including
resolving `CONFIRM` pending actions), and reports back what you clicked.
It is intentionally minimal - no tray icon, no chat window - so it's fast
to build on for a real Windows client, an avatar UI, or "AlexOS" later
without the protocol changing.

`clients/web_console/index.html` is a second reference client: a
self-contained (no build step, no dependencies) HUD-styled chat interface,
mounted by the server itself at `/console/` (see `alex/server/app.py`).
Same protocol, same auth model (token entered client-side, held in
`localStorage`) - it exists to prove a browser-based client works over the
exact same contract as the desktop one, and to give a fast way to talk to
ALEX from any device without installing anything.

## Why these specific technology choices

| Concern | Choice | Why |
|---|---|---|
| Language/runtime | Python 3.11, asyncio | Best-supported ecosystem for every piece ALEX needs (faster-whisper, Piper, openWakeWord, FastAPI) with good enough performance on a Pi 4 for an I/O-bound assistant workload. |
| API/WS server | FastAPI + uvicorn | Native async, first-class WebSocket support, minimal boilerplate, good docs generation for free. |
| Database | SQLite (aiosqlite) + FTS5 | Zero ops, single file, plenty fast for one user's memory, built-in full-text search - no need for a separate DB server on a Pi. |
| Default AI provider | NVIDIA NIM (OpenAI-compatible) | Free hosted inference tier, no local GPU required, swappable via the `AIProvider` interface. |
| Alternate AI provider | Anthropic Claude | Already used for development; supported as a first-class, equally-weighted option, not a special case. |
| Wake word | openWakeWord | Local, CPU-only, ONNX models small enough for a Pi 4, actively maintained, supports custom keyword training. |
| STT | faster-whisper (CTranslate2) | Local, int8-quantized "small" model transcribes short utterances in a few seconds on Pi 4 CPU. |
| TTS | Piper | Purpose-built for small local devices; natural-sounding, fast, offline. |
| Scheduler | APScheduler (AsyncIO executor) | Simple in-process interval jobs for plugin background checks (system monitor, reminders) without another moving part/service. |
| Process supervision | systemd | Already on Raspberry Pi OS, gives auto-start-on-boot, auto-restart-on-crash, log integration (`journalctl`) for free. |

## What's deliberately not built yet

Per the project brief, this first version is backend-first: no rich UI, no
avatar, no camera/screen vision, no calendar/To Do/Home Assistant
integrations yet. The plugin system, event model, and client protocol are
built so all of those are additive later - new plugin modules and new
client implementations, not Core changes.
