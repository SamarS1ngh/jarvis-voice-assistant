import subprocess
import os
import re


HOME = os.path.expanduser("~")

LOCATION_MAP = {
    "desktop": os.path.join(HOME, "Desktop"),
    "downloads": os.path.join(HOME, "Downloads"),
    "documents": os.path.join(HOME, "Documents"),
    "pictures": os.path.join(HOME, "Pictures"),
    "music": os.path.join(HOME, "Music"),
    "videos": os.path.join(HOME, "Videos"),
    "home": HOME,
}


def _resolve_location(text: str) -> str:
    """Extract a location from the command text."""
    for name, path in LOCATION_MAP.items():
        if name in text:
            return path
    return HOME


def handle_files(text: str) -> tuple[str, bool]:
    # Create folder
    match = re.search(r"create\s+(?:a\s+)?folder\s+(?:called\s+|named\s+)?(\w+)", text)
    if match:
        folder_name = match.group(1)
        location = _resolve_location(text)
        path = os.path.join(location, folder_name)
        os.makedirs(path, exist_ok=True)
        return f"Created folder {folder_name} in {os.path.basename(location)}.", True

    # Create file
    match = re.search(r"create\s+(?:a\s+)?file\s+(?:called\s+|named\s+)?(\S+)", text)
    if match:
        file_name = match.group(1)
        location = _resolve_location(text)
        path = os.path.join(location, file_name)
        with open(path, "w") as f:
            f.write("")
        return f"Created file {file_name} in {os.path.basename(location)}.", True

    # Delete file or folder
    match = re.search(r"delete\s+(?:the\s+)?(?:file|folder)\s+(?:called\s+|named\s+)?(\S+)", text)
    if match:
        name = match.group(1)
        location = _resolve_location(text)
        path = os.path.join(location, name)
        if os.path.isdir(path):
            os.rmdir(path)
            return f"Deleted folder {name}.", True
        elif os.path.isfile(path):
            os.remove(path)
            return f"Deleted file {name}.", True
        else:
            return f"Could not find {name}.", True

    # Move file
    match = re.search(r"move\s+(\S+)\s+to\s+(\w+)", text)
    if match:
        name = match.group(1)
        dest_key = match.group(2).lower()
        dest = LOCATION_MAP.get(dest_key, os.path.join(HOME, dest_key))
        # Search for the file in common locations
        for loc in LOCATION_MAP.values():
            src = os.path.join(loc, name)
            if os.path.exists(src):
                os.rename(src, os.path.join(dest, name))
                return f"Moved {name} to {dest_key}.", True
        return f"Could not find {name}.", True

    # Search for files — REQUIRE the word "file" or "folder" to fire.
    # Without this, "search for simran in telegram" falsely matches.
    if re.search(r"\b(?:file|folder)s?\b", text) and re.search(r"\b(?:find|search|locate)\b", text):
        match = re.search(
            r"\b(?:find|search|locate)\s+(?:for\s+)?(?:a\s+|the\s+)?(?:file|folder)s?\s+(?:called\s+|named\s+)?(\S+)",
            text,
        )
        if match and "web" not in text and "google" not in text:
            name = match.group(1)
            result = subprocess.run(
                ["find", HOME, "-maxdepth", "4", "-iname", f"*{name}*", "-type", "f"],
                capture_output=True, text=True, timeout=5,
            )
            files = result.stdout.strip().split("\n")[:5]
            files = [f for f in files if f]
            if files:
                count = len(files)
                return f"Found {count} files matching {name}.", True
            return f"No files found matching {name}.", True

    # Open file manager at location
    if re.search(r"open\s+(?:the\s+)?(?:file\s+manager|files|folder)", text):
        location = _resolve_location(text)
        subprocess.Popen(
            ["nautilus", location],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Opening file manager at {os.path.basename(location)}.", True

    return "", False
