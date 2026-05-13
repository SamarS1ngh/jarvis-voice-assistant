import os
import re
import shutil
import subprocess
import time
import urllib.parse


_YDOTOOL = shutil.which("ydotool")
_GTK_LAUNCH = shutil.which("gtk-launch")
_IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


# Spoken app name -> .desktop file basename (used by gtk-launch)
DESKTOP_SLUGS = {
    "microsoft edge":   "microsoft-edge",
    "edge":             "microsoft-edge",
    "msedge":           "microsoft-edge",
    "firefox":          "firefox",
    "chrome":           "google-chrome",
    "google chrome":    "google-chrome",
    "terminal":         "org.gnome.Terminal",
    "gnome terminal":   "org.gnome.Terminal",
    "vs code":          "code",
    "vscode":           "code",
    "code":             "code",
    "files":            "org.gnome.Nautilus",
    "file manager":     "org.gnome.Nautilus",
    "nautilus":         "org.gnome.Nautilus",
    "calculator":       "org.gnome.Calculator",
    "settings":         "gnome-control-center",
    "spotify":          "spotify",
    "discord":          "discord",
    "slack":            "slack",
}

DESKTOP_SEARCH_DIRS = [
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
    os.path.expanduser("~/.local/share/applications"),
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
]


def _find_desktop_slug(name: str) -> str | None:
    """Find a .desktop file matching the spoken app name. Returns the slug (no .desktop)."""
    import glob
    candidates = []
    if name in DESKTOP_SLUGS:
        candidates.append(DESKTOP_SLUGS[name])
    slug_dash = name.replace(" ", "-")
    slug_nospace = name.replace(" ", "")
    candidates += [slug_dash, slug_nospace]

    # 1) Exact filename match in any search dir
    for slug in candidates:
        for d in DESKTOP_SEARCH_DIRS:
            if os.path.isfile(os.path.join(d, f"{slug}.desktop")):
                return slug

    # 2) Fuzzy glob — handles snap naming like firefox_firefox.desktop, code_code.desktop.
    #    Collect everything, drop variants/handlers, return the shortest canonical match.
    SKIP_TOKENS = (
        "preferences", "settings", "uninstall", "remove", "license",
        "url-handler", "uri-handler", "scheme-handler",
    )
    all_matches: list[str] = []
    for slug in candidates + [name.split()[0]]:
        for d in DESKTOP_SEARCH_DIRS:
            for path in glob.glob(os.path.join(d, f"*{slug}*.desktop")):
                base = os.path.basename(path)[:-len(".desktop")]
                if any(skip in base.lower() for skip in SKIP_TOKENS):
                    continue
                all_matches.append(base)
    if all_matches:
        # Prefer shortest (most canonical) and dedupe
        return sorted(set(all_matches), key=len)[0]
    return None


def _try_gtk_launch(name: str) -> bool:
    """Activate via gtk-launch — focuses existing instance for DBus-aware apps."""
    if not _GTK_LAUNCH:
        return False
    slug = _find_desktop_slug(name)
    if not slug:
        return False
    try:
        r = subprocess.run(
            [_GTK_LAUNCH, slug],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False


def _try_overview_switch(name: str) -> bool:
    """GNOME Overview: tap Super, type the app name, hit Enter.

    Works for Wayland-native apps that wmctrl can't see. Requires ydotool.
    Sleeps are tuned for GNOME's overview animation + search debounce.
    """
    if not _YDOTOOL:
        return False
    try:
        subprocess.run([_YDOTOOL, "key", "super"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)  # let Overview finish animating in
        subprocess.run([_YDOTOOL, "type", "--", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)  # let GNOME's search debounce + populate results
        subprocess.run([_YDOTOOL, "key", "Return"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# App name -> command mapping
APPS = {
    "firefox": "firefox",
    "browser": "firefox",
    "chrome": "google-chrome",
    "files": "nautilus",
    "file manager": "nautilus",
    "terminal": "gnome-terminal",
    "calculator": "gnome-calculator",
    "settings": "gnome-control-center",
    "text editor": "gedit",
    "editor": "gedit",
    "music": "rhythmbox",
    "videos": "totem",
    "image viewer": "eog",
    "screenshot": "gnome-screenshot",
    "system monitor": "gnome-system-monitor",
    "software center": "gnome-software",
    "discord": "discord",
    "spotify": "spotify",
    "slack": "slack",
    "code": "code",
    "vs code": "code",
    "vscode": "code",
}

WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "linkedin": "https://www.linkedin.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "chatgpt": "https://chat.openai.com",
    "whatsapp": "https://web.whatsapp.com",
}


def handle_apps(text: str) -> tuple[str, bool]:
    # Open an app
    if re.search(r"\b(open|launch|start|run)\b", text):
        # If the user mentions a workspace context, this is a multi-step intent
        # ("open X in a new workspace") — let Gemini orchestrate the sequence
        # instead of greedily launching X in the current workspace.
        if re.search(r"\b(workspace|workplace|work\s+space|box\s+place)\b", text):
            return "", False

        # 1) Curated APPS dict (fast path, but recovers via gtk-launch if binary missing)
        for name, cmd in APPS.items():
            if name in text:
                try:
                    subprocess.Popen(
                        [cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return f"Opening {name}.", True
                except FileNotFoundError:
                    if _try_gtk_launch(name):
                        return f"Opening {name}.", True
                    return f"Sorry, {name} is not installed.", True

        # 2) Open a website
        for name, url in WEBSITES.items():
            if name in text:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"Opening {name}.", True

        # 3) Fall back to gtk-launch with the captured name —
        #    catches snap/flatpak/AppImage apps not in the curated dict
        m = re.search(r"\b(?:open|launch|start|run)\s+(.+)", text)
        if m:
            target = m.group(1).strip().rstrip(".")
            target = re.sub(r"\s+(app|application|program)$", "", target).strip()
            if target and _try_gtk_launch(target):
                return f"Opening {target}.", True

    # Search the web — only for EXPLICIT Google/web intent.
    # Plain "search for X" falls through to Gemini, which can route it via
    # find_and_type to the active app's search bar (e.g., WhatsApp, Gmail).
    if re.search(r"\b(google|the\s+web)\b", text):
        match = re.search(r"\bsearch\s+(?:google\s+|on\s+google\s+|the\s+web\s+|on\s+the\s+web\s+)?(?:for\s+)?(.+)", text)
        if match:
            query = match.group(1).strip().rstrip(".")
            query = re.sub(r"\b(?:on\s+(?:google|the\s+web)|google\s+(?:for|search))\b", "", query).strip()
            url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Searching Google for {query}.", True

    # Close an app
    if re.search(r"\b(close|kill|quit|exit)\b", text):
        for name, cmd in APPS.items():
            if name in text:
                subprocess.run(
                    ["pkill", "-f", cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"Closing {name}.", True

    # Switch to window
    match = re.search(r"\bswitch\s+to\s+(.+)", text)
    if match:
        window_name = match.group(1).strip().rstrip(".")
        # If it mentions tab/workspace, those have dedicated handlers — don't poach them
        if re.search(r"\b(tab|workspace|workplace|work\s+space)\b", window_name):
            return "", False
        # Strip filler suffixes: "switch to firefox window" -> "firefox"
        window_name = re.sub(r"\s+(window|app|the\s+app)$", "", window_name).strip()

        # 1) Try gtk-launch — clean DBus activation, focuses existing instance
        #    for apps that support it (Edge, Firefox, GNOME apps, etc.)
        if _try_gtk_launch(window_name):
            return f"Switching to {window_name}.", True

        # 2) X11 only — wmctrl. Skip on Wayland (can't see native windows)
        if not _IS_WAYLAND:
            r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True)
            if window_name.lower() in r.stdout.lower():
                subprocess.run(["wmctrl", "-a", window_name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Switching to {window_name}.", True

        # 3) Last resort — GNOME Overview keystroke trick (timing-sensitive)
        if _try_overview_switch(window_name):
            return f"Switching to {window_name}.", True

        return f"I couldn't switch to {window_name}.", True

    # Minimize/maximize
    if "minimize" in text:
        subprocess.run(["xdotool", "getactivewindow", "windowminimize"])
        return "Window minimized.", True
    if "maximize" in text:
        subprocess.run(
            ["wmctrl", "-r", ":ACTIVE:", "-b", "toggle,maximized_vert,maximized_horz"]
        )
        return "Window maximized.", True

    return "", False
