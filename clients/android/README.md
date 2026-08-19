# ALEX Android client

A native Android app that keeps a persistent background connection to ALEX
(see `clients/protocol.md`) so your phone can receive reminders/events as
real Android notifications, and show an on-top overlay for anything ALEX
marks as truly important - the mobile equivalent of
`clients/desktop_minimal`. It also has a **Chat** screen (`ChatActivity`)
for talking to ALEX directly, the equivalent of what iOS gets by adding
`/console/` (the web console PWA) to its home screen - Android has no
matching "install a web page as an app" story built into this app, so it's
a real screen instead.

## What it does

- **`AlexConnectionService`** - a foreground service that holds the
  WebSocket connection open (`ws://<host>:<port>/ws`) for as long as you
  want it running, with automatic reconnect/backoff. A small persistent
  notification shows connection status (required by Android for any
  foreground service).
- Every notification ALEX pushes becomes a normal Android notification
  (in a priority-matched channel, so you can mute/configure each level from
  Android's own notification settings).
- Notifications at/above a configurable priority (default: **high**, level
  2) additionally show as a HUD-style overlay drawn **on top of whatever
  app you're using** - same visual language as `clients/web_console`.
  Requires the "draw over other apps" permission.
- Notification/overlay actions (Confirm/Cancel/Dismiss) call the same REST
  endpoints as every other client (`POST /actions/{id}/confirm`,
  `POST /notifications/{id}/status`).
- Optional: start automatically on phone boot.
- **`ChatActivity`** ("CHAT CON ALEX" on the main screen) - a text
  conversation with ALEX, same `chat.message`/`chat.reply` WebSocket
  messages as `clients/web_console`, same "ALEX_"/"TU_" labeling for a
  consistent look across clients. Opens its own short-lived WebSocket
  (closed when you leave the screen) rather than reusing
  `AlexConnectionService`'s - the server already supports any number of
  simultaneous clients per device, so this stays simple and doesn't touch
  the foreground service's reconnect/notification logic. The background
  service (if running) keeps receiving push notifications independently,
  whether or not the Chat screen is open.

## Build

1. Open the `clients/android/` folder as a project in **Android Studio**
   (Koala/2024.1 or newer recommended). Let it sync - if the Gradle wrapper
   is missing, Android Studio will offer to generate it automatically
   (this repo doesn't commit the wrapper's binary jar).
2. Build > Make Project, or `Run` on a connected device/emulator (Android
   8.0 / API 26 or newer).

Command line (with the Android SDK installed and `ANDROID_HOME` set):

```bash
cd clients/android
./gradlew assembleDebug   # or: gradle assembleDebug
```

The debug APK lands at `app/build/outputs/apk/debug/app-debug.apk` -
install it with `adb install app-debug.apk` or by copying it to the phone.

> This client was actually built (`assembleDebug`, not just read) against
> Android SDK 34 / Gradle 8.14.3 / AGP 8.5.0 / Kotlin 1.9.24 while writing
> this project - `BUILD SUCCESSFUL`, zero errors, zero warnings, valid
> manifest/permissions verified with `aapt dump badging`. Re-verified
> (`BUILD SUCCESSFUL` again) after adding `ChatActivity`. What that
> doesn't cover: the actual WebSocket connection, overlay permission flow,
> chat round-trip, and notification behavior on a real device still need
> to be verified on your phone - a successful build proves the code
> compiles and packages correctly, not that the runtime behavior is
> correct.

## Setup on the phone

1. Install the APK, open the app.
2. Enter **Host** (your Pi's LAN IP or `.local` name, or its Tailscale
   address if you're off-network), **Puerto** (`8787`), and **Token**
   (the same `ALEX_API_TOKEN` from the Pi's `.env`). Tap **GUARDAR**.
3. Tap **CONCEDER PERMISO DE SUPERPOSICION** and grant "display over other
   apps" for ALEX in the system settings screen that opens.
4. Android will also prompt for notification permission on first launch
   (Android 13+) - allow it.
5. Tap **INICIAR SERVICIO**. You should see a persistent low-priority
   "ALEX - Conectado" notification.
6. Trigger a test notification from the Pi (e.g. the reminder test in
   `docs/INSTALL_RASPBERRY_PI.md` step 6) - it should arrive as a normal
   notification, and if its priority is 2+ also pop up as an overlay on
   top of whatever app you're in.
7. Optionally enable **"Iniciar automaticamente al arrancar el telefono"**
   so the service comes back after a reboot.
8. Tap **CHAT CON ALEX** any time to open a text conversation - it connects
   on its own the moment you open the screen, no need to have the
   background service running first.

## Notes / known limitations

- Android aggressively manages background processes on some OEM skins
  (Xiaomi/MIUI, Huawei, some Samsung configurations) beyond stock
  behavior - if the service keeps getting killed, look for that
  manufacturer's battery-optimization exemption setting for this app.
- The overlay auto-dismisses after 15s for priority 0-2; priority 3
  (critical) stays until you tap an action.
- Chat history in `ChatActivity` isn't persisted locally - it's just the
  in-memory log for that screen session (ALEX's own conversation memory on
  the server side is unaffected; reopening Chat continues the same
  conversation, you just don't see the earlier lines again on this
  screen). `clients/web_console/` and `clients/desktop_minimal/` remain
  valid alternatives if you'd rather chat from a browser or desktop.
