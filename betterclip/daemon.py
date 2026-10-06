"""Daemon: monitor clipboard (Wayland/X11) and append to history."""

from __future__ import annotations

import os
import signal
import struct
import subprocess
import sys
import threading
import time

from .utils import X11_CLIPBOARD_TOOLS, find_executable, find_x11_tool


def _on_clipboard_payload(kind: str, mime: str, data: bytes) -> None:
    from .storage import add_entry, add_image_entry

    if kind == "image":
        add_image_entry(data, mime)
        return
    text = data.decode("utf-8", errors="replace").strip()
    if text:
        add_entry(text)


def _on_new_clipboard() -> None:
    """Probe CLIPBOARD: store an image if present, otherwise text."""
    from .clipboard import read_clipboard, read_clipboard_image

    img = read_clipboard_image()
    if img:
        _on_clipboard_payload("image", img[1], img[0])
        return
    text = read_clipboard()
    if text:
        _on_clipboard_payload("text", "text/plain", text.encode("utf-8"))


def _on_new_clipboard_text(text: str) -> None:
    _on_clipboard_payload("text", "text/plain", text.encode("utf-8"))


def wayland_watch_tick() -> None:
    """
    Body of `wl-paste --watch`. Consume stdin (avoids pipe deadlock), then
    send a tagged image-or-text frame on BETTERCLIP_WATCH_FD.
    """
    fd = int(os.environ.get("BETTERCLIP_WATCH_FD", "3"))
    stdin_data = sys.stdin.buffer.read()
    from .clipboard import first_image_mime, list_clipboard_types, read_clipboard_image, sniff_image_mime
    from .utils import IMAGE_MAX_BYTES

    types = list_clipboard_types()
    mime = first_image_mime(types)
    if mime:
        sniffed = sniff_image_mime(stdin_data)
        if sniffed and len(stdin_data) <= IMAGE_MAX_BYTES:
            _write_watch_frame(fd, 1, sniffed, stdin_data)
            return
        img = read_clipboard_image()
        if img:
            _write_watch_frame(fd, 1, img[1], img[0])
        return
    if stdin_data:
        _write_watch_frame(fd, 0, "text/plain", stdin_data)


def _write_watch_frame(fd: int, kind: int, mime: str, data: bytes) -> None:
    mime_b = mime.encode("utf-8")
    inner = bytes([kind]) + struct.pack(">H", len(mime_b)) + mime_b + data
    os.write(fd, struct.pack(">I", len(inner)) + inner)


def _wayland_wlroots_watch_supported(wl: str) -> bool:
    """
    wl-paste --watch needs the wlr data-control protocol.
    GNOME/Mutter does not support it; use X11/XWayland or slow polling instead.
    """
    try:
        p = subprocess.Popen(
            [wl, "--watch", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            p.wait(timeout=0.6)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            return True
        return False
    except OSError:
        return False


def _wayland_poll_forever() -> None:
    """
    Last-resort: poll wl-paste. Avoid on GNOME — each run can flash an icon in the dock.
    Prefer X11/XWayland when DISPLAY is set (see run_daemon).
    """
    sys.stderr.write(
        "betterclip: wl-paste polling (slow interval to limit dock noise). "
        "Prefer setting DISPLAY for XWayland + XFixes.\n"
    )
    sys.stderr.flush()
    while True:
        time.sleep(2.0)
        _on_new_clipboard()


def _wayland_run_watcher(primary: bool) -> subprocess.Popen | None:
    """Run wl-paste --watch with a wrapper that sends length-prefixed data over a pipe."""
    wl = find_executable("wl-paste")
    if not wl:
        return None

    rfd, wfd = os.pipe()
    wrapper = "from betterclip.daemon import wayland_watch_tick; wayland_watch_tick()"
    args = [wl, "--watch"]
    if primary:
        args.append("--primary")
    args.extend([sys.executable, "-c", wrapper])

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(wfd,),
        env={
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "BETTERCLIP_WATCH_FD": str(wfd),
        },
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
                        if len(payload) < 3:
                            continue
                        kind = payload[0]
                        mime_len = struct.unpack(">H", payload[1:3])[0]
                        if len(payload) < 3 + mime_len:
                            continue
                        mime = payload[3 : 3 + mime_len].decode("utf-8", errors="replace")
                        data = payload[3 + mime_len :]
                        _on_clipboard_payload(
                            "image" if kind == 1 else "text",
                            mime,
                            data,
                        )
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

    while True:
        try:
            ev = disp.next_event()
        except Exception as exc:
            # Silent return was treated as success by systemd (Restart=on-failure).
            sys.stderr.write(f"betterclip: X11 event loop ended ({exc!r}).\n")
            sys.stderr.flush()
            sys.exit(1)
        if ev.type != sel_notify_type or ev.selection != atom_clipboard:
            continue
        _on_new_clipboard()


_SESSION_ENV_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
)


def _parse_systemctl_environment(stdout: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value.strip()
    return env


def import_user_manager_environment(stdout: str | None = None) -> None:
    """Copy graphical session vars from the user manager into this process."""
    if stdout is None:
        try:
            out = subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            stdout = out.stdout
        except (OSError, subprocess.SubprocessError):
            return
    env_map = _parse_systemctl_environment(stdout)
    for key in _SESSION_ENV_KEYS:
        value = env_map.get(key, "").strip()
        if value:
            os.environ[key] = value


def _wait_for_display(timeout_s: float = 60.0, interval_s: float = 1.0) -> str | None:
    """Wait until DISPLAY is set (systemd user units often start before the GUI)."""
    deadline = time.monotonic() + timeout_s
    while True:
        import_user_manager_environment()
        display = os.environ.get("DISPLAY", "").strip()
        if display:
            return display
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval_s)


def _monitor_via_x11_or_poll() -> None:
    """GNOME/Mutter path: XFixes on XWayland, or slow wl-paste polling."""
    if os.environ.get("DISPLAY", "").strip():
        sys.stderr.write(
            "betterclip: Wayland without wl-paste --watch; using XFixes on XWayland.\n"
        )
        sys.stderr.flush()
        try:
            _x11_run_watcher()
        except SystemExit:
            raise
        except BaseException as exc:
            sys.stderr.write(
                f"betterclip: X11 monitor failed ({exc!r}); falling back to wl-paste polling.\n"
            )
            sys.stderr.flush()
            _wayland_poll_forever()
    else:
        sys.stderr.write(
            "betterclip: no DISPLAY (XWayland unavailable). "
            "Add PassEnvironment=DISPLAY to the systemd user unit.\n"
        )
        sys.stderr.flush()
        _wayland_poll_forever()


def run_daemon() -> None:
    from .clipboard import is_wayland

    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    except ValueError:
        pass  # Signals only work in main thread

    # User units WantedBy=default.target can race the graphical session.
    _wait_for_display()

    if is_wayland():
        wl = find_executable("wl-paste")
        if not wl:
            sys.stderr.write("betterclip: wl-paste not found. Install wl-clipboard.\n")
            sys.exit(1)
        # Only watch CLIPBOARD (Ctrl+C, right-click Copy), not PRIMARY (mouse selection)
        if _wayland_wlroots_watch_supported(wl):
            p = _wayland_run_watcher(primary=False)
            if p is None:
                sys.stderr.write("betterclip: wl-paste not found. Install wl-clipboard.\n")
                sys.exit(1)
            p.wait()
            # Login race: compositor is not ready, --watch looks alive for ~0.6s, then dies.
            # Do not treat that as a clean shutdown (systemd Restart=on-failure would skip it).
            sys.stderr.write(
                "betterclip: wl-paste --watch exited; falling back to X11/XWayland.\n"
            )
            sys.stderr.flush()
        _monitor_via_x11_or_poll()
    else:
        if not os.environ.get("DISPLAY", "").strip():
            sys.stderr.write("betterclip: DISPLAY is empty; cannot attach to X11.\n")
            sys.exit(1)
        _x11_run_watcher()
