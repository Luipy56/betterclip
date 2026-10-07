"""Rofi-based picker for clipboard history."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from .clipboard import get_write_tool, is_wayland, write_clipboard_image
from .config import load_config
from .rofi_theme import DEFAULT_THEME, rofi_scroll_method_args, rofi_theme_args
from .storage import get_history_reversed, resolve_image_path
from .utils import PICKER_MAX_LINES, PICKER_TRUNCATE_LEN, ROFI_TIMEOUT, find_executable

# Modifier keysyms that GNOME may still hold while handling Super+V / Ctrl+Alt+V.
_SHORTCUT_MODIFIER_KEYSYMS = (
    "Super_L",
    "Super_R",
    "Alt_L",
    "Alt_R",
    "Control_L",
    "Control_R",
)

# How often to poll _NET_ACTIVE_WINDOW while the normal-window picker is open.
_FOCUS_POLL_S = 0.05


def _rofi_env() -> dict[str, str]:
    """
    Build env for rofi.

    rofi 2.x on native Wayland requires the wlr layer-shell protocol. GNOME/Mutter
    does not provide it, so rofi aborts. Force the X11 backend (XWayland) instead.
    """
    env = os.environ.copy()
    if is_wayland():
        env.pop("WAYLAND_DISPLAY", None)
        # Keep DISPLAY so rofi talks to XWayland.
        if not env.get("DISPLAY", "").strip():
            env["DISPLAY"] = ":0"
    return env


def main_show() -> None:
    """Entry point for betterclip-show script."""
    sys.exit(0 if run_picker() else 1)


def _wait_for_shortcut_modifiers_release(timeout: float = 1.0) -> None:
    """
    Wait until Super/Ctrl/Alt are up.

    GNOME custom shortcuts keep a keyboard grab while the chord is held. If rofi
    maps during that grab (typical with Super+V), it appears on XWayland without
    keyboard focus until the user clicks it.
    """
    try:
        from Xlib import XK, display
    except ImportError:
        time.sleep(0.15)
        return

    try:
        dpy = display.Display()
    except Exception:
        time.sleep(0.15)
        return

    keycodes: set[int] = set()
    for name in _SHORTCUT_MODIFIER_KEYSYMS:
        keysym = XK.string_to_keysym(name)
        if not keysym:
            continue
        for entry in dpy.keysym_to_keycodes(keysym):
            # python-xlib yields (keycode, level) or similar tuples
            kc = entry[0] if isinstance(entry, tuple) else int(entry)
            if kc:
                keycodes.add(kc)

    if not keycodes:
        time.sleep(0.15)
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        keymap = dpy.query_keymap()
        if not any(keymap[kc // 8] & (1 << (kc % 8)) for kc in keycodes):
            return
        time.sleep(0.02)


def _x11_active_window_is_pid(dpy, root, pid: int) -> bool | None:
    """
    True if _NET_ACTIVE_WINDOW belongs to pid, False if another client, None if unknown.
    """
    try:
        from Xlib import X
    except ImportError:
        return None

    try:
        net_active = dpy.intern_atom("_NET_ACTIVE_WINDOW")
        net_wm_pid = dpy.intern_atom("_NET_WM_PID")
        prop = root.get_full_property(net_active, X.AnyPropertyType)
        if not prop or not prop.value:
            return None
        wid = int(prop.value[0])
        if wid == 0:
            return None
        win = dpy.create_resource_object("window", wid)
        pid_prop = win.get_full_property(net_wm_pid, X.AnyPropertyType)
        if pid_prop and pid_prop.value:
            return int(pid_prop.value[0]) == pid
        cls = win.get_wm_class()
        if cls and any(str(c).lower() == "rofi" for c in cls):
            # No PID atom; treat any rofi window as ours while the picker runs.
            return True
    except Exception:
        return None
    return False


def _terminate_rofi_on_focus_loss(proc: subprocess.Popen) -> None:
    """
    Cancel the picker when a -normal-window rofi loses focus (click outside, Alt-Tab).

    Overlay-style rofi uses -click-to-exit; GNOME/XWayland needs -normal-window for
    keyboard focus, and that mode does not dismiss on outside click by itself.
    """
    try:
        from Xlib import display
    except ImportError:
        return

    try:
        dpy = display.Display()
    except Exception:
        return

    root = dpy.screen().root
    saw_focus = False
    while proc.poll() is None:
        state = _x11_active_window_is_pid(dpy, root, proc.pid)
        if state is True:
            saw_focus = True
        elif saw_focus and state is False:
            try:
                proc.terminate()
            except OSError:
                pass
            return
        time.sleep(_FOCUS_POLL_S)


def _truncate(text: str, max_len: int = PICKER_TRUNCATE_LEN) -> str:
    """Truncate and escape for rofi display."""
    text = text.replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _format_stamp(ts: str | None) -> str:
    """Local [dd/HH:mm] from an ISO timestamp (history stores UTC)."""
    if not ts or not str(ts).strip():
        return "--/--:--"
    raw = str(ts).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return "--/--:--"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return local.strftime("%d/%H:%M")


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _image_dims(entry: dict) -> tuple[int, int] | None:
    w, h = entry.get("width"), entry.get("height")
    try:
        if w and h:
            return int(w), int(h)
    except (TypeError, ValueError):
        pass
    rel = entry.get("path")
    if not isinstance(rel, str) or not rel:
        return None
    path = resolve_image_path(rel)
    if not path.is_file():
        return None
    try:
        from .clipboard import image_dimensions

        return image_dimensions(path.read_bytes())
    except OSError:
        return None


def _image_byte_count(entry: dict) -> int | None:
    raw = entry.get("bytes")
    try:
        if raw is not None:
            n = int(raw)
            if n >= 0:
                return n
    except (TypeError, ValueError):
        pass
    rel = entry.get("path")
    if isinstance(rel, str) and rel:
        try:
            return resolve_image_path(rel).stat().st_size
        except OSError:
            return None
    return None


def _image_label(entry: dict) -> str:
    mime = str(entry.get("mime") or "image/png")
    subtype = mime.split("/", 1)[-1].upper()
    if subtype == "JPEG":
        subtype = "JPG"
    parts = ["Imagen", subtype]
    dims = _image_dims(entry)
    if dims:
        parts.append(f"{dims[0]}×{dims[1]}")
    nbytes = _image_byte_count(entry)
    if nbytes is not None:
        parts.append(_format_bytes(nbytes))
    return " · ".join(parts)


def _picker_preview(entry: dict) -> str:
    if entry.get("kind") == "image":
        return _image_label(entry)
    return _truncate(entry.get("text", ""))


def _picker_line(index: int, entry: dict, *, with_icon: bool = False) -> str:
    line = f"{index}\t[{_format_stamp(entry.get('timestamp'))}] {_picker_preview(entry)}"
    if with_icon and entry.get("kind") == "image":
        rel = entry.get("path")
        if isinstance(rel, str) and rel:
            abs_path = resolve_image_path(rel)
            if abs_path.is_file():
                return f"{line}\0icon\x1f{abs_path}"
    return line


def _show_cli_picker(max_lines: int = PICKER_MAX_LINES) -> dict | None:
    """
    Terminal picker: print numbered history to stderr, read index from stdin.
    Returns the selected entry, or None if cancelled/invalid.
    """
    history = get_history_reversed()
    if not history:
        return None
    n = min(max_lines, len(history))
    for i in range(n):
        sys.stderr.write(f"  {_picker_line(i, history[i])}\n")
    sys.stderr.write("Index (0–{}): ".format(n - 1))
    sys.stderr.flush()
    try:
        line = sys.stdin.readline()
        idx = int(line.strip())
        if 0 <= idx < len(history):
            return history[idx]
    except (ValueError, EOFError):
        pass
    return None


def _parse_picker_index(selected: str, history: list[dict]) -> dict | None:
    selected = selected.strip()
    if not selected:
        return None
    idx_str = selected.split("\t", 1)[0] if "\t" in selected else selected
    try:
        idx = int(idx_str)
        if 0 <= idx < len(history):
            return history[idx]
    except ValueError:
        pass
    return None


def show_picker(max_lines: int = PICKER_MAX_LINES) -> dict | None:
    """
    Show picker with clipboard history (rofi on desktop, terminal list in cli_mode).
    Returns the selected history entry, or None if cancelled.
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

    has_image = any(ent.get("kind") == "image" for ent in history)
    lines = [_picker_line(i, ent, with_icon=has_image) for i, ent in enumerate(history)]

    theme = config.get("theme", DEFAULT_THEME)
    rofi_args = [rofi, "-dmenu", *rofi_theme_args(theme), *rofi_scroll_method_args(theme)]
    # GNOME Wayland: _rofi_env() forces XWayland (rofi 2.x needs layer-shell).
    # Both -normal-window and -steal-focus are required so keyboard focus works
    # without an extra click after Super+V (including modern_mac).
    use_normal_window = is_wayland()
    if use_normal_window:
        rofi_args.append("-normal-window")
    rofi_args.extend(
        [
            "-steal-focus",
            # Outside click cancels like Escape (X11 overlay; also set for clarity).
            "-click-to-exit",
            "-p",
            "Portapapeles (Super+V)",
            "-l",
            str(min(max_lines, len(lines))),
            "-i",
        ]
    )
    if has_image:
        rofi_args.append("-show-icons")

    # Release Super/Ctrl/Alt before mapping rofi (shortcut grab otherwise steals focus).
    _wait_for_shortcut_modifiers_release()

    fed = "\n".join(lines).encode("utf-8")
    try:
        proc = subprocess.Popen(
            rofi_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_rofi_env(),
        )
        if use_normal_window:
            threading.Thread(
                target=_terminate_rofi_on_focus_loss,
                args=(proc,),
                daemon=True,
            ).start()
        out, _ = proc.communicate(input=fed, timeout=ROFI_TIMEOUT)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None

    selected = ""
    if out:
        selected = out.decode("utf-8", errors="replace") if isinstance(out, (bytes, bytearray)) else str(out)
    return _parse_picker_index(selected, history)


def run_picker() -> bool:
    """Show picker and write the selection to the clipboard. Returns True if user selected."""
    from .storage import mark_self_write

    config = load_config(use_cache=False)
    cli_mode = config.get("cli_mode", False)

    entry = show_picker()
    if not entry:
        return False

    if entry.get("kind") == "image":
        rel = entry.get("path")
        mime = str(entry.get("mime") or "image/png")
        path = resolve_image_path(rel) if isinstance(rel, str) and rel else None
        if cli_mode and path is not None:
            print(str(path), end="")
        if path is None or not path.is_file():
            return bool(cli_mode)
        try:
            data = path.read_bytes()
        except OSError:
            return bool(cli_mode)
        # Daemon must not treat this re-selection as a new copy.
        mark_self_write("image", data)
        ok = write_clipboard_image(data, mime)
        return True if cli_mode else ok

    text = entry.get("text", "")
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

    # Fingerprint matches daemon stripping; ignore the ensuing CLIPBOARD event.
    mark_self_write("text", text.strip().encode("utf-8"))

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
