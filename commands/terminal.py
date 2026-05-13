import subprocess
import re


def handle_terminal(text: str) -> tuple[str, bool]:
    # Open terminal
    if re.search(r"open\s+(?:a\s+)?(?:new\s+)?terminal", text):
        subprocess.Popen(
            ["gnome-terminal"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "Opening terminal.", True

    # Open VS Code
    if re.search(r"open\s+(?:vs\s*code|code|editor)", text):
        subprocess.Popen(
            ["code"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "Opening VS Code.", True

    # Run a terminal command
    match = re.search(r"(?:run|execute)\s+(?:command\s+)?(.+)", text)
    if match:
        cmd = match.group(1).strip()
        # Safety: block dangerous commands
        dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"]
        for d in dangerous:
            if d in cmd:
                return "I can't run that command. It looks dangerous.", True
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            if output:
                # Speak just the first line to keep it brief
                first_line = output.split("\n")[0]
                return f"Result: {first_line}", True
            elif result.returncode == 0:
                return "Command executed successfully.", True
            else:
                return f"Command failed: {result.stderr.strip()[:100]}", True
        except subprocess.TimeoutExpired:
            return "Command timed out.", True

    # Git commands
    if "git status" in text:
        result = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True,
        )
        output = result.stdout.strip()
        if output:
            lines = len(output.split("\n"))
            return f"Git status shows {lines} changed files.", True
        return "Working directory is clean.", True

    if "git pull" in text:
        result = subprocess.run(
            ["git", "pull"], capture_output=True, text=True, timeout=30,
        )
        return f"Git pull: {result.stdout.strip()[:100]}", True

    if "git push" in text:
        result = subprocess.run(
            ["git", "push"], capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return "Git push completed.", True
        return f"Git push failed: {result.stderr.strip()[:100]}", True

    return "", False
