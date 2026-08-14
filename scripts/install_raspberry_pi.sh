#!/usr/bin/env bash
# Installs and configures ALEX as a systemd service on a Raspberry Pi 4
# (Raspberry Pi OS Bookworm/64-bit recommended). Safe to re-run.
#
# Usage:
#   ./scripts/install_raspberry_pi.sh              # backend only (no voice deps)
#   ./scripts/install_raspberry_pi.sh --with-voice  # also installs wake word/STT/TTS deps
set -euo pipefail

WITH_VOICE=false
for arg in "$@"; do
  case "$arg" in
    --with-voice) WITH_VOICE=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "==> Installing ALEX from $PROJECT_DIR (user=$CURRENT_USER, voice=$WITH_VOICE)"

echo "==> Installing system packages (requires sudo)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev python3-pip build-essential git sqlite3

if [ "$WITH_VOICE" = true ]; then
  echo "==> Installing voice system dependencies (portaudio, espeak-ng)..."
  sudo apt-get install -y portaudio19-dev libsndfile1 espeak-ng ffmpeg
fi

echo "==> Creating Python virtual environment at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip

echo "==> Installing Python dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt"
if [ "$WITH_VOICE" = true ]; then
  pip install -r "$PROJECT_DIR/requirements-voice.txt"
fi

echo "==> Preparing data directories..."
mkdir -p "$PROJECT_DIR/data/logs" "$PROJECT_DIR/data/voice_models/piper" "$PROJECT_DIR/data/voice_models/wakeword"

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "==> Creating .env from .env.example ..."
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  GENERATED_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  sed -i "s#^ALEX_API_TOKEN=.*#ALEX_API_TOKEN=$GENERATED_TOKEN#" "$PROJECT_DIR/.env"
  if [ "$WITH_VOICE" = true ]; then
    sed -i "s#^ALEX_VOICE_ENABLED=.*#ALEX_VOICE_ENABLED=true#" "$PROJECT_DIR/.env"
  fi
  echo "    Generated a random ALEX_API_TOKEN. IMPORTANT: edit $PROJECT_DIR/.env now to add your"
  echo "    ALEX_NVIDIA_API_KEY (or ALEX_ANTHROPIC_API_KEY) before starting ALEX."
else
  echo "==> .env already exists, leaving it untouched."
fi

echo "==> Installing systemd service..."
sudo cp "$PROJECT_DIR/scripts/alex.service" /etc/systemd/system/alex.service
sudo sed -i "s#/home/pi/Proyect-ALEX#$PROJECT_DIR#g" /etc/systemd/system/alex.service
sudo sed -i "s#^User=.*#User=$CURRENT_USER#" /etc/systemd/system/alex.service
sudo sed -i "s#^Group=.*#Group=$CURRENT_USER#" /etc/systemd/system/alex.service
sudo systemctl daemon-reload
sudo systemctl enable alex.service

echo ""
echo "==> Done. Next steps:"
echo "    1. Edit $PROJECT_DIR/.env and set at least one AI provider API key."
if [ "$WITH_VOICE" = true ]; then
  echo "    2. Download a Piper voice into data/voice_models/piper (see docs/INSTALL_RASPBERRY_PI.md)."
  echo "    3. sudo systemctl start alex"
else
  echo "    2. sudo systemctl start alex"
fi
echo "    Check status with: sudo systemctl status alex"
echo "    Follow logs with:  journalctl -u alex -f"
