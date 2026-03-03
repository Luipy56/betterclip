"""Clipboard abstraction for Wayland and X11."""

from __future__ import annotations

import os
import subprocess

from .utils import (
    SUBPROCESS_TIMEOUT,
    X11_CLIPBOARD_TOOLS,
    find_executable,
    find_x11_tool,
)


def is_wayland() -> bool:
    """Detect if running under Wayland session."""
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def read_clipboard() -> str | None:
    """
    Read current clipboard content as UTF-8 text.
    Returns None if not text or on error.
    """
    if is_wayland():
        wl = find_executable("wl-paste")
        if not wl:
            return None
        try:
            r = subprocess.run(
                [wl, "-t", "text/plain;utf-8", "--no-newline"],
                capture_output=True,
                timeout=SUBPROCESS_TIMEOUT,
                env=os.environ,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", errors="replace")
            return None
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, UnicodeDecodeError):
            return None

    tool = find_x11_tool(X11_CLIPBOARD_TOOLS)
    if not tool:
        return None
    path, read_args, _ = tool
    try:
        r = subprocess.run(
            [path] + read_args,
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, UnicodeDecodeError):
        pass
    return None


def write_clipboard(text: str) -> bool:
    """Write text to clipboard. Returns True on success."""
    if not text:
        return False

    if is_wayland():
        wl = find_executable("wl-copy")
        if not wl:
            return False
        try:
            subprocess.run(
                [wl],
                input=text.encode("utf-8"),
                check=True,
                timeout=SUBPROCESS_TIMEOUT,
                env=os.environ,
            )
            return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return False

    tool = find_x11_tool(X11_CLIPBOARD_TOOLS)
    if not tool:
        return False
    path, _, write_args = tool
    try:
        subprocess.run(
            [path] + write_args,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
            check=True,
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def get_write_tool() -> tuple[str, list[str]] | None:
    """Return (executable, args) for writing clipboard, or None."""
    if is_wayland():
        wl = find_executable("wl-copy")
        return (wl, []) if wl else None

    tool = find_x11_tool(X11_CLIPBOARD_TOOLS)
    if not tool:
        return None
    path, _, write_args = tool
    return (path, write_args)