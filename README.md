# J.A.R.V.I.S — Voice-Controlled Linux Assistant

A voice-driven desktop assistant for Linux (built and tested on GNOME Wayland).
Wake it with "Hey Jarvis", then speak commands. Local STT (faster-whisper) and
TTS (Piper) for privacy + low latency; Gemini 2.5 Flash as the smart fallback
for anything the regex handlers don't catch. Adds keyboard / mouse / scroll /
window control via ydotool + xdotool, with optional vision-driven UI clicking
via Gemini Multi-Modal.

## What it can do

- **Apps & windows** — open / close / switch (gtk-launch + GNOME Overview)
- **Workspaces** — switch by number, ordinal, name, next/previous, create new
- **Browser tabs** — Ctrl+1..9 + named-tab vision search
- **System** — volume, brightness, lock, suspend, screenshot, Wi-Fi, battery
- **Keyboard & mouse** — type any text, press any combo, click at coords or screen position
- **Vision** — "click the play button", "what does that error say", "switch to the Gmail tab"
- **Conversation context** — multi-turn ("open YouTube" → "now search for lo-fi")
- **Self-evolution (Level 1)** — logs missing capabilities to `missing_capabilities.md` for you to review

See `commands/` for each handler and `gemini_brain.py` for the full action schema.

## Setup

```bash
# Clone and install system deps + venv + Piper voice
git clone https://github.com/SamarS1ngh/jarvis-voice-assistant.git
cd jarvis-voice-assistant
./setup.sh

# Set your Gemini API key (free tier — https://aistudio.google.com/apikey)
cp .env.example .env
# edit .env and paste your key
# OR: export GEMINI_API_KEY="your-key-here"

# Run
source venv/bin/activate
python3 main.py
```

Then say "Hey Jarvis" and a command. "Hey Jarvis, shut down" exits cleanly.

## Stack

```
mic → openwakeword ("hey_jarvis") → faster-whisper (STT)
    → Commander (regex handlers / Gemini fallback)
    → ydotool / xdotool / xdg-open / gtk-launch / Gemini Vision
    → Piper TTS → speaker + pygame face widget
```

## Requirements

- Ubuntu 22.04+ on GNOME (Wayland or X11; Wayland needs `ydotool` for input)
- Python 3.10+
- A free Gemini API key

## Status

Personal "iterate forever" project — Stark-style continuous improvement.
Expect rough edges; see `TODO.md` for what's next and
`missing_capabilities.md` for things Jarvis itself flags as gaps.

## License

MIT — see `LICENSE` if added later.
