"""Mouse, keyboard, scroll, and click control for Jarvis.

Backends:
  - ydotool: Wayland-native (preferred when installed)
  - xdotool: X11 / XWayland — works for most apps even on Wayland sessions

If neither is installed the handler falls through silently so the user
just gets the normal "I didn't understand" path.
"""

import re
import shutil
import subprocess

import config


_YDOTOOL = shutil.which("ydotool")
_XDOTOOL = shutil.which("xdotool")
HAS_BACKEND = bool(_YDOTOOL or _XDOTOOL)


# Spoken key name -> xdotool key name (xdotool's keysym table is rich)
SPOKEN_TO_KEY = {
    "enter": "Return", "return": "Return",
    "tab": "Tab",
    "escape": "Escape", "esc": "Escape",
    "space": "space", "spacebar": "space", "space bar": "space",
    "backspace": "BackSpace", "back space": "BackSpace",
    "delete": "Delete", "del": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End",
    "page up": "Page_Up", "page down": "Page_Down",
    "control": "ctrl", "ctrl": "ctrl",
    "command": "super", "meta": "super", "super": "super", "win": "super", "windows": "super",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
    "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
    "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
}

# Filler words to drop from spoken combos — Whisper's natural-language transcripts
# often include these; we strip them so "press the space bar" -> press space.
# CRITICAL: "a" is NOT in this set because it's a real letter ("ctrl+a" must work).
FILLER_WORDS = {"the", "an", "key", "button"}

# Known keysyms for validation — rejects garbage combos like "BackSpace+on+search+bar".
# Built lazily from SPOKEN_TO_KEY's values + single letters/digits.
_KNOWN_KEYSYMS_LOWER: set[str] | None = None


def _known_keysyms() -> set[str]:
    global _KNOWN_KEYSYMS_LOWER
    if _KNOWN_KEYSYMS_LOWER is None:
        _KNOWN_KEYSYMS_LOWER = (
            {v.lower() for v in SPOKEN_TO_KEY.values()}
            | set("abcdefghijklmnopqrstuvwxyz")
            | set("0123456789")
        )
    return _KNOWN_KEYSYMS_LOWER

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _normalize_key_combo(spoken: str) -> str:
    """Convert spoken combo ("control c", "page up", "alt plus tab") to xdotool form ("ctrl+c").

    Strips filler words ("the", "key", etc.) so "press the space bar" -> "space".
    Preserves the original case for unmapped tokens (so Gemini can hand us
    "super+Page_Down" and we don't lowercase it into "page_down").
    """
    s = spoken.strip().rstrip(".")
    s = re.sub(r"\s+(plus|and)\s+", " ", s, flags=re.IGNORECASE)
    parts = [p for p in re.split(r"[\s+]+", s) if p and p.lower() not in FILLER_WORDS]

    out = []
    i = 0
    while i < len(parts):
        # Try a 2-word match first ("page up", "page down", "space bar") — case-insensitive
        if i + 1 < len(parts):
            two_lower = f"{parts[i].lower()} {parts[i+1].lower()}"
            if two_lower in SPOKEN_TO_KEY:
                out.append(SPOKEN_TO_KEY[two_lower])
                i += 2
                continue
        token = parts[i]
        token_lower = token.lower()
        if token_lower in SPOKEN_TO_KEY:
            out.append(SPOKEN_TO_KEY[token_lower])
        else:
            out.append(token)  # preserve original case for unmapped (e.g., "Page_Down")
        i += 1

    return "+".join(out)


def _run(cmd: list[str]) -> bool:
    return subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


# --- Public primitives ------------------------------------------------------

def type_text(text: str) -> bool:
    if not text:
        return False
    if len(text) > config.MAX_TYPE_LENGTH:
        return False
    if _YDOTOOL:
        return _run(["ydotool", "type", "--", text])
    if _XDOTOOL:
        return _run(["xdotool", "type", "--delay", "20", "--", text])
    return False


def press_keys(spoken_combo: str) -> bool:
    combo = _normalize_key_combo(spoken_combo)
    try:
        from jarvis_log import log
        log.debug(f"press_keys: spoken={spoken_combo!r} -> normalized={combo!r}")
    except Exception:
        pass
    if not combo:
        return False
    # Validate every component — rejects garbage like "BackSpace+on+search+bar+telegram".
    # When called by handle_control "press X" with junk text, we want to return False so
    # the caller can fall through to Gemini for compound interpretation.
    known = _known_keysyms()
    parts = combo.split("+")
    bad = [p for p in parts if p.lower() not in known]
    if bad:
        try:
            from jarvis_log import log
            log.debug(f"press_keys: rejecting combo {combo!r} (unknown parts: {bad})")
        except Exception:
            pass
        return False
    # Prefer ydotool — works on Wayland-native windows (gnome-terminal, etc.)
    # ydotool 0.1.8 accepts the same combo syntax as xdotool ("ctrl+c", "alt+Tab").
    if _YDOTOOL and _run(["ydotool", "key", combo]):
        return True
    if _XDOTOOL:
        return _run(["xdotool", "key", combo])
    return False


def click(x: int, y: int, button: str = "left") -> bool:
    # Prefer ydotool — its events flow through uinput → kernel → compositor,
    # which Wayland-native windows (Edge, Firefox in Wayland mode, GNOME apps)
    # actually receive. xdotool's clicks don't reach Wayland-native windows.
    # ydotool 0.1.8 has relative-only mousemove, so use the corner-trick.
    if _YDOTOOL:
        # ydotool 0.1.8 click button mapping: 1=left, 2=right, 3=middle
        btn_map = {"left": "1", "middle": "3", "right": "2"}
        _run([_YDOTOOL, "mousemove", "--", "-10000", "-10000"])
        _run([_YDOTOOL, "mousemove", "--", str(x), str(y)])
        return _run([_YDOTOOL, "click", btn_map.get(button, "1")])
    if _XDOTOOL:
        btn = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
        return _run([_XDOTOOL, "mousemove", str(x), str(y), "click", btn])
    return False


def scroll(direction: str, amount: int = 3) -> bool:
    amount = max(1, min(amount, 20))
    # ydotool 0.1.8 has no wheel/scroll command, so use Page_Down/Page_Up keys.
    # These work on Wayland-native windows (which xdotool's button-clicks don't reach).
    if _YDOTOOL:
        key = {"up": "Page_Up", "down": "Page_Down", "left": "Home", "right": "End"}.get(direction, "Page_Down")
        for _ in range(amount):
            if not _run([_YDOTOOL, "key", key]):
                break
        return True
    if _XDOTOOL:
        # X11 fallback — actual mouse wheel events. Only works in X11 / XWayland apps.
        btn = {"up": "4", "down": "5", "left": "6", "right": "7"}.get(direction, "5")
        for _ in range(amount):
            _run([_XDOTOOL, "click", btn])
        return True
    return False


# --- Screen-position clicks (center, middle, etc.) -------------------------

_screen_size_cache: tuple[int, int] | None = None


def _get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor. Cached after first call."""
    global _screen_size_cache
    if _screen_size_cache is not None:
        return _screen_size_cache

    width, height = 1920, 1080  # sensible laptop default
    try:
        r = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=2)
        primary_line = None
        first_connected = None
        for line in r.stdout.splitlines():
            if " connected primary" in line:
                primary_line = line
                break
            if " connected" in line and not first_connected:
                first_connected = line
        line = primary_line or first_connected
        if line:
            m = re.search(r"\b(\d{3,5})x(\d{3,5})\b", line)
            if m:
                width, height = int(m.group(1)), int(m.group(2))
    except Exception:
        pass

    _screen_size_cache = (width, height)
    return _screen_size_cache


def click_at_position(position: str = "center") -> bool:
    """Click at a named position on screen. position: center/middle/top/bottom/left/right."""
    w, h = _get_screen_size()
    coords = {
        "center": (w // 2, h // 2),
        "middle": (w // 2, h // 2),
        "centre": (w // 2, h // 2),
        "top":    (w // 2, max(80, h // 10)),
        "bottom": (w // 2, h - max(80, h // 10)),
        "left":   (max(80, w // 10), h // 2),
        "right":  (w - max(80, w // 10), h // 2),
    }.get(position)
    if not coords:
        return False
    x, y = coords

    # ydotool first — works on Wayland-native windows. ydotool 0.1.8 mousemove
    # is RELATIVE only, so use the corner-trick: jump to top-left then to target.
    if _YDOTOOL:
        _run([_YDOTOOL, "mousemove", "--", "-10000", "-10000"])
        _run([_YDOTOOL, "mousemove", "--", str(x), str(y)])
        return _run([_YDOTOOL, "click", "1"])
    if _XDOTOOL:
        return _run([_XDOTOOL, "mousemove", str(x), str(y), "click", "1"])
    return False


# --- Voice-command handler --------------------------------------------------

_DIRECTION_RE = re.compile(r"\b(up|down|left|right)\b")
_AMOUNT_RE = re.compile(r"\b(\d+)\s*(?:times|x)?\b")
_CLICK_COORDS_RE = re.compile(r"\bclick\b[^0-9]*(\d{2,4})[,\s]+(\d{2,4})")
_CLICK_POSITION_RE = re.compile(r"\bclick\b.*?\b(center|centre|middle|top|bottom|left|right)\b")

_MODIFIER = r"(?:ctrl|control|alt|shift|super|command|meta|win)"
_BARE_COMBO_RE = re.compile(
    rf"^\s*({_MODIFIER}(?:[\s+\-]+{_MODIFIER})*)[\s+\-]+(\S+?)\s*\.?\s*$"
)


def _amount_from(text: str, default: int = 3) -> int:
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    m = _AMOUNT_RE.search(text)
    if m:
        return int(m.group(1))
    return default


def handle_control(text: str) -> tuple[str, bool]:
    if not HAS_BACKEND:
        return "", False

    # Type — "type out hello world" / "type hello world"
    m = re.search(r"\btype(?:\s+out)?\s+(.+)", text)
    if m:
        body = m.group(1).strip().rstrip(".")
        if type_text(body):
            return "Typed.", True
        return "I couldn't type that — too long or input failed.", True

    # Press / hit a key — "press enter" / "press control c" / "hit alt tab"
    m = re.search(r"\b(?:press|hit)\s+(.+)", text)
    if m:
        combo = m.group(1).strip().rstrip(".")
        # Garbage detector: if too many words, this is probably "press X on the Y of Z"
        # which Gemini should interpret as a compound action (focus + key).
        if len(re.split(r"\s+", combo)) > 4:
            return "", False
        if press_keys(combo):
            return f"Pressed {combo}.", True
        # press_keys rejected as invalid combo → fall through to Gemini
        return "", False

    # Bare modifier+key combo — "control c", "alt tab", "ctrl shift t"
    m = _BARE_COMBO_RE.match(text)
    if m:
        combo = f"{m.group(1)} {m.group(2)}"
        if press_keys(combo):
            return f"Pressed {combo}.", True
        return "I couldn't press that.", True

    # Scroll — "scroll down" / "scroll up three times"
    if "scroll" in text:
        d = _DIRECTION_RE.search(text)
        direction = d.group(1) if d else "down"
        amount = _amount_from(text, default=3)
        if scroll(direction, amount):
            return f"Scrolled {direction}.", True
        return "I couldn't scroll.", True

    # Click at coords — "click at 500 300" / "click 500, 300"
    m = _CLICK_COORDS_RE.search(text)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        button = (
            "right" if "right click" in text
            else "middle" if "middle click" in text
            else "left"
        )
        if click(x, y, button):
            return "Clicked.", True
        return "I couldn't click there.", True

    # Click at named screen position — "click at the center of the screen", "click middle", etc.
    m = _CLICK_POSITION_RE.search(text)
    if m:
        position = m.group(1).lower()
        # Normalize "middle click" / "right click" — those mean BUTTON, not POSITION.
        # The previous coords branch already handled them; here we also need to skip those phrasings.
        if f"{position} click" in text:
            return "", False
        if click_at_position(position):
            return f"Clicked {position}.", True
        return f"I couldn't click {position}.", True

    return "", False
