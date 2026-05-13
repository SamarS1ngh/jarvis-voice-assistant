"""Browser tab switching.

Tabs use Ctrl+1..9 (universal across all browsers and many multi-tab apps).

Media play/pause is intentionally NOT handled here — blind click+space proved
unreliable. It now flows through Gemini, which uses vision (see_and_click on
the play button) for a much higher success rate.
"""

import re

from commands.control import press_keys
from jarvis_log import log


NUMBERS = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "6th": 6, "7th": 7, "8th": 8, "9th": 9,
}

# Direction tokens that map to cycling
NEXT_TOKENS = {"next", "forward"}
PREV_TOKENS = {"previous", "prev", "last", "back"}

# Tab patterns
_VERB = r"(?:switch|go|jump|move)"
TAB_PATTERNS = [
    re.compile(rf"\b{_VERB}\s+to\s+(?:the\s+)?(\w+)\s+tab\b"),
    re.compile(rf"\b{_VERB}\s+to\s+(?:the\s+)?tab\s+(\w+)\b"),
    re.compile(r"^\s*(?:the\s+)?(\w+)\s+tab\b"),
    re.compile(r"^\s*tab\s+(\w+)\b"),
]

def handle_tabs(text: str) -> tuple[str, bool]:
    text_lower = text.lower().strip().rstrip(".")

    # Tab switching
    for pattern in TAB_PATTERNS:
        m = pattern.search(text_lower)
        if not m:
            continue
        token = m.group(1).lower()

        if token in NEXT_TOKENS:
            ok = press_keys("ctrl Tab")
            log.info(f"tabs: NEXT (Ctrl+Tab) -> {ok}")
            return ("Next tab.", True) if ok else ("Couldn't switch tab.", True)

        if token in PREV_TOKENS:
            ok = press_keys("ctrl shift Tab")
            log.info(f"tabs: PREV (Ctrl+Shift+Tab) -> {ok}")
            return ("Previous tab.", True) if ok else ("Couldn't switch tab.", True)

        n = NUMBERS.get(token)
        if n and 1 <= n <= 9:
            ok = press_keys(f"ctrl {n}")
            log.info(f"tabs: numeric {n} (Ctrl+{n}) -> {ok}")
            return (f"Switched to tab {n}.", True) if ok else (f"Couldn't switch to tab {n}.", True)

        # Named tab ("the GitHub tab") — fall through to Gemini for vision-based finding
        log.info(f"tabs: named token {token!r} — falling through to Gemini for vision")
        return "", False

    return "", False
