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
