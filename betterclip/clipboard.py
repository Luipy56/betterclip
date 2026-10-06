"""Clipboard abstraction for Wayland and X11."""

from __future__ import annotations

import os
import struct
import subprocess

from .utils import (
    IMAGE_MAX_BYTES,
    IMAGE_MIMES,
    IMAGE_SUBPROCESS_TIMEOUT,
    SUBPROCESS_TIMEOUT,
    X11_CLIPBOARD_TOOLS,
    find_executable,
    find_x11_tool,
)

_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_WEBP_MAGIC = b"WEBP"

# GNOME/XWayland often exposes charset=utf-8 rather than ;utf-8.
_TEXT_MIME_CANDIDATES = (
    "text/plain;utf-8",
    "text/plain;charset=utf-8",
    "text/plain",
    "UTF8_STRING",
    "STRING",
)


def is_wayland() -> bool:
    """Detect if running under Wayland session."""
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def normalize_mime(raw: str) -> str:
    """Lowercase MIME, strip parameters, map aliases."""
    mime = raw.strip().split(";", 1)[0].strip().lower()
    return _MIME_ALIASES.get(mime, mime)


def first_image_mime(types: list[str]) -> str | None:
    """Return first supported image MIME from a type list, or None."""
    normalized = [normalize_mime(t) for t in types]
    for wanted in IMAGE_MIMES:
        if wanted in normalized:
            return wanted
    return None


def sniff_image_mime(data: bytes) -> str | None:
    """Detect PNG/JPEG/WEBP from magic bytes."""
    if not data:
        return None
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == _WEBP_MAGIC:
        return "image/webp"
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Best-effort width/height from PNG/JPEG/WEBP headers (no external deps)."""
    if not data:
        return None
    if len(data) >= 24 and data.startswith(_PNG_MAGIC) and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        if w > 0 and h > 0:
            return int(w), int(h)
    if data.startswith(_JPEG_MAGIC):
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xD8:
                i += 2
                continue
            if marker == 0xD9 or marker == 0xDA:
                break
            if i + 4 > n:
                break
            seglen = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if seglen < 2 or i + 2 + seglen > n:
                break
            # SOF0 / SOF1 / SOF2
            if marker in (0xC0, 0xC1, 0xC2) and seglen >= 7:
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                if w > 0 and h > 0:
                    return int(w), int(h)
            i += 2 + seglen
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == _WEBP_MAGIC:
        # VP8X: bytes 24..29 hold canvas width/height minus one (24-bit LE)
        if data[12:16] == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            if w > 0 and h > 0:
                return w, h
        # VP8 lossy bitstream: frame tag then 3-byte start code, then 14-bit dims
        if data[12:16] == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            if w > 0 and h > 0:
                return w, h
    return None


def _list_types_wayland() -> list[str]:
    wl = find_executable("wl-paste")
    if not wl:
        return []
    try:
        r = subprocess.run(
            [wl, "-l"],
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
            env=os.environ,
        )
        if r.returncode != 0 or not r.stdout:
            return []
        return [
            line.strip()
            for line in r.stdout.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, UnicodeDecodeError):
        return []


def _list_types_xclip() -> list[str]:
    xclip = find_executable("xclip")
    if not xclip:
        return []
    try:
        r = subprocess.run(
            [xclip, "-o", "-selection", "clipboard", "-t", "TARGETS"],
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout:
            return []
        return [
            line.strip()
            for line in r.stdout.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, UnicodeDecodeError):
        return []


def list_clipboard_types() -> list[str]:
    """
    List MIME/target types on CLIPBOARD.

    On GNOME the daemon often watches XWayland (XFixes) while the session is
    Wayland — try wl-paste first, then xclip TARGETS.
    """
    if is_wayland():
        types = _list_types_wayland()
        if types:
            return types
    return _list_types_xclip()


def _read_wayland_bytes(mime: str) -> bytes | None:
    wl = find_executable("wl-paste")
    if not wl:
        return None
    args = [wl, "-t", mime]
    if mime.startswith("text/") or mime in ("UTF8_STRING", "STRING", "TEXT"):
        args.append("--no-newline")
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            timeout=IMAGE_SUBPROCESS_TIMEOUT,
            env=os.environ,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    return None


def _read_xclip_bytes(mime: str) -> bytes | None:
    xclip = find_executable("xclip")
    if not xclip:
        return None
    try:
        r = subprocess.run(
            [xclip, "-o", "-selection", "clipboard", "-t", mime],
            capture_output=True,
            timeout=IMAGE_SUBPROCESS_TIMEOUT,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    return None


def _read_bytes(mime: str) -> bytes | None:
    """Read a MIME type; Wayland first when applicable, then xclip."""
    if is_wayland():
        data = _read_wayland_bytes(mime)
        if data:
            return data
    return _read_xclip_bytes(mime)


def read_clipboard_image() -> tuple[bytes, str] | None:
    """
    Read the first supported image from CLIPBOARD.
    Returns (bytes, mime) or None. Skips payloads over IMAGE_MAX_BYTES.
    """
    mime = first_image_mime(list_clipboard_types())
    if not mime:
        return None
    data = _read_bytes(mime)
    if not data or len(data) > IMAGE_MAX_BYTES:
        return None
    sniffed = sniff_image_mime(data)
    return (data, sniffed or mime)


def write_clipboard_image(data: bytes, mime: str) -> bool:
    """Write image bytes to CLIPBOARD with the given MIME type."""
    if not data:
        return False
    mime = normalize_mime(mime)
    if mime not in IMAGE_MIMES:
        return False

    if is_wayland():
        wl = find_executable("wl-copy")
        if wl:
            try:
                subprocess.run(
                    [wl, "-t", mime],
                    input=data,
                    check=True,
                    timeout=IMAGE_SUBPROCESS_TIMEOUT,
                    env=os.environ,
                )
                return True
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    xclip = find_executable("xclip")
    if not xclip:
        return False
    try:
        subprocess.run(
            [xclip, "-selection", "clipboard", "-t", mime, "-i"],
            input=data,
            capture_output=True,
            timeout=IMAGE_SUBPROCESS_TIMEOUT,
            check=True,
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def _read_text_x11() -> str | None:
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


def read_clipboard() -> str | None:
    """
    Read current clipboard content as UTF-8 text.
    Returns None if not text or on error.

    Tries several text MIME types on Wayland, then falls back to xsel/xclip
    (needed on GNOME where the daemon watches XWayland).
    """
    if is_wayland():
        types = list_clipboard_types()
        type_set = set(types)
        candidates = [m for m in _TEXT_MIME_CANDIDATES if not types or m in type_set]
        # If TARGETS/list was empty or X11-style without our exact names, still try defaults.
        if not candidates:
            candidates = list(_TEXT_MIME_CANDIDATES)
        for mime in candidates:
            data = _read_wayland_bytes(mime)
            if data:
                return data.decode("utf-8", errors="replace")

    text = _read_text_x11()
    if text is not None:
        return text

    # Last resort: typed xclip reads when default xsel/xclip stdout was empty.
    for mime in _TEXT_MIME_CANDIDATES:
        data = _read_xclip_bytes(mime)
        if data:
            return data.decode("utf-8", errors="replace")
    return None


def write_clipboard(text: str) -> bool:
    """Write text to clipboard. Returns True on success."""
    if not text:
        return False

    if is_wayland():
        wl = find_executable("wl-copy")
        if wl:
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
                pass

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
    """Return (executable, args) for writing clipboard text, or None."""
    if is_wayland():
        wl = find_executable("wl-copy")
        if wl:
            return (wl, [])

    tool = find_x11_tool(X11_CLIPBOARD_TOOLS)
    if not tool:
        return None
    path, _, write_args = tool
    return (path, write_args)
