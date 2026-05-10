"""Rofi-based picker for clipboard history."""

from __future__ import annotations

import subprocess
import sys

from .clipboard import get_write_tool, is_wayland
from .config import load_config
from .rofi_theme import DEFAULT_THEME, rofi_scroll_method_args, rofi_theme_args
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


def _show_cli_picker(max_lines: int = PICKER_MAX_LINES) -> str | None:
    """
    Terminal picker: print numbered history to stderr, read index from stdin.
    Returns the selected full text, or None if cancelled/invalid.
    """
    history = get_history_reversed()
    if not history:
        return None
    n = min(max_lines, len(history))
    for i in range(n):
        ent = history[i]
        preview = _truncate(ent.get("text", ""))
        sys.stderr.write(f"  {i}\t{preview}\n")
    sys.stderr.write("Index (0–{}): ".format(n - 1))
    sys.stderr.flush()
    try:
        line = sys.stdin.readline()
        idx = int(line.strip())
        if 0 <= idx < len(history):
            return history[idx].get("text", "")
    except (ValueError, EOFError):
        pass
    return None


def show_picker(max_lines: int = PICKER_MAX_LINES) -> str | None:
    """
    Show picker with clipboard history (rofi on desktop, terminal list in cli_mode).
    Returns the selected full text, or None if cancelled.
    """
    config = load_config(use_cache=False)
    if config.get("cli_mode"):
        return _show_cli_picker(max_lines)

    rofi = find_executable("rofi")
    if not rofi:
        sys.stderr.write("betterclip: rofi not found. Install rofi.\n")
        return None

    history = get_history_reversed()
    if not history:
        return None

    lines = [f"{i}\t{_truncate(ent.get('text', ''))}" for i, ent in enumerate(history)]

    theme = config.get("theme", DEFAULT_THEME)
    rofi_args = [rofi, "-dmenu", *rofi_theme_args(theme), *rofi_scroll_method_args(theme)]
    # Experimental: behave as a normal window; helps some Mutter focus edge cases.
    # modern_mac uses a heavy rounded theme; -normal-window on XWayland often causes
    # scroll/focus glitches and transient unmap — keep classic behavior for that theme.
    if is_wayland() and theme != "modern_mac":
        rofi_args.append("-normal-window")
    # GNOME Wayland + global shortcut: rofi runs on XWayland without keyboard focus
    # until you click. -steal-focus fixes that (rofi default is -no-steal-focus).
    rofi_args.extend(
        [
            "-steal-focus",
            "-p",
            "Portapapeles (Super+V)",
            "-l",
            str(min(max_lines, len(lines))),
            "-i",
        ]
    )

    try:
        proc = subprocess.Popen(
            rofi_args,
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
    config = load_config(use_cache=False)
    cli_mode = config.get("cli_mode", False)

    text = show_picker()
    if not text:
        return False

    # In CLI mode, always print selection to stdout so it can be piped (e.g. on headless servers)
    if cli_mode:
        print(text, end="")

    tool = get_write_tool()
    if not tool:
        if not cli_mode:
            sys.stderr.write("betterclip: No clipboard write tool (wl-copy/xsel/xclip).\n")
            return False
        return True  # CLI mode: selection already printed to stdout

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
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        if not cli_mode:
            return False
    return True
