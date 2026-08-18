# Installing ALEX on a Raspberry Pi 4

Target: Raspberry Pi 4 (2GB+ RAM, 4GB+ recommended if voice is enabled),
Raspberry Pi OS Bookworm 64-bit. A USB microphone (or a USB sound card + any
mic) and speakers/headphones plugged in if you want voice.

## 1. Get the code onto the Pi

```bash
git clone <this-repo-url> Proyect-ALEX
cd Proyect-ALEX
```

## 2. Run the installer

Backend only (recommended first - get text/API working before adding voice):

```bash
./scripts/install_raspberry_pi.sh
```

With voice dependencies (wake word/STT/TTS, heavier install):

```bash
./scripts/install_raspberry_pi.sh --with-voice
```

**Never run this script with `sudo`** - it calls `sudo` itself for the
specific steps that need it (`apt`, `systemctl`). Running the whole thing as
root creates a root-owned `.venv` that `alex.service` (which runs as your
normal user) then can't read; the script refuses to run as root for this
reason. If you already did this by mistake, just re-run as your normal
user - the script detects a `.venv` with the wrong owner and rebuilds it.

This installs system packages (via `apt`), creates a `.venv`, installs
Python dependencies, generates `.env` from `.env.example` with a random
`ALEX_API_TOKEN`, and installs+enables (but does not yet start) the
`alex` systemd service.

## 3. Configure `.env`

Edit `.env` and set **at least one** AI provider key:

```bash
nano .env
```

- **NVIDIA NIM (default, free tier)**: create a key at
  https://build.nvidia.com, set `ALEX_NVIDIA_API_KEY`. Leave
  `ALEX_AI_PROVIDER=nvidia`.
- **Anthropic Claude**: set `ALEX_ANTHROPIC_API_KEY` and
  `ALEX_AI_PROVIDER=anthropic`.
- **OpenRouter**: create a key at https://openrouter.ai/keys, set
  `ALEX_OPENROUTER_API_KEY` and `ALEX_AI_PROVIDER=openrouter`. Defaults to
  a free-tier model (`ALEX_OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free`);
  browse other options (including paid ones needing OpenRouter account
  credits) at https://openrouter.ai/models.
- **AnyAPI**: create a key at https://anyapi.ai, set `ALEX_ANYAPI_API_KEY`
  and `ALEX_AI_PROVIDER=anyapi`. Model ids are `provider/model-name`; the
  default (`nvidia/nemotron-nano-9b-v2:free`) was verified working
  end-to-end (chat + tool-calling) on a real free account. A free key
  can't access every model though: paid ones (e.g. `openai/gpt-4o-mini`)
  fail with `403 key_model_access_denied` unless your account has credits,
  and some free-tier models return `404` even though they're listed
  (delisted/unavailable upstream - seen in practice with
  `meta-llama/llama-3.3-70b-instruct:free` and `qwen/qwen3-coder:free`).
  If you want to switch models, list what your key can access and then
  confirm the candidate actually responds before putting it in `.env`:
  ```bash
  curl https://api.anyapi.ai/v1/models -H "Authorization: Bearer $ALEX_ANYAPI_API_KEY"
  curl https://api.anyapi.ai/v1/chat/completions -H "Authorization: Bearer $ALEX_ANYAPI_API_KEY" \
    -H "Content-Type: application/json" -d '{"model": "<candidate>", "messages": [{"role":"user","content":"hola"}]}'
  ```

`ALEX_API_TOKEN` was already generated for you - copy it, you'll need it to
configure clients.

## 4. Start ALEX

```bash
sudo systemctl start alex
```

### Check it's running

```bash
sudo systemctl status alex
journalctl -u alex -f          # follow logs live
curl http://localhost:8787/health
```

`/health` should return `{"status": "ok", ...}` with `ai_reachable: true` if
your API key is valid.

ALEX will now start automatically on every boot, and systemd restarts it
automatically if it crashes (`Restart=on-failure` in
`scripts/alex.service`).

## 5. Test memory and a tool (no voice needed)

```bash
TOKEN=$(grep ALEX_API_TOKEN .env | cut -d= -f2)

curl -s http://localhost:8787/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "Recuerda que mi examen de calculo es el 20 de agosto a las 9 de la manana"}' | python3 -m json.tool

curl -s http://localhost:8787/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "Que examen tengo?"}' | python3 -m json.tool
```

The second reply should reference the exam - proof memory persisted across
turns and `memory_recall` worked. Try `"Que tal esta la Raspberry?"` to
exercise the `system_status` tool from the system plugin.

## 6. Test a notification

```bash
sqlite3 data/alex.db "select id, title, status from notifications order by created_at desc limit 5;"
```

Or trigger one for real: set a reminder a minute in the future and wait for
it to fire (the reminders plugin checks every 30s):

```bash
NOW_PLUS_1MIN=$(date -d '+1 minute' '+%Y-%m-%dT%H:%M:%S')
curl -s http://localhost:8787/chat -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"text\": \"Ponme un recordatorio para las $NOW_PLUS_1MIN que diga probar notificaciones\"}"
# wait ~1-2 minutes, then:
curl -s http://localhost:8787/notifications -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

You should see a `reminder.due` notification with `priority: 3`.

## 7. Connect the desktop client (from your PC/Mac, not the Pi)

```bash
cd clients/desktop_minimal
pip install -r requirements.txt
cp .env.example .env
# Edit .env: ALEX_HOST=<pi-ip-or-hostname.local>, ALEX_TOKEN=<the token from step 3>
python client.py
```

Trigger the reminder test above again (or wait for one) - a popup should
appear in the top-right corner of your screen.

## 7b. Chat from a browser - the web console

For quick text conversations from any device (phone, laptop, whatever's
around) without installing anything, ALEX serves a small HUD-style chat
client directly - no separate service, no build step, just static
HTML/CSS/JS served by ALEX itself:

```
http://<pi-ip-or-hostname.local>:8787/console/
```

Open that URL in a browser, enter the Pi's host/port and your
`ALEX_API_TOKEN` (from `.env`, step 3) once - it's remembered in that
browser's local storage. It talks over the same WebSocket protocol as
every other client (`clients/protocol.md`): live chat, and any
notification ALEX pushes shows up as a HUD alert in the corner, with the
same confirm/dismiss actions as the desktop client.

The source is `clients/web_console/index.html` if you want to reskin it -
it's a single self-contained file, no dependencies.

## 7c. Android app (background notifications + overlay)

For a phone that stays connected to ALEX in the background and can pop a
notification/overlay on top of whatever app you're using for anything
important, build and install the native Android client:

```bash
cd clients/android
# open in Android Studio and Run, OR from the command line with the
# Android SDK installed:
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

Full build/setup/permissions walkthrough in `clients/android/README.md`.
Same host/port/token as every other client, same WebSocket protocol - no
server-side changes needed to use it.

## 8. Voice setup (optional, do this after steps 1-7 work)

Voice needs three things beyond `--with-voice`'s Python packages: a working
mic, a Piper voice model, and (for the real "Alex" wake word) a trained
wake-word model.

### 8a. Check your microphone is visible

```bash
source .venv/bin/activate
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

Note the input device name/index. If you need a specific one, set
`ALEX_MIC_DEVICE` in `.env` to that name or index.

### 8b. Download a Piper voice (TTS)

```bash
mkdir -p data/voice_models/piper && cd data/voice_models/piper
# Spanish example voice - browse others at https://huggingface.co/rhasspy/piper-voices
curl -L -o es_ES-davefx-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx
curl -L -o es_ES-davefx-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json
cd -
```

(This must match `ALEX_TTS_VOICE` in `.env` - it defaults to
`es_ES-davefx-medium`.)

### 8c. Wake word

Out of the box, `ALEX_WAKEWORD_NAME=hey_jarvis` (a keyword openWakeWord
ships pretrained) so you can test the full pipeline immediately by saying
**"Hey Jarvis"**. To actually wake on **"Alex"**:

1. Open openWakeWord's training notebook (linked from
   https://github.com/dscripka/openWakeWord) in Google Colab - no local GPU
   needed, takes ~20-30 minutes, generates synthetic training data for your
   chosen word.
2. Train for the word "Alex", download the resulting `alex.onnx`.
3. Copy it to `data/voice_models/wakeword/alex.onnx` on the Pi.
4. In `.env`, set `ALEX_WAKEWORD_MODEL_PATH=data/voice_models/wakeword/alex.onnx`.

### 8d. Enable and start

```bash
sed -i 's/^ALEX_VOICE_ENABLED=.*/ALEX_VOICE_ENABLED=true/' .env
sudo systemctl restart alex
journalctl -u alex -f
```

You should see `"Voice pipeline active - listening passively for the wake
word"` in the logs. Say the wake word, wait for ALEX's short "Dime."
acknowledgement, then speak your request.

**Tuning**: if ALEX cuts you off too early or never stops "listening",
adjust `SILENCE_AMPLITUDE_THRESHOLD` in `alex/voice/pipeline.py` (lower it
if it's cutting you off, raise it if background noise keeps it listening) -
mic sensitivity varies a lot between USB mics.

## Troubleshooting

**Reminders never fire, and/or the logs show `RuntimeWarning: coroutine
'...' was never awaited`** (e.g. from `RemindersPlugin._check_due` or any
other plugin's background check): this was a real bug in earlier versions
- every plugin's scheduled background check (reminders, system monitoring,
email/calendar/task due-soon checks) was silently never actually running,
because of how APScheduler was handed the callback. `git pull` for the
fix and `sudo systemctl restart alex` - no config changes needed. You can
confirm it's fixed by setting a reminder a minute out and watching it
actually notify you.

**`pip install` fails on `tflite-runtime` while installing voice deps** (`ERROR:
Could not find a version that satisfies the requirement tflite-runtime...`):
you're on an older copy of `install_raspberry_pi.sh`/`requirements-voice.txt`
- `git pull` to get the fix (openwakeword is installed with `--no-deps` since
its published dependency on `tflite-runtime` has no wheel for recent Python
versions on aarch64, and ALEX never uses that backend anyway). If you already
have a partially-installed `.venv`, just re-run
`./scripts/install_raspberry_pi.sh --with-voice` - it's safe to re-run.

**`Permission denied` inside `.venv`, or `alex.service` fails to start with a
permissions error**: `.venv` was created (or touched) by `root` at some
point, usually from running the installer with `sudo` by mistake. Fix:

```bash
sudo rm -rf .venv
./scripts/install_raspberry_pi.sh              # or --with-voice, as your normal user, no sudo
```

**`/console/` (or another client) shows "PROCESANDO" forever, the input box
stays locked, and eventually a fresh "Conectado a ALEX" appears without
ever answering your message**: this was a real bug in earlier versions.
Two things could cause it: a single slow/unresponsive AI provider call, OR
- less obviously - a model that takes several *individually fast* tool-call
hops that add up past any reasonable total latency (e.g. it keeps calling
tools back-to-back without ever settling on a final answer). Either way the
connection could drop mid-turn and the client never recovered. `git pull`
for the fix: `ALEX_AI_REQUEST_TIMEOUT_SECONDS` (default 45s) bounds every
single AI provider call, `ALEX_AI_TURN_TIMEOUT_SECONDS` (default 90s)
additionally bounds the *entire* turn regardless of how many hops it takes,
so a turn always finishes (with a clear error message) instead of hanging
indefinitely, and `/console/` now resets its "thinking" state on disconnect
and after a 90s safety timeout regardless. If a tool call itself is
genuinely slow (e.g. a long `run_shell_command`), that command may still be
running server-side even after the client gives
up waiting - check `journalctl -u alex -f` before re-issuing it.

## 9. Remote access with Tailscale (optional)

By design, ALEX only binds to your LAN and never opens a port on your
router (do not port-forward 8787). To reach ALEX from outside your home
network - e.g. connecting the desktop client from a laptop that isn't on
your home Wi-Fi - use [Tailscale](https://tailscale.com): it creates a
private, encrypted, direct connection between your own devices without
exposing anything to the public Internet.

### 9a. Install Tailscale on the Pi

Run this **on the Pi itself** (SSH in with your own credentials, or use a
keyboard/monitor - never share your Pi's login password with anyone,
including in chat):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

The second command prints a URL - open it in a browser on any device and
log in (or create a free Tailscale account) to authorize the Pi. Once
authorized, get the Pi's Tailscale address:

```bash
tailscale ip -4
```

This IP (something like `100.x.y.z`) is reachable **only** from your other
devices once they're also on the same Tailscale network - it does not
require ALEX's own bind address to change (it already listens on
`0.0.0.0:8787`, so it's automatically reachable on the Tailscale interface
too).

### 9b. Install Tailscale on your other devices

On the laptop/phone/PC you want to use as a client, install Tailscale from
https://tailscale.com/download and log in with the **same account** you
used for the Pi.

### 9c. Point the desktop client at the Tailscale address

In `clients/desktop_minimal/.env`, set:

```
ALEX_HOST=<the 100.x.y.z address from step 9a, or the MagicDNS name Tailscale shows for the Pi>
```

Now the desktop client (and `curl`/`/health` checks) work the same way
whether you're on your home network or anywhere else with Tailscale
running.

### 9d. Optional hardening: restrict the port to Tailscale + LAN only

If you want extra defense-in-depth beyond the `ALEX_API_TOKEN` check, you
can use a firewall (e.g. `ufw`) to only allow port 8787 from your LAN
subnet and the Tailscale interface (`tailscale0`), rejecting anything else
- most home routers already make the Pi unreachable from the public
Internet by default (no port forwarding), so this is optional but tidy:

```bash
sudo apt-get install -y ufw
sudo ufw allow from 192.168.0.0/16 to any port 8787 proto tcp
sudo ufw allow in on tailscale0 to any port 8787 proto tcp
sudo ufw enable
```

(Adjust `192.168.0.0/16` to match your actual LAN subnet if different.)

### 9e. HTTPS via `tailscale serve` (needed for the iPhone PWA, see section 12)

The web console works fine over plain `http://` on your LAN or over
Tailscale as-is. The one thing that needs real HTTPS is installing it as
a Home Screen app on iOS and getting push notifications there - browsers
(Safari included) refuse to register a Service Worker or Web Push
subscription outside a "secure context" (`https://` or `localhost`), and
self-signed certificates don't satisfy that.

Tailscale can front ALEX with a real, trusted certificate for its own
`*.ts.net` address (issued via Tailscale's own ACME integration - no
public domain, no separate reverse proxy, no cert renewal cron job to
maintain yourself) with one command, **on the Pi**:

```bash
sudo tailscale serve --bg 8787
```

Run `tailscale serve status` to see the resulting HTTPS address - it
looks like `https://<pi-machine-name>.<your-tailnet>.ts.net/`, reachable
only from devices on your tailnet (not the public Internet). That's the
address to use for the console when you want push notifications (section
12) - for everything else (desktop client, Android app, `curl`), plain
`http://` on port 8787 keeps working exactly as before, nothing about
this is required for them.

## 10. Optional integrations

10a-10d need their own credentials set up first and are NOT enabled by
default - after configuring one, add its plugin id to
`ALEX_ENABLED_PLUGINS` in `.env` (e.g.
`ALEX_ENABLED_PLUGINS=["system","reminders","home_assistant"]`) and
`sudo systemctl restart alex`. No credentials, no new dependencies to
install - all four use only `httpx` and the standard library, already
installed. 10e and 10f need no credentials and ARE enabled by default.

### 10a. Home Assistant

Only useful if you already run a Home Assistant instance on your network.

1. In Home Assistant: your profile (bottom-left) -> scroll to **Long-Lived
   Access Tokens** -> **Create Token**. Copy it now, it's shown once.
2. In the Pi's `.env`:
   ```
   ALEX_HOME_ASSISTANT_URL=http://homeassistant.local:8123
   ALEX_HOME_ASSISTANT_TOKEN=<the token from step 1>
   ```
3. Add `"home_assistant"` to `ALEX_ENABLED_PLUGINS` and restart.

Gives ALEX `ha_get_state`, `ha_list_entities` and `ha_call_service` (the
last one always asks for confirmation before acting, since it controls real
devices).

### 10b. Gmail (IMAP + SMTP)

1. Turn on 2-Step Verification on the Google account if it isn't already
   (required for app passwords): https://myaccount.google.com/security
2. Create an app password: https://myaccount.google.com/apppasswords ->
   name it "ALEX" -> copy the 16-character password.
3. In the Pi's `.env`:
   ```
   ALEX_GMAIL_ADDRESS=you@gmail.com
   ALEX_GMAIL_APP_PASSWORD=<the 16-char app password, no spaces>
   ```
4. Add `"email"` to `ALEX_ENABLED_PLUGINS` and restart.

Gives ALEX `email_check_unread`, `email_mark_read` and `email_send` (the
last one always asks for confirmation before actually sending), plus a
background check every 5 minutes that surfaces new mail (stored, not
push-notified, by default - see `alex/events/engine.py` if you want it
louder). Sending reuses the same app password over SMTP - no extra setup.

### 10c. Google Calendar and/or Google Tasks

Both use the same OAuth helper script and can share one Google Cloud
project - do either or both.

1. In https://console.cloud.google.com: create/select a project -> **APIs &
   Services > Library** -> enable **Google Calendar API** and/or **Tasks
   API** (whichever you're setting up).
2. **APIs & Services > Credentials > Create Credentials > OAuth client ID**
   -> application type **Desktop app**. Note the Client ID and Client Secret.
   (You can reuse the same OAuth client for both Calendar and Tasks.)
3. **On your laptop** (needs a browser - not the Pi):
   ```bash
   cd Proyect-ALEX   # or wherever you cloned the repo locally

   # Calendar only:
   python3 scripts/google_oauth_auth.py --client-id <id> --client-secret <secret> --scopes calendar

   # Tasks only:
   python3 scripts/google_oauth_auth.py --client-id <id> --client-secret <secret> --scopes tasks

   # Both at once (one consent screen, one refresh token valid for both):
   python3 scripts/google_oauth_auth.py --client-id <id> --client-secret <secret> --scopes calendar,tasks
   ```
   This opens a browser tab to log in and consent, then prints the `.env`
   lines to add - `ALEX_GOOGLE_CALENDAR_*` and/or `ALEX_GOOGLE_TASKS_*`
   depending on which scopes you requested. If you requested both scopes in
   one run, the same refresh token is printed for both sets of variables -
   paste it into both.
4. Paste the printed lines into the Pi's `.env`.
5. Add `"google_calendar"` and/or `"google_tasks"` to `ALEX_ENABLED_PLUGINS`
   and restart.

**Google Calendar** gives ALEX `calendar_list_upcoming`,
`calendar_create_event`, `calendar_delete_event` (confirmation required),
plus a background check that notifies you ~60 minutes before an event
starts.

**Google Tasks** gives ALEX `tasks_list`, `tasks_add`, `tasks_complete`,
plus a background check that notifies you about tasks due within 24 hours.

### 10d. Microsoft To Do

Skip this if you're using Google Tasks instead - they're two different
task-management products; you don't need both.

1. In https://portal.azure.com: **Azure Active Directory > App
   registrations > New registration**. Name it "ALEX", leave redirect URI
   empty, register.
2. **Authentication** -> under **Advanced settings**, set **Allow public
   client flows** to **Yes** -> Save.
3. **API permissions > Add a permission > Microsoft Graph > Delegated
   permissions** -> add `Tasks.ReadWrite` -> (grant admin consent if you're
   the tenant admin, otherwise you'll consent yourself during login).
4. Copy the **Application (client) ID** from the app's Overview page.
5. In the Pi's `.env`:
   ```
   ALEX_MS_CLIENT_ID=<the client id from step 4>
   ALEX_MS_TENANT=consumers
   ```
   (`consumers` for a personal Microsoft account; use `common` if you also
   want to allow a work/school account.)
6. Add `"ms_todo"` to `ALEX_ENABLED_PLUGINS` and restart, then watch the logs:
   ```bash
   journalctl -u alex -f
   ```
   On first start you'll see a message like "ve a
   https://microsoft.com/devicelogin e introduce el codigo XXXXXXX" - it's
   also pushed as a notification (so it reaches the desktop client too). Do
   that once from any browser and ALEX stores the resulting token for future
   restarts (via its own memory, not the `.env` file).

Gives ALEX `todo_list_tasks`, `todo_add_task`, `todo_complete_task`, plus a
background check that notifies you about tasks due within 24 hours.

### 10e. Web browsing

On by default (`"web"` in `ALEX_ENABLED_PLUGINS`), no setup needed. Gives
ALEX `web_fetch`: give it a URL ("mira esta pagina...", or paste a link) and
it reads the page's title and text back, so you can ask questions about it.
Public pages only (no login), and it reads whatever the page returns - same
trust model as clicking a link yourself. No web search (no reliable
key-free search API to build on) - it needs an actual URL, not a topic to
search for.

### 10f. Daily briefing

On by default (`"daily_briefing"` in `ALEX_ENABLED_PLUGINS`). Once a day,
at `ALEX_BRIEFING_TIME` (local time, default `07:30`), ALEX pushes a
notification with the day's news, plus today's calendar events and pending
tasks if you've set up 10c above (skipped otherwise - news alone works with
zero configuration). If `ALEX_VOICE_ENABLED=true`, it's also spoken aloud
through the speaker, not just pushed. You don't have to wait for the
scheduled time either - just ask "dime las noticias de hoy" any time.

To change the time or news source:
```
ALEX_BRIEFING_TIME=07:30
ALEX_BRIEFING_NEWS_RSS_URL=https://feeds.bbci.co.uk/mundo/rss.xml
ALEX_BRIEFING_NEWS_MAX_ITEMS=5
```
Any RSS 2.0 feed works for `ALEX_BRIEFING_NEWS_RSS_URL`. Restart after
changing either.

## 11. System command execution (`system_exec`) - HIGH RISK, optional

> **Read this before enabling.** This gives ALEX a `run_shell_command` tool
> that can run anything the `alex` process's user can: read/modify/delete
> any file it can reach, install or remove software, change configuration.
> It is CONFIRM-gated - ALEX always asks you before running a command, no
> exceptions, and every attempted command (approved or not) is logged - but
> the blast radius of an approved command is the whole machine. Only enable
> this on a Pi you're comfortable giving that level of access to.

1. Add `"system_exec"` to `ALEX_ENABLED_PLUGINS` in `.env` and restart:
   ```bash
   sudo systemctl restart alex
   ```
2. Test it with something harmless first, e.g. ask ALEX (via `/console/`,
   the desktop client, or `/chat`) to run `echo hola` or `df -h` - it should
   explain what it's about to do and wait for your confirmation before
   running it.

### `sudo` commands (e.g. "inicia tailscale")

Commands run with no interactive terminal, so anything that prompts for a
`sudo` password will hang until it times out and fails - there's no way for
ALEX to type a password for you. To let specific, approved commands run
with `sudo` and no password prompt, add a **narrowly scoped** sudoers rule
(never grant blanket passwordless root):

```bash
sudo visudo -f /etc/sudoers.d/alex-system-exec
```

Add (replace `nicolas` with the user `alex.service` runs as, and confirm
the binary paths with `which tailscale` / `which systemctl` first - they
can differ slightly between systems):

```
nicolas ALL=(root) NOPASSWD: /usr/bin/tailscale
nicolas ALL=(root) NOPASSWD: /usr/bin/systemctl restart alex, /usr/bin/systemctl status alex
```

Save and exit (`visudo` validates the syntax before writing, so a typo
can't lock out `sudo` entirely). This allows passwordless `sudo` for the
`tailscale` binary specifically (its own auth model still applies - you
still approve the device via a browser link) and for restarting/checking
ALEX's own service, and nothing else.

With that in place, you can ask ALEX something like "inicia tailscale y
dame el enlace para autenticar" - it will run `sudo tailscale up`
(after you confirm), capture the printed authentication URL from the
output, and give it to you in the reply.

## 12. Phone push notifications via the web console (optional, iPhone included)

The desktop client and Android app (7c) stay connected in the background
and get notifications that way. A browser tab can't do that - it only
gets pushed messages while the WebSocket connection is open, i.e. while
you have the console open and on screen. Web Push fixes that: once the
console is installed as a Home Screen app, the OS itself wakes it to
show a notification, exactly like a native app - **this is the only way
to get ALEX notifications on an iPhone** (there is no native iOS app -
see the project's own notes on why: no background execution without
this, and no floating overlay at all, both are iOS platform
restrictions, not something any app can work around).

1. **Generate a VAPID key pair** (the credential that proves push
   messages come from your own ALEX, not anyone else) - on the Pi:
   ```bash
   python3 scripts/gen_vapid_keys.py
   ```
   Paste the three printed lines into `.env` (fill in your own email for
   `ALEX_VAPID_CONTACT_EMAIL` - it's only ever sent to the push service
   as a contact point, never shown to you or anyone else):
   ```
   ALEX_VAPID_PUBLIC_KEY=...
   ALEX_VAPID_PRIVATE_KEY=...
   ALEX_VAPID_CONTACT_EMAIL=you@example.com
   ```
2. **Restart ALEX**:
   ```bash
   sudo systemctl restart alex
   ```
3. **Set up HTTPS** via section 9e above if you haven't already
   (`sudo tailscale serve --bg 8787` on the Pi) - required specifically
   for the install-as-app + push step below, not for anything else.
4. **On the iPhone** (Tailscale app installed and logged into the same
   tailnet as the Pi, per 9b): open **Safari** (must be Safari, not
   Chrome/Firefox - only Safari can install a Home Screen app on iOS) at
   the `https://....ts.net/console/` address from step 3, connect once
   with the Pi's host/port left as just the `....ts.net` hostname (leave
   the **port field empty** - `tailscale serve` puts HTTPS on 443, the
   implicit default) and your `ALEX_API_TOKEN`.
5. Tap the **Share** button → **Add to Home Screen**. This installed
   copy, not the regular Safari tab, is what can receive push - opening
   `https://.../console/` in a normal tab won't work for this.
6. Open the app from the Home Screen icon, tap the 🔔 button in the
   header, and allow notifications when iOS asks.

From then on, anything that reaches `send_notification` (including
things ALEX decides to notify you about on its own within a chat turn)
or fires as a reminder shows up as a real iOS notification - lock screen
included - even with the app fully closed.

## Updating

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart alex
```

## Uninstalling

```bash
sudo systemctl stop alex
sudo systemctl disable alex
sudo rm /etc/systemd/system/alex.service
sudo systemctl daemon-reload
```

Your data (`data/alex.db`, logs) stays on disk unless you delete the
project directory yourself.
