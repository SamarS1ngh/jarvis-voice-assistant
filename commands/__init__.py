from commands.apps import handle_apps
from commands.system import handle_system
from commands.files import handle_files
from commands.terminal import handle_terminal
from commands.control import handle_control
from commands.workspaces import handle_workspaces
from commands.tabs import handle_tabs

# Each handler returns (response_text, handled) tuple.
# response_text: what Jarvis says back
# handled: True if this handler matched the command

ALL_HANDLERS = [
    handle_control,    # mouse/keyboard/scroll — fastest path, runs before the rest
    handle_workspaces, # workspace numeric/ordinal switching
    handle_tabs,       # browser tab switching + media play/pause
    handle_apps,
    handle_system,
    handle_files,
    handle_terminal,
]
