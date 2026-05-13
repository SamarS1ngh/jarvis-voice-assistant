"""MK-3: Screen vision via Gemini multi-modal.

Takes a screenshot and asks Gemini Vision to either locate a UI element
(returning click coordinates) or describe what's on screen.

Screenshot backends, tried in order:
  1. grim              — Wayland-native, most reliable on Wayland sessions
  2. gnome-screenshot  — works on GNOME Wayland
  3. scrot             — X11 / XWayland only, may produce black images on Wayland
"""

import json
import os
import shutil
import subprocess
import tempfile

from jarvis_log import log


_GRIM = shutil.which("grim")
_GNOME_SS = shutil.which("gnome-screenshot")
_SCROT = shutil.which("scrot")
HAS_SCREENSHOT = bool(_GRIM or _GNOME_SS or _SCROT)


def _set_event_sounds(enabled: bool) -> bool | None:
    """Toggle GNOME event sounds. Returns the PREVIOUS state ('true'/'false') or None on failure."""
    try:
        r = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.sound", "event-sounds"],
            capture_output=True, text=True, timeout=2,
        )
        previous = r.stdout.strip()  # 'true' or 'false'
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.sound", "event-sounds",
             "true" if enabled else "false"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        return previous
    except Exception:
        return None


def _try_grim(path: str) -> bytes | None:
    """Try grim with one retry — handles transient compositor failures during animations."""
    import time as _time
    for attempt in range(2):
        if attempt > 0:
            _time.sleep(0.25)
        try:
            r = subprocess.run(
                [_GRIM, path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if r.returncode == 0 and os.path.getsize(path) > 0:
                with open(path, "rb") as f:
                    data = f.read()
                if attempt > 0:
                    log.info(f"take_screenshot: grim succeeded on retry {attempt}")
                return data
        except (subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"take_screenshot: grim attempt {attempt} raised {e}")
    return None


def take_screenshot() -> bytes | None:
    """Capture the current screen and return PNG bytes, or None on failure.

    Tries grim first (Wayland-native, silent, no shutter sound). Falls back to
    gnome-screenshot or scrot, but mutes GNOME event sounds during the capture
    so the camera-shutter click doesn't play.
    """
    if not HAS_SCREENSHOT:
        log.warning("take_screenshot: no backend available")
        return None

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    path = tmp.name

    try:
        # 1) Grim — silent natively, the preferred path on Wayland
        if _GRIM:
            data = _try_grim(path)
            if data:
                log.info(f"take_screenshot: grim -> {len(data)} bytes (silent)")
                return data
            log.debug("take_screenshot: grim failed both attempts, falling back")

        # 2) Fallback paths — these may play the system shutter sound, so mute first
        prev_sounds = _set_event_sounds(False)
        try:
            for cmd, label in [
                ([_GNOME_SS, "-f", path] if _GNOME_SS else None, "gnome-screenshot"),
                ([_SCROT, "-z", path] if _SCROT else None, "scrot"),
            ]:
                if not cmd:
                    continue
                try:
                    r = subprocess.run(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                    if r.returncode == 0 and os.path.getsize(path) > 0:
                        with open(path, "rb") as f:
                            data = f.read()
                        log.info(f"take_screenshot: {label} -> {len(data)} bytes (sounds muted)")
                        return data
                    else:
                        log.debug(f"take_screenshot: {label} failed (rc={r.returncode})")
                except (subprocess.TimeoutExpired, OSError) as e:
                    log.debug(f"take_screenshot: {label} raised {e}")
        finally:
            # Restore the previous event-sounds state
            if prev_sounds in ("true", "false"):
                _set_event_sounds(prev_sounds == "true")

        log.warning("take_screenshot: all backends failed")
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def find_element(client, model: str, image_bytes: bytes, description: str) -> tuple[int, int] | None:
    """Ask Gemini Vision to locate a UI element on screen.

    Returns (x, y) center coordinates or None if not found / not parseable.
    """
    from google.genai import types

    prompt = (
        f"In this screenshot, find: {description}\n\n"
        "Return ONLY a JSON object — no prose, no fences. Format:\n"
        '  {"found": true, "x": <int>, "y": <int>}  if visible\n'
        '  {"found": false}                          if not visible\n\n'
        "x,y are pixel coordinates of the element's center. "
        "Origin is the top-left of the image. "
        "Be precise — these coordinates will be used to click."
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                prompt,
            ],
        )
        data = json.loads(_strip_fences(response.text or ""))
        if data.get("found") and "x" in data and "y" in data:
            return int(data["x"]), int(data["y"])
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
        pass
    except Exception as e:
        print(f"Vision find_element error: {e}")
    return None


def describe_screen(client, model: str, image_bytes: bytes, question: str) -> str:
    """Ask Gemini Vision a free-form question about the current screen."""
    from google.genai import types

    full_prompt = (
        f"{question}\n\n"
        "Answer concisely in 1-2 sentences for a voice assistant to read aloud. "
        "Don't mention the screenshot itself."
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                full_prompt,
            ],
        )
        text = (response.text or "").strip()
        return text[:400] if text else "I couldn't read what's on the screen."
    except Exception as e:
        print(f"Vision describe_screen error: {e}")
        return "I couldn't read the screen right now."
