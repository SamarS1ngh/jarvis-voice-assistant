import subprocess
import re
import datetime


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def handle_system(text: str) -> tuple[str, bool]:
    # Mute — works as a bare command too ("mute" / "silent")
    if "mute" in text or text.strip() == "silent":
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        return "Toggled mute.", True

    # Volume control
    if "volume" in text or "sound" in text:
        if "up" in text or "increase" in text or "raise" in text:
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"])
            return "Volume increased.", True
        if "down" in text or "decrease" in text or "lower" in text:
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"])
            return "Volume decreased.", True
        match = re.search(r"(\d+)\s*%?", text)
        if match:
            level = match.group(1)
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
            return f"Volume set to {level} percent.", True

    # Brightness control
    if "brightness" in text or "bright" in text:
        if "up" in text or "increase" in text:
            _run(["brightnessctl", "set", "+10%"])
            return "Brightness increased.", True
        if "down" in text or "decrease" in text:
            _run(["brightnessctl", "set", "10%-"])
            return "Brightness decreased.", True
        match = re.search(r"(\d+)\s*%?", text)
        if match:
            level = match.group(1)
            _run(["brightnessctl", "set", f"{level}%"])
            return f"Brightness set to {level} percent.", True

    # Lock screen
    if "lock" in text and ("screen" in text or "computer" in text or "pc" in text):
        _run(["loginctl", "lock-session"])
        return "Locking screen.", True

    # Shutdown
    if "shutdown" in text or "shut down" in text or "power off" in text:
        return "Shutting down in 10 seconds. Say cancel to abort.", True
        # Note: actual shutdown handled in main.py with confirmation

    # Restart
    if "restart" in text or "reboot" in text:
        return "Restarting in 10 seconds. Say cancel to abort.", True

    # Suspend / sleep
    if "suspend" in text or "sleep" in text or "hibernate" in text:
        _run(["systemctl", "suspend"])
        return "Going to sleep.", True

    # Screenshot
    if "screenshot" in text or "screen shot" in text or "screen capture" in text:
        if "area" in text or "select" in text or "region" in text:
            subprocess.Popen(
                ["scrot", "-s", "-e", "mv $f ~/Pictures/"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "Select an area for the screenshot.", True
        else:
            subprocess.Popen(
                ["scrot", "-e", "mv $f ~/Pictures/"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "Screenshot taken and saved to Pictures.", True

    # Time
    if "time" in text and ("what" in text or "tell" in text or "current" in text):
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The time is {now}.", True

    # Date
    if "date" in text and ("what" in text or "tell" in text or "today" in text):
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {today}.", True

    # Wi-Fi
    if "wifi" in text or "wi-fi" in text or "wireless" in text:
        if "off" in text or "disable" in text or "disconnect" in text:
            _run(["nmcli", "radio", "wifi", "off"])
            return "Wi-Fi turned off.", True
        if "on" in text or "enable" in text or "connect" in text:
            _run(["nmcli", "radio", "wifi", "on"])
            return "Wi-Fi turned on.", True

    # Battery
    if "battery" in text:
        output = _run(["cat", "/sys/class/power_supply/BAT0/capacity"])
        if output:
            return f"Battery is at {output} percent.", True
        return "Could not read battery level.", True

    return "", False
