#!/bin/bash
# V.O.I.D — Voice Operated Intelligent Daemon
# One-shot installer for Ubuntu

set -e

echo "=== V.O.I.D Setup ==="
echo ""

# System packages
echo "[1/4] Installing system packages..."
sudo apt update -qq
sudo apt install -y \
    portaudio19-dev \
    python3-dev \
    python3-venv \
    python3-pip \
    xdotool \
    ydotool \
    wmctrl \
    brightnessctl \
    xclip \
    scrot \
    grim \
    gnome-screenshot \
    alsa-utils \
    pulseaudio-utils \
    ffmpeg

# ydotool note: on Wayland, ydotool needs a running daemon and your user
# in the 'input' group. One-time setup:
#   sudo usermod -aG input $USER
#   systemctl --user enable --now ydotool   # then log out + back in
# xdotool remains the primary backend and works for X11 / XWayland apps.

# Create virtual environment
echo "[2/4] Creating Python virtual environment..."
VENV_DIR="$(dirname "$0")/venv"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Python packages
echo "[3/4] Installing Python packages..."
pip install --upgrade pip -q
pip install -r "$(dirname "$0")/requirements.txt"

# Download Piper voice
echo "[4/4] Downloading Piper TTS voice..."
VOICE_DIR="$(dirname "$0")/models/piper"
mkdir -p "$VOICE_DIR"
if [ ! -f "$VOICE_DIR/en_US-lessac-high.onnx" ]; then
    pip install piper-tts -q
    echo "Piper voice will be downloaded on first run."
fi

echo ""
echo "=== Setup complete! ==="
echo "To run V.O.I.D:"
echo "  source venv/bin/activate"
echo "  python3 main.py"
echo ""
echo "Optional: Set your Gemini API key in config.py for smart fallback."
