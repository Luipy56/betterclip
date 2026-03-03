"""Rofi-based picker for clipboard history."""

from __future__ import annotations

import subprocess
import sys

from .clipboard import get_write_tool
from .storage import get_history_reversed
from .utils import PICKER_MAX_LINES, PICKER_TRUNCATE_LEN, ROFI_TIMEOUT, find_executable


def main_show() -> None:
    """Entry point for betterclip-show script."""
    sys.exit(0 if run_picker() else 1)


def _truncate(text: str, max_len: int = PICKER_TRUNCATE_LEN) -> str:
    """Truncate and escape for rofi display."""
    text = text.replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def show_picker(max_lines: int = PICKER_MAX_LINES) -> str | None:
    """
    Show rofi picker with clipboard history.
    Returns the selected full text, or None if cancelled.
    """
    rofi = find_executable("rofi")
    if not rofi:
        sys.stderr.write("betterclip: rofi not found. Install rofi.\n")
        return None

    history = get_history_reversed()
    if not history:
        return None

    lines = [f"{i}\t{_truncate(ent.get('text', ''))}" for i, ent in enumerate(history)]

    try:
        proc = subprocess.Popen(
            [
                rofi,
                "-dmenu",
                "-p", "Portapapeles (Super+V)",
                "-l", str(min(max_lines, len(lines))),
                "-i",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        out, _ = proc.communicate(input="\n".join(lines), timeout=ROFI_TIMEOUT)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None

    selected = out.strip() if out else ""
    if not selected:
        return None

    idx_str = selected.split("\t", 1)[0] if "\t" in selected else selected
    try:
        idx = int(idx_str)
        if 0 <= idx < len(history):
            return history[idx].get("text", "")
    except ValueError:
        pass

    return None


def run_picker() -> bool:
    """Show picker and write selected text to clipboard. Returns True if user selected."""
    text = show_picker()
    if not text:
        return False

    tool = get_write_tool()
    if not tool:
        sys.stderr.write("betterclip: No clipboard write tool (wl-copy/xsel/xclip).\n")
        return False

    exe, args = tool
    try:
        subprocess.run(
            [exe] + args,
            input=text,
            capture_output=True,
            timeout=2,
            check=True,
            text=True,
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False
