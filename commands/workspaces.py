"""Workspace switching by number, ordinal, or direction.

Numeric / ordinal switching uses Super+Alt+N (bound via gsettings during setup).
Cycling uses Super+PageDown / Super+PageUp.
Name-based switching ("switch to the Code workspace") falls through to Gemini's
switch_workspace_by_name action — see gemini_brain.py.
"""

import re

from commands.control import press_keys
from jarvis_log import log


# Tokens we know how to translate. Names like "code", "web", "main"
# are NOT here — those fall through to Gemini for vision-based switching.
TOKENS = {
    # digits
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    # cardinal
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
    # ordinal
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "6th": 6, "7th": 7, "8th": 8, "9th": 9,
    # direction (special markers)
    "next": "NEXT", "forward": "NEXT",
    "previous": "PREV", "prev": "PREV", "back": "PREV", "last": "PREV",
}

# Patterns ordered most-specific to least.
# "workplace", "work space" (two words), "box place" are Whisper mistranscriptions.
_W = r"(?:workspaces?|workplaces?|work\s+spaces?|box\s+places?)"
# Allow "switch back to" / "go back to" by making "back" optional between verb and "to"
_VERB = r"(?:switch|go|jump|move|change|take\s+me)(?:\s+back)?"

PATTERNS = [
    # "switch to (the) X workspace"  — captures X
    re.compile(rf"\b{_VERB}\s+to\s+(?:the\s+)?(\w+)\s+{_W}\b"),
    # "switch to (the) workspace X"  — captures X
    re.compile(rf"\b{_VERB}\s+to\s+(?:the\s+)?{_W}\s+(\w+)\b"),
    # "(the) X workspace"            — bare form, captures X
    re.compile(rf"^\s*(?:the\s+)?(\w+)\s+{_W}\b"),
    # "workspace X"
    re.compile(rf"^\s*{_W}\s+(\w+)\b"),
]


def handle_workspaces(text: str) -> tuple[str, bool]:
    text_lower = text.lower().strip().rstrip(".")

    # "open/create/add/make/switch-to a new workspace" — relies on dynamic-workspaces=true.
    # Going past the last workspace via Ctrl+Alt+Right auto-creates a new one.
    create_patterns = [
        re.compile(rf"\b(?:open|create|add|make)\s+(?:a\s+)?(?:new\s+)?{_W}\b"),
        re.compile(rf"\b(?:switch|go|jump|move)\s+to\s+(?:a\s+)?new\s+{_W}\b"),
    ]
    if any(p.search(text_lower) for p in create_patterns):
        ok = press_keys("ctrl alt right")
        log.info(f"workspaces: NEW (Ctrl+Alt+Right past last) -> {ok}")
        return ("Opening a new workspace.", True) if ok else ("Couldn't create workspace.", True)

    for pattern in PATTERNS:
        m = pattern.search(text_lower)
        if not m:
            continue

        token = m.group(1).lower()
        target = TOKENS.get(token)

        if target == "NEXT":
            # Ctrl+Alt+Right is bound and uses simpler keysyms than Super+PageDown
            # (ydotool 0.1.8 silently mishandles "Page_Down" sometimes)
            ok = press_keys("ctrl alt right")
            log.info(f"workspaces: NEXT (Ctrl+Alt+Right) -> {ok}")
            return ("Next workspace.", True) if ok else ("Couldn't switch workspace.", True)

        if target == "PREV":
            ok = press_keys("ctrl alt left")
            log.info(f"workspaces: PREV (Ctrl+Alt+Left) -> {ok}")
            return ("Previous workspace.", True) if ok else ("Couldn't switch workspace.", True)

        if isinstance(target, int) and 1 <= target <= 9:
            ok = press_keys(f"super alt {target}")
            log.info(f"workspaces: numeric {target} (Super+Alt+{target}) -> {ok}")
            return (f"Switched to workspace {target}.", True) if ok else (f"Couldn't switch to workspace {target}.", True)

        # Token didn't map (probably a workspace NAME like "code", "web").
        # Fall through so Gemini can handle it via switch_workspace_by_name.
        log.info(f"workspaces: token {token!r} unknown — falling through to Gemini")
        return "", False

    return "", False
