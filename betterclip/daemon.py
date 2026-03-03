"""Daemon: monitor clipboard (Wayland/X11) and append to history."""

from __future__ import annotations

import os
import signal
import struct
import subprocess
import sys
import threading

from .utils import SUBPROCESS_TIMEOUT, X11_CLIPBOARD_TOOLS, find_executable, find_x11_tool


def _on_new_clipboard_text(text: str) -> None:
    from .storage import add_entry

    text = text.strip()
    if text:
        add_entry(text)


def _wayland_run_watcher(primary: bool) -> subprocess.Popen | None:
    """Run wl-paste --watch with a wrapper that sends length-prefixed data over a pipe."""
    wl = find_executable("wl-paste")
    if not wl:
        return None

    rfd, wfd = os.pipe()
    wrapper = (
        "import sys,os,struct;"
        "d=sys.stdin.buffer.read();"
        "os.write(3,struct.pack('>I',len(d))+d);"
        "sys.exit(0)"
    )
    args = [wl, "--watch", "--type", "text/plain;utf-8", "--no-newline"]
    if primary:
        args.append("--primary")
    args.extend([sys.executable, "-c", wrapper])

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(wfd,),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    os.close(wfd)

    def reader():
        buf = b""
        while True:
            try:
                chunk = os.read(rfd, 65536)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 4:
                    sz = struct.unpack(">I", buf[:4])[0]
                    if len(buf) < 4 + sz:
                        break
                    payload = buf[4 : 4 + sz]
                    buf = buf[4 + sz :]
                    try:
                        text = payload.decode("utf-8", errors="replace")
                        _on_new_clipboard_text(text)
                    except Exception:
                        pass
            except OSError:
                break
        try:
            os.close(rfd)
        except OSError:
            pass

    threading.Thread(target=reader, daemon=True).start()
    return proc


def _x11_run_watcher() -> None:
    """Run X11 clipboard monitor using python-xlib XFixes."""
    try:
        from Xlib import display
        from Xlib.ext import xfixes
    except ImportError:
        sys.stderr.write("betterclip: python-xlib not found. Install python3-xlib.\n")
        sys.exit(1)

    disp = display.Display()
    try:
        disp.xfixes_query_version()
    except Exception:
        sys.stderr.write("betterclip: XFixes extension not available.\n")
        sys.exit(1)

    # Only monitor CLIPBOARD (Ctrl+C, right-click Copy). Skip PRIMARY (mouse selection)
    # to avoid partial/incremental text as user drags to select.
    clip_tool = find_x11_tool(X11_CLIPBOARD_TOOLS)
    if not clip_tool:
        sys.stderr.write("betterclip: xsel/xclip not found. Install xsel.\n")
        sys.exit(1)

    root = disp.screen().root
    atom_clipboard = disp.get_atom("CLIPBOARD")
    mask = xfixes.XFixesSetSelectionOwnerNotifyMask

    disp.xfixes_select_selection_input(root, atom_clipboard, mask)

    # query_extension works on both dist-packages and pypi python-xlib
    ext_reply = disp.query_extension("XFIXES")
    sel_notify_type = ext_reply.first_event + xfixes.XFixesSelectionNotify

    def read_clipboard() -> str | None:
        path, read_args, _ = clip_tool
        try:
            r = subprocess.run(
                [path] + read_args,
                capture_output=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", errors="replace")
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    while True:
        try:
            ev = disp.next_event()
        except Exception:
            break
        if ev.type != sel_notify_type or ev.selection != atom_clipboard:
            continue
        text = read_clipboard()
        if text:
            _on_new_clipboard_text(text)


def run_daemon() -> None:
    from .clipboard import is_wayland

    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    except ValueError:
        pass  # Signals only work in main thread

    if is_wayland():
        # Only watch CLIPBOARD (Ctrl+C, right-click Copy), not PRIMARY (mouse selection)
        p = _wayland_run_watcher(primary=False)
        if p is None:
            sys.stderr.write("betterclip: wl-paste not found. Install wl-clipboard.\n")
            sys.exit(1)
        p.wait()
    else:
        _x11_run_watcher()
