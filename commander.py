import datetime
import os
import re
import signal

from commands import ALL_HANDLERS
from gemini_brain import GeminiBrain
from jarvis_log import log
import config


# When Gemini's response matches one of these, Jarvis didn't really understand
# the user. We log these to missing_capabilities.md for the user to review.
UNCERTAIN_PATTERNS = [
    re.compile(r"\bI'?m\s+not\s+sure\b", re.I),
    re.compile(r"\bI\s+don'?t\b", re.I),
    re.compile(r"\bI\s+couldn'?t\b", re.I),
    re.compile(r"\bI\s+can'?t\b", re.I),
    re.compile(r"\bI\s+am\s+unable\b", re.I),
    re.compile(r"\bcould\s+you\s+(?:please\s+)?rephrase\b", re.I),
    re.compile(r"\bnot\s+able\s+to\b", re.I),
    re.compile(r"\bI\s+don'?t\s+(?:see|know|understand)\b", re.I),
]

MISSING_CAPS_PATH = os.path.join(config.PROJECT_DIR, "missing_capabilities.md")


def _is_uncertain(response: str) -> bool:
    return any(p.search(response) for p in UNCERTAIN_PATTERNS)


def _log_missing_capability(heard: str, response: str):
    """Append a structured entry to missing_capabilities.md for user review."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (
        f"\n## {timestamp}\n"
        f"- **Heard:** `{heard}`\n"
        f"- **Jarvis said:** `{response}`\n"
        f"- **Suggested:** Add a handler / regex / SYSTEM_PROMPT example so this works next time.\n"
    )
    try:
        with open(MISSING_CAPS_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        log.info(f"missing_capability logged: {heard!r}")
    except Exception as e:
        log.warning(f"Could not write missing_capabilities.md: {e}")


# Phrases that wipe the Gemini conversation context (MK-2)
RESET_PHRASES = (
    "new topic",
    "forget that",
    "forget what we said",
    "clear context",
    "clear conversation",
    "start over",
    "fresh start",
    "reset context",
)

# Patterns that terminate Jarvis (sends SIGINT → main.py shutdown handler).
# Use regex so "shut down" matches alone but NOT "shut down the computer".
EXIT_PATTERNS = [
    re.compile(r"^\s*shut\s*down\.?\s*$"),
    re.compile(r"^\s*shutdown\.?\s*$"),
    re.compile(r"\bshut\s+(?:yourself|jarvis)\s+down\b"),
    re.compile(r"\bshut\s+down\s+(?:yourself|jarvis)\b"),
    re.compile(r"\b(?:exit|quit|stop)\s+jarvis\b"),
    re.compile(r"\bclose\s+(?:yourself|your\s+program)\b"),
    re.compile(r"\b(?:kill|terminate)\s+yourself\b"),
    re.compile(r"\bturn\s+yourself\s+off\b"),
    re.compile(r"\bgoodbye\s+jarvis\b"),
    re.compile(r"\bgo\s+to\s+sleep\s+jarvis\b"),
]

# Pause: stop responding but keep listening. Use specific phrases to avoid
# false positives ("stop" alone is too common in normal speech).
PAUSE_PATTERNS = [
    re.compile(r"^\s*(?:pause|wait|hush)\.?\s*$"),
    re.compile(r"\b(?:be\s+quiet|shut\s+up|don'?t\s+talk|don'?t\s+do\s+anything|don'?t\s+respond)\b"),
    re.compile(r"\bstop\s+(?:listening|responding|talking)\b"),
    re.compile(r"^\s*go\s+to\s+sleep\.?\s*$"),
]

# Resume from pause
RESUME_PATTERNS = [
    re.compile(r"^\s*(?:resume|wake\s+up|continue|i'?m\s+back)\.?\s*$"),
    re.compile(r"\b(?:start|resume)\s+listening\b"),
    re.compile(r"\byou\s+can\s+(?:talk|respond)\b"),
    re.compile(r"\bcome\s+back\s+jarvis\b"),
]


class Commander:
    def __init__(self):
        self.gemini = GeminiBrain() if config.GEMINI_API_KEY else None
        self.paused = False  # When True, Jarvis ignores everything except resume

    def process(self, text: str) -> str:
        """Process transcribed text and execute the matching command.

        Args:
            text: Lowercased transcribed voice command.

        Returns:
            Response text for TTS to speak.
        """
        if not text:
            return ""

        # PAUSED MODE — only listen for resume; ignore everything else
        if self.paused:
            if any(p.search(text) for p in RESUME_PATTERNS):
                self.paused = False
                log.info("RESUMED from pause")
                return "OK, I'm back."
            log.info(f"PAUSED — ignoring {text!r}")
            return ""

        # Self-termination — sends SIGINT so main.py's shutdown handler runs
        if any(p.search(text) for p in EXIT_PATTERNS):
            log.info("ROUTED: exit (sending SIGINT to self)")
            os.kill(os.getpid(), signal.SIGINT)
            return "Goodbye."

        # Pause — stop responding but keep listening for resume
        if any(p.search(text) for p in PAUSE_PATTERNS):
            self.paused = True
            log.info("ENTERED PAUSED state")
            return "OK, I'll be quiet. Say wake up when you need me."

        # MK-2 meta-command: clear conversation context
        if any(p in text for p in RESET_PHRASES):
            if self.gemini:
                self.gemini.clear_history()
            log.info("ROUTED: reset (cleared Gemini history)")
            return "OK, starting fresh."

        # Try built-in handlers first
        for handler in ALL_HANDLERS:
            response, handled = handler(text)
            if handled:
                log.info(f"ROUTED to {handler.__name__}: response={response!r}")
                return response

        log.info("ROUTED to Gemini brain (no regex match)")
        # Fall back to Gemini (which carries conversation history)
        if self.gemini:
            result = self.gemini.process(text)
            # Detect "Gemini didn't really know how to handle this" responses
            # and log them so the user can review and add capabilities.
            if result and _is_uncertain(result):
                _log_missing_capability(text, result)
            return result

        log.warning("Gemini unavailable; no handler matched")
        _log_missing_capability(text, "(no handler matched and Gemini unavailable)")
        return "I didn't understand that. Try saying it differently."
