import json
import subprocess
import time

from commands import control
from jarvis_log import log
import vision
import config

SYSTEM_PROMPT = """You are Jarvis, a voice-controlled Linux PC assistant. The user gives you a spoken command.
You must respond with a JSON object describing the action to take.

Available actions:
- {"action": "speak", "text": "..."} — just say something back to the user
- {"action": "open_url", "url": "..."} — open a URL in the browser
- {"action": "open_app", "command": "..."} — run a Linux command to open an app
- {"action": "run_command", "command": "...", "speak": "..."} — run a shell command and speak the result description
- {"action": "notify", "title": "...", "body": "..."} — show a desktop notification
- {"action": "type_text", "text": "..."} — type text at the current cursor position (max 500 chars)
- {"action": "press_key", "keys": "..."} — press a key or combo. Use xdotool keysyms: Return, Tab, Escape, BackSpace, Delete, Up, Down, Left, Right, Page_Up, Page_Down, F1-F12, or combos like "ctrl+c", "alt+Tab", "ctrl+shift+t"
- {"action": "click", "x": 500, "y": 300, "button": "left"} — click at absolute screen coordinates (button: left/middle/right)
- {"action": "scroll", "direction": "down", "amount": 3} — scroll the active window (direction: up/down/left/right)
- {"action": "see_and_click", "description": "..."} — take a screenshot and click on the UI element matching the description. Use this when the user names an on-screen element by description rather than coordinates (e.g. "click the play button", "close that tab", "click reply", "click the search bar")
- {"action": "describe_screen", "question": "..."} — take a screenshot and answer a question about what is visible. Use this when the user asks what something on screen says or shows (e.g. "what does that error say", "what's on my screen", "how many tabs are open")
- {"action": "switch_workspace_by_name", "name": "..."} — opens the Activities overview, locates the workspace tile labeled with that name (Space Bar extension shows them), and clicks it. Use for spoken commands like "switch to the Code workspace" or "go to my web workspace". Numeric switching ("switch to workspace 3") is handled before you see the request — you only need this for NAMED workspaces.
- {"action": "find_and_type", "element": "...", "text": "..."} — takes a screenshot, finds a UI element by description, clicks it (focuses it), then types the text. Use this for "search for X" / "find X" inside a currently-open app like WhatsApp, Gmail, Slack — e.g. {"element": "the WhatsApp search bar at the top", "text": "Saloni"}.

Multi-step orchestration:
- {"action": "sequence", "steps": [<action1>, <action2>, ...]} — run several actions in order, with a 700ms delay between them so prior actions can settle (page loads, focus changes, etc.). Use this whenever the user gives a compound command. Examples:
  - "open Telegram and search for Simran" -> {"action": "sequence", "steps": [
      {"action": "open_app", "command": "telegram"},
      {"action": "find_and_type", "element": "the Telegram search bar at the top of the chat list", "text": "Simran"}
    ]}
  - "open Steam in a new workspace" -> {"action": "sequence", "steps": [
      {"action": "press_key", "keys": "ctrl+alt+Right"},
      {"action": "open_app", "command": "steam"}
    ]}  (Ctrl+Alt+Right past the last workspace creates a new one because dynamic-workspaces=true on this system)
  - "open Firefox in workspace 3" -> {"action": "sequence", "steps": [
      {"action": "press_key", "keys": "super+alt+3"},
      {"action": "open_app", "command": "firefox"}
    ]}
  - "play the video" / "pause the video" -> {"action": "sequence", "steps": [
      {"action": "see_and_click", "description": "the center of the video player or the play/pause button"},
      {"action": "press_key", "keys": "space"}
    ]}  (the click ensures the player has keyboard focus before space — without focus, space goes to whatever window had focus before, often the terminal)
  - "exit fullscreen" / "escape fullscreen" / "leave fullscreen" -> {"action": "sequence", "steps": [
      {"action": "see_and_click", "description": "the center of the video player or any visible part of the fullscreen content"},
      {"action": "press_key", "keys": "Escape"}
    ]}  (same focus problem — Escape only exits fullscreen if the player has focus)
  - "clear the search bar in <app>" -> {"action": "sequence", "steps": [
      {"action": "find_and_type", "element": "the <app> search bar", "text": ""},
      {"action": "press_key", "keys": "ctrl+a"},
      {"action": "press_key", "keys": "Delete"}
    ]}  (Escape does NOT clear text fields — only Ctrl+A then Delete reliably clears. Step 1 with empty text just focuses the bar.)
  - "clear the search bar and search X in <app>" -> sequence: find_and_type with text="" to focus, ctrl+a, Delete, then find_and_type with text=X

Focus rule (CRITICAL): keystrokes only affect the focused window. If you want a keystroke to act on a specific app/element, click it first (via see_and_click or find_and_type with empty text). Without that, keystrokes go to whatever had focus when Jarvis processed the command — usually the terminal Jarvis runs in.

Rules:
- Always respond with valid JSON only, no extra text.
- For questions (weather, math, trivia, translations), use "speak" to answer directly.
- For music/video requests, use "open_url" with a YouTube search URL.
- Never run destructive commands (rm -rf, mkfs, dd, etc.).
- Only use type_text / press_key / click / scroll when the user explicitly asks to type, press, click, or scroll at coordinates.
- Prefer see_and_click over click(x,y) when the user describes an element by appearance rather than coordinates.
- Keep spoken responses concise (1-2 sentences).
- If the conversation has prior turns, use them to resolve follow-ups like "again", "the other one", "and Mumbai?", "louder". Maintain continuity with what was just asked. For example, if the user opened YouTube and then says "search for lo-fi", interpret it as a YouTube search, not a Google search.

Linux/Wayland-specific hints (this is a GNOME Wayland session):
- For run_command, if you want the command's first line of stdout spoken, include the literal placeholder {result} in your "speak" string. The system substitutes it before TTS. Example: {"action": "run_command", "command": "date +%A", "speak": "Today is {result}."}

- COUNTING TERMINAL WINDOWS — gnome-terminal uses a server-client model: ALL terminal windows share one gnome-terminal-server process. Counting that server gives 1, not the window count. Also `pgrep -f gnome-terminal-server` falsely matches any shell whose command line contains that string (including the very command you're running). The reliable command is:
    ps --no-headers --ppid $(pidof gnome-terminal-server | tr ' ' ',') 2>/dev/null | wc -l
  This counts child shells of all server processes — equal to the number of terminal tabs/windows.

- COUNTING OTHER APPS — for apps that spawn one process per window (Edge, Firefox, Chrome, Code), use `pgrep -fc` but anchor the pattern to the binary path to avoid self-matching:
    Edge:    pgrep -fc '^[^ ]*microsoft-edge'
    Firefox: pgrep -fc '^[^ ]*firefox'
    Chrome:  pgrep -fc '^[^ ]*chrome'
    Code:    pgrep -fc '^[^ ]*/code '

- VISION LIMITS — describe_screen / see_and_click ONLY see what's currently on the active monitor. You CANNOT see: minimized windows, windows on other workspaces, content of unfocused background windows, or anything off-screen. If the user asks about a window that isn't currently visible, tell them honestly: "I can only see what's currently on screen — bring that window to the front and ask me again." Do NOT pretend to be able to switch to and inspect a hidden window in one step.

- WINDOW SWITCHING is unreliable on Wayland. The "switch to X" handler attempts it via the GNOME Activities Overview, but it can fail silently if the app isn't found. Don't promise to switch to a window before reading it.

- For "how many X are open", prefer run_command (which sees ALL processes/windows, including hidden ones) over describe_screen (which only sees the visible screen).
- For "what's on screen" or "what does that say", use describe_screen.
- wmctrl does not work on Wayland for native Wayland windows. Don't suggest it.
"""


class GeminiBrain:
    def __init__(self):
        self.client = None
        # MK-2: rolling conversation history. Each entry is a dict
        # {"role": "user"|"model", "parts": [{"text": ...}]}
        self.history: list[dict] = []
        self.last_turn_time: float = 0.0
        try:
            from google import genai
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            self.model_name = config.GEMINI_MODEL
        except Exception as e:
            print(f"Gemini init failed: {e}")

    def clear_history(self):
        """Drop all conversation context. Called on 'new topic' / 'forget that'."""
        self.history = []
        self.last_turn_time = 0.0

    def _expire_if_stale(self):
        """Drop history if the user has been silent past the TTL."""
        if self.history and (time.time() - self.last_turn_time) > config.CONTEXT_TTL_SECONDS:
            self.history = []

    def process(self, text: str) -> str:
        """Send command to Gemini (with rolling history) and execute the returned action."""
        if not self.client:
            log.warning("Gemini client not available")
            return "Smart mode is not available right now."

        self._expire_if_stale()
        log.info(f"GEMINI INPUT: {text!r} (history_len={len(self.history)})")

        user_msg = {"role": "user", "parts": [{"text": text}]}
        contents = self.history + [user_msg]

        response = None
        try:
            from google.genai import types
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                ),
            )
            raw = response.text.strip()
            log.info(f"GEMINI RAW: {raw[:300]!r}")

            # Clean markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            # Commit the turn to history (raw model output, before execution)
            self.history.append(user_msg)
            self.history.append({"role": "model", "parts": [{"text": raw}]})
            self.last_turn_time = time.time()

            # Cap to last N exchanges (1 exchange = user msg + model msg)
            max_msgs = config.CONTEXT_MAX_TURNS * 2
            if len(self.history) > max_msgs:
                self.history = self.history[-max_msgs:]

            action = json.loads(raw)
            log.info(f"PARSED ACTION: {action}")
            result = self._execute_sequence_or_single(action)
            log.info(f"EXECUTED: result={result!r}")
            return result
        except json.JSONDecodeError:
            # Gemini returned plain text instead of JSON — just speak it
            fallback = response.text.strip()[:200] if (response and response.text) else "I couldn't process that."
            log.info(f"GEMINI returned non-JSON, speaking raw: {fallback!r}")
            return fallback
        except Exception as e:
            log.exception(f"Gemini error: {e}")
            print(f"Gemini error: {e}")
            return "I couldn't reach smart mode. Check your internet connection."

    def _execute_sequence_or_single(self, action) -> str:
        """Dispatch single action or a sequence of actions returned by Gemini."""
        # Sequence form: {"action": "sequence", "steps": [...]}
        if isinstance(action, dict) and action.get("action") == "sequence":
            steps = action.get("steps", []) or []
            return self._run_sequence(steps)
        # Bare list form: [{...}, {...}]
        if isinstance(action, list):
            return self._run_sequence(action)
        # Single action
        return self._execute(action)

    def _run_sequence(self, steps: list) -> str:
        """Run a list of actions in order, with a settle delay between them."""
        if not steps:
            return "Nothing to do."
        results = []
        for i, step in enumerate(steps):
            if i > 0:
                time.sleep(0.7)  # let previous action settle (page loads, focus, etc.)
            log.info(f"SEQUENCE step {i+1}/{len(steps)}: {step}")
            result = self._execute(step)
            log.info(f"SEQUENCE step {i+1} result: {result!r}")
            results.append(result)
        # Speak the last meaningful result
        return results[-1] if results[-1] else "Done."

    def _execute(self, action: dict) -> str:
        """Execute a single Gemini-returned action."""
        act = action.get("action", "")

        if act == "speak":
            return action.get("text", "Done.")

        if act == "open_url":
            url = action.get("url", "")
            if url:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "Opening that for you."
            return "I don't have a URL to open."

        if act == "open_app":
            cmd = action.get("command", "")
            if not cmd:
                return "I don't know which app to open."
            try:
                subprocess.Popen(
                    cmd.split(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return action.get("speak", f"Opening {cmd}.")
            except FileNotFoundError:
                # Binary not in PATH — fall back to gtk-launch via desktop-file lookup.
                # Catches snap, flatpak, AppImage installs that Gemini guessed wrong about.
                from commands.apps import _try_gtk_launch
                for variant in (cmd, cmd.replace("-", " "), cmd.replace("_", " ")):
                    if _try_gtk_launch(variant):
                        return action.get("speak", f"Opening {cmd}.")
                return f"I couldn't find {cmd} on this system."

        if act == "run_command":
            cmd = action.get("command", "")
            dangerous = ["rm -rf", "mkfs", "dd if=", ":(){", "fork", "shutdown", "reboot"]
            for d in dangerous:
                if d in cmd:
                    return "I can't run that command. It looks dangerous."
            if cmd:
                try:
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True, timeout=10,
                    )
                    output = result.stdout.strip()
                    first_line = output.split("\n")[0][:150] if output else ""

                    speak_text = action.get("speak", "")
                    if speak_text:
                        # Substitute placeholders with the command output
                        sub = first_line if first_line else "no output"
                        for ph in ("{{result}}", "{result}", "{{output}}", "{output}"):
                            speak_text = speak_text.replace(ph, sub)
                        return speak_text
                    if first_line:
                        return first_line
                    return "Command executed."
                except subprocess.TimeoutExpired:
                    return "Command timed out."

        if act == "notify":
            title = action.get("title", "JARVIS")
            body = action.get("body", "")
            subprocess.run(
                ["notify-send", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return action.get("speak", "Notification sent.")

        if act == "type_text":
            text = action.get("text", "")
            if control.type_text(text):
                return action.get("speak", "Typed.")
            return "I couldn't type that."

        if act == "press_key":
            keys = action.get("keys", "")
            if control.press_keys(keys):
                return action.get("speak", f"Pressed {keys}.")
            return "I couldn't press that."

        if act == "click":
            x = action.get("x")
            y = action.get("y")
            button = action.get("button", "left")
            if x is not None and y is not None and control.click(int(x), int(y), button):
                return action.get("speak", "Clicked.")
            return "I couldn't click there."

        if act == "scroll":
            direction = action.get("direction", "down")
            amount = int(action.get("amount", 3))
            if control.scroll(direction, amount):
                return action.get("speak", f"Scrolled {direction}.")
            return "I couldn't scroll."

        if act == "see_and_click":
            description = action.get("description", "").strip()
            if not description:
                return "I need to know what to click."
            img = vision.take_screenshot()
            if not img:
                return "I couldn't capture the screen."
            coords = vision.find_element(self.client, self.model_name, img, description)
            if not coords:
                return f"I don't see {description} on the screen."
            x, y = coords
            if control.click(x, y, "left"):
                return action.get("speak", f"Clicked {description}.")
            return f"I found {description} but couldn't click it."

        if act == "describe_screen":
            question = action.get("question", "Describe what is on the screen briefly.")
            img = vision.take_screenshot()
            if not img:
                return "I couldn't capture the screen."
            return vision.describe_screen(self.client, self.model_name, img, question)

        if act == "find_and_type":
            element = action.get("element", "").strip()
            text_to_type = action.get("text", "")
            if not element:
                return "I need to know what element to find."
            img = vision.take_screenshot()
            if not img:
                return "I couldn't capture the screen."
            coords = vision.find_element(self.client, self.model_name, img, element)
            if not coords:
                return f"I don't see {element} on the screen."
            if not control.click(coords[0], coords[1], "left"):
                return f"I found {element} but couldn't click it."
            time.sleep(0.3)  # let focus settle before typing
            if not text_to_type:
                # Empty text = just focus the element (useful as step 1 of a clear-then-type sequence)
                return action.get("speak", f"Focused {element}.")
            if control.type_text(text_to_type):
                return action.get("speak", f"Typed in {element}.")
            return f"Clicked {element} but couldn't type."

        if act == "switch_workspace_by_name":
            name = action.get("name", "").strip()
            if not name:
                return "I need a workspace name."
            import shutil
            ydotool = shutil.which("ydotool")
            if not ydotool:
                return "I can't open the workspaces overview without ydotool."
            # Open Activities (workspace strip appears at top of screen)
            subprocess.run([ydotool, "key", "super"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.8)
            img = vision.take_screenshot()
            if not img:
                subprocess.run([ydotool, "key", "Escape"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "I couldn't capture the screen."
            coords = vision.find_element(
                self.client, self.model_name, img,
                f"the workspace tile labeled '{name}' in the workspace strip at the top of the GNOME Activities overview"
            )
            if not coords:
                subprocess.run([ydotool, "key", "Escape"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"I don't see a workspace named {name}."
            if control.click(coords[0], coords[1], "left"):
                return action.get("speak", f"Switched to {name} workspace.")
            return f"Found {name} workspace but couldn't click it."

        return "I'm not sure how to do that."
