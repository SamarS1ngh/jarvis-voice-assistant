import os

# Load .env from the project directory at import time so config can read it.
# Silently skipped if python-dotenv isn't installed (the env var still works).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# === JARVIS Configuration ===
# Originally: V.O.I.D — Voice Operated Intelligent Daemon

# Wake word
WAKE_WORD = "hey_jarvis"  # OpenWakeWord model name
WAKE_WORD_THRESHOLD = 0.5  # Confidence threshold (0.0 - 1.0)

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1280  # Samples per frame (80ms at 16kHz)
SILENCE_THRESHOLD = 0.03  # RMS threshold for silence detection
SILENCE_DURATION = 1  # Seconds of silence before stopping recording
MAX_RECORD_SECONDS = 10  # Maximum recording duration

# Speech-to-Text (faster-whisper)
WHISPER_MODEL = "small"  # tiny, base, small, medium, large-v3
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"  # int8 for CPU efficiency
WHISPER_LANGUAGE = "en"

# Text-to-Speech (Piper)
PIPER_VOICE = "en_US-lessac-high"  # Natural American English voice

# Gemini API — set GEMINI_API_KEY in your environment (or a .env file)
# Get one from https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# Paths
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(PROJECT_DIR, "models")

# Computer control safety
MAX_TYPE_LENGTH = 500  # Refuse to type strings longer than this — guards against runaway Gemini outputs

# Conversation context (MK-2 — Gemini brain memory)
CONTEXT_TTL_SECONDS = 60   # Drop history if user has been silent this long
CONTEXT_MAX_TURNS = 6      # Keep at most N user+model exchanges (older ones drop off)

# Assistant identity
ASSISTANT_NAME = "Jarvis"
GREETING = "Jarvis is ready. Say Hey Jarvis to give me a command."

# Floating face overlay
OVERLAY_SIZE = int(os.environ.get("OVERLAY_SIZE", "360"))   # square canvas, px
OVERLAY_MARGIN = int(os.environ.get("OVERLAY_MARGIN", "24"))  # gap from screen edge for first launch
# Pure passthrough "movie" mode: clicks fully pass through, overlay is NOT draggable.
# Off by default so you can grab and drag the brain by its disc.
OVERLAY_CLICK_THROUGH = os.environ.get("OVERLAY_CLICK_THROUGH", "0") == "1"
# Saved drag position (written when you move the overlay). Deleted -> back to default corner.
OVERLAY_POS_FILE = os.path.join(PROJECT_DIR, ".overlay_pos.json")
