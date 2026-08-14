# ALEX Client Protocol (v1)

ALEX's "brain" lives on the Raspberry Pi. Any device (Windows desktop, phone,
future AlexOS UI, ...) becomes a **client**: it connects over the local
network, gets pushed notifications/events, and can send text turns or
confirm/cancel pending actions. This document is the contract every client
implementation (starting with `clients/desktop_minimal/client.py`) follows.

## Transport

- **WebSocket** (persistent, real-time): `ws://<pi-host>:8787/ws?token=<API_TOKEN>&client_id=<id>`
  Used for push notifications and interactive chat.
- **REST** (request/response, stateless): `http://<pi-host>:8787/...`
  Used for one-off actions (confirming a pending action, fetching notification
  history, health checks) and by clients that don't want a persistent socket.

Both require the same bearer token (`ALEX_API_TOKEN` from the server's
`.env`), either as `?token=` on the WS URL or an `Authorization: Bearer <token>`
header on REST/WS handshake requests. There is no per-user login system -
ALEX is a single-owner assistant; the token is a shared secret between the
Pi and your own devices. Do not expose port 8787 to the public Internet -
use your LAN, or Tailscale for remote access.

## Message envelope

Every WebSocket message (both directions) is a single JSON object with a
`type` field:

```json
{ "type": "<message-type>", ...fields }
```

### Client -> Server

| type | fields | purpose |
|---|---|---|
| `chat.message` | `text` (string), `conversation_id` (string, optional) | Send a text turn, same path voice uses after STT. |
| `action.confirm` | `action_id` (string), `approved` (bool) | Resolve a CONFIRM-level pending tool action. |
| `ping` | - | Keepalive / connectivity check. |

### Server -> Client

| type | fields | purpose |
|---|---|---|
| `hello` | `assistant_name` | Sent immediately after a successful connection. |
| `chat.reply` | `conversation_id`, `reply`, `pending_action_id` (nullable) | Answer to a `chat.message`. |
| `notification` | `notification` (see below) | **Unsolicited push** - a new notification the Event Engine decided was worth surfacing. This is what drives the desktop overlay popup. |
| `action.result` | `action_id`, `success`, `message` | Result of an `action.confirm`. |
| `pong` | - | Reply to `ping`. |
| `error` | `message`, `code` | Something went wrong processing the last message. |

### Notification object

```json
{
  "id": "uuid",
  "source": "reminders",
  "title": "Recordatorio",
  "body": "Examen de calculo a las 9:00",
  "priority": 2,
  "actions": [
    { "id": "dismiss", "label": "Entendido" }
  ],
  "status": "pending",
  "created_at": "2026-08-14T20:00:00"
}
```

`priority` is an integer 0-3:

| value | meaning | suggested client behaviour |
|---|---|---|
| 0 | info | log only / no interruption |
| 1 | normal | subtle popup, auto-dismiss |
| 2 | high | visible overlay popup, stays until dismissed |
| 3 | critical | overlay popup, does not auto-dismiss, consider sound |

`actions` is a list of `{id, label}`, optionally with an `action_id` field
when the action must resolve a pending CONFIRM tool call (in that case the
client should send `action.confirm` over the WS, or `POST
/actions/{action_id}/confirm`, with `approved: true` for the "confirm"-style
action and `false` for "cancel"-style ones).

## REST endpoints

All require `Authorization: Bearer <ALEX_API_TOKEN>` except `/health`.

- `GET /health` -> `{status, ai_provider, ai_reachable, plugins, tools, voice_enabled}`
- `POST /chat` `{text, conversation_id?}` -> `{conversation_id, reply, pending_action_id}`
- `POST /actions/{action_id}/confirm` `{approved}` -> `{success, message}`
- `GET /actions/pending` -> list of pending confirmations
- `GET /notifications?limit=20&status=` -> list of notifications (history)
- `POST /notifications/{id}/status` `{status}` -> mark `delivered` / `dismissed` / `acted`

## Extending the protocol

New message types are additive - unknown `type` values are ignored (or
answered with `error`) rather than crashing the connection, so older clients
keep working as new server capabilities are added (voice-triggered avatar
state, camera/screen vision events, AlexOS UI hooks, etc.).
