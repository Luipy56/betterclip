"""Shared utilities for betterclip."""

from __future__ import annotations

import shutil
# Subprocess timeouts (seconds)
SUBPROCESS_TIMEOUT = 2
ROFI_TIMEOUT = 30

# Picker display
PICKER_MAX_LINES = 15
PICKER_TRUNCATE_LEN = 120

# Clipboard tool config: (cmd, read_args, write_args)
X11_CLIPBOARD_TOOLS = [
    ("xsel", ["-o", "-b"], ["-i", "-b"]),
    ("xclip", ["-o", "-selection", "clipboard"], ["-i", "-selection", "clipboard"]),
]
X11_PRIMARY_TOOLS = [
    ("xsel", ["-o", "-p"], ["-i", "-p"]),
    ("xclip", ["-o", "-selection", "primary"], ["-i", "-selection", "primary"]),
]


def find_executable(name: str) -> str | None:
    """Return path to executable, or None."""
    return shutil.which(name)


def find_x11_tool(tools_list: list) -> tuple[str, list[str], list[str]] | None:
    """Return (path, read_args, write_args) for first available tool."""
    for cmd, read_args, write_args in tools_list:
        path = find_executable(cmd)
        if path:
            return (path, read_args, write_args)
    return None
