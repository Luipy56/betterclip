"""Tests for betterclip - run with pytest or python -m pytest."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestConfig(unittest.TestCase):
    """Test config module."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("betterclip.config.Path.home", return_value=Path(self.tmp))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_config_defaults(self):
        from betterclip.config import load_config

        cfg = load_config()
        self.assertEqual(cfg["max_items"], 50)
        self.assertEqual(cfg["hotkey"], "Super+V")
        self.assertFalse(cfg["cli_mode"])
        self.assertEqual(cfg["theme"], "modern_mac")

    def test_load_config_from_file(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"max_items": 25}', encoding="utf-8")
        cfg = load_config()
        self.assertEqual(cfg["max_items"], 25)
        self.assertEqual(cfg["hotkey"], "Super+V")

    def test_load_config_validates_max_items(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"max_items": -5}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertEqual(cfg["max_items"], 50)
        path.write_text('{"max_items": 9999}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertEqual(cfg["max_items"], 1000)

    def test_load_config_uses_cache(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"max_items": 10}', encoding="utf-8")
        cfg1 = load_config(use_cache=True)
        cfg2 = load_config(use_cache=True)
        self.assertEqual(cfg1["max_items"], 10)
        self.assertEqual(cfg2["max_items"], 10)

    def test_load_config_unknown_theme_defaults_to_modern_mac(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"theme": "does_not_exist"}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertEqual(cfg["theme"], "modern_mac")

    def test_load_config_theme_modern_mac_normalized(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"theme": "modern-mac"}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertEqual(cfg["theme"], "modern_mac")

    def test_load_config_cli_mode(self):
        from betterclip.config import get_config_path, load_config

        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cli_mode": true}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertTrue(cfg["cli_mode"])
        path.write_text('{"cli_mode": "true"}', encoding="utf-8")
        cfg = load_config(use_cache=False)
        self.assertTrue(cfg["cli_mode"])


class TestStorage(unittest.TestCase):
    """Test storage module."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("betterclip.config.Path.home", return_value=Path(self.tmp))
        self.patcher.start()
        self.config_patcher = patch("betterclip.storage.load_config", return_value={"max_items": 50})
        self.config_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.config_patcher.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_entry(self):
        from betterclip.storage import add_entry, load_history

        add_entry("hello")
        hist = load_history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["text"], "hello")
        self.assertIn("timestamp", hist[0])

    def test_add_image_entry(self):
        import hashlib
        import struct

        from betterclip.storage import add_image_entry, load_history, resolve_image_path

        data = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">IIBBBBB", 1920, 1080, 8, 2, 0, 0, 0)
            + b"\x00\x00\x00\x00"
        )
        add_image_entry(data, "image/png")
        hist = load_history()
        self.assertEqual(len(hist), 1)
        entry = hist[0]
        self.assertEqual(entry["kind"], "image")
        self.assertEqual(entry["mime"], "image/png")
        self.assertEqual(entry["width"], 1920)
        self.assertEqual(entry["height"], 1080)
        self.assertEqual(entry["bytes"], len(data))
        sha = hashlib.sha256(data).hexdigest()
        self.assertEqual(entry["sha256"], sha)
        self.assertEqual(entry["path"], f"images/{sha}.png")
        path = resolve_image_path(entry["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), data)

    def test_add_image_entry_dedup_consecutive(self):
        from betterclip.storage import add_image_entry, load_history

        data = b"\x89PNG\r\n\x1a\n" + b"same"
        add_image_entry(data, "image/png")
        add_image_entry(data, "image/png")
        self.assertEqual(len(load_history()), 1)

    def test_image_eviction_deletes_blob(self):
        from betterclip.storage import add_entry, add_image_entry, load_history, resolve_image_path

        self.config_patcher.stop()
        self.config_patcher = patch("betterclip.storage.load_config", return_value={"max_items": 2})
        self.config_patcher.start()

        data = b"\x89PNG\r\n\x1a\n" + b"drop-me"
        add_image_entry(data, "image/png")
        rel = load_history()[0]["path"]
        blob = resolve_image_path(rel)
        self.assertTrue(blob.is_file())
        add_entry("a")
        add_entry("b")
        hist = load_history()
        self.assertEqual(len(hist), 2)
        self.assertEqual([e.get("text") for e in hist], ["a", "b"])
        self.assertFalse(blob.exists())

    def test_add_image_entry_skips_oversized(self):
        from betterclip.storage import add_image_entry, load_history
        from betterclip.utils import IMAGE_MAX_BYTES

        add_image_entry(b"x" * (IMAGE_MAX_BYTES + 1), "image/png")
        self.assertEqual(load_history(), [])

    def test_add_entry_dedup_consecutive(self):
        from betterclip.storage import add_entry, load_history

        add_entry("same")
        add_entry("same")
        hist = load_history()
        self.assertEqual(len(hist), 1)

    def test_add_entry_max_items(self):
        from betterclip.storage import add_entry, load_history

        for i in range(55):
            add_entry(f"item {i}")
        hist = load_history()
        self.assertEqual(len(hist), 50)
        self.assertEqual(hist[0]["text"], "item 5")
        self.assertEqual(hist[-1]["text"], "item 54")

    def test_get_history_reversed(self):
        from betterclip.storage import add_entry, get_history_reversed

        add_entry("first")
        add_entry("second")
        rev = get_history_reversed()
        self.assertEqual(rev[0]["text"], "second")
        self.assertEqual(rev[1]["text"], "first")

    def test_add_entry_skip_empty(self):
        from betterclip.storage import add_entry, load_history

        add_entry("")
        add_entry("   ")
        hist = load_history()
        self.assertEqual(len(hist), 0)

    def test_self_write_ignore_matches_once(self):
        from betterclip.storage import mark_self_write, take_self_write_ignore

        payload = b"selected line"
        mark_self_write("text", payload)
        self.assertTrue(take_self_write_ignore("text", payload))
        # Consumed: a second identical capture must not be ignored.
        self.assertFalse(take_self_write_ignore("text", payload))

    def test_self_write_ignore_leaves_marker_on_mismatch(self):
        from betterclip.storage import mark_self_write, take_self_write_ignore

        mark_self_write("text", b"from-picker")
        self.assertFalse(take_self_write_ignore("text", b"other-event"))
        self.assertTrue(take_self_write_ignore("text", b"from-picker"))

    def test_self_write_ignore_expires(self):
        import json

        from betterclip import storage as storage_mod
        from betterclip.storage import mark_self_write, take_self_write_ignore

        mark_self_write("text", b"stale")
        path = storage_mod._self_write_path()
        marker = json.loads(path.read_text(encoding="utf-8"))
        marker["ts"] = marker["ts"] - storage_mod._SELF_WRITE_TTL_S - 1
        path.write_text(json.dumps(marker), encoding="utf-8")
        self.assertFalse(take_self_write_ignore("text", b"stale"))


class TestUtils(unittest.TestCase):
    """Test utils module."""

    def test_find_x11_tool_returns_none_when_missing(self):
        from betterclip.utils import X11_CLIPBOARD_TOOLS, find_x11_tool

        with patch("betterclip.utils.find_executable", return_value=None):
            self.assertIsNone(find_x11_tool(X11_CLIPBOARD_TOOLS))

    def test_find_x11_tool_returns_tool_when_found(self):
        from betterclip.utils import X11_CLIPBOARD_TOOLS, find_x11_tool

        with patch("betterclip.utils.find_executable") as mock:
            mock.return_value = "/usr/bin/xsel"
            result = find_x11_tool(X11_CLIPBOARD_TOOLS)
            self.assertIsNotNone(result)
            path, read_args, write_args = result
            self.assertEqual(path, "/usr/bin/xsel")
            self.assertEqual(read_args, ["-o", "-b"])


class TestClipboard(unittest.TestCase):
    """Test clipboard module (session detection only, no real clipboard)."""

    def test_is_wayland_detects_wayland(self):
        from betterclip.clipboard import is_wayland

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}):
            self.assertTrue(is_wayland())
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}):
            self.assertTrue(is_wayland())

    def test_is_wayland_detects_x11(self):
        from betterclip.clipboard import is_wayland

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}, clear=False):
            # Need to pop WAYLAND_DISPLAY to avoid override
            env = os.environ.copy()
            env.pop("WAYLAND_DISPLAY", None)
            env["XDG_SESSION_TYPE"] = "x11"
            with patch.dict(os.environ, env):
                self.assertFalse(is_wayland())

    def test_first_image_mime_and_sniff(self):
        import struct

        from betterclip.clipboard import first_image_mime, image_dimensions, sniff_image_mime

        self.assertEqual(
            first_image_mime(["TIMESTAMP", "text/plain", "image/png"]),
            "image/png",
        )
        self.assertEqual(first_image_mime(["image/jpg"]), "image/jpeg")
        self.assertIsNone(first_image_mime(["text/plain"]))
        png = b"\x89PNG\r\n\x1a\n"
        self.assertEqual(sniff_image_mime(png), "image/png")
        self.assertEqual(sniff_image_mime(b"\xff\xd8\xff\xe0"), "image/jpeg")
        webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"xxxx"
        self.assertEqual(sniff_image_mime(webp), "image/webp")
        self.assertIsNone(sniff_image_mime(b"hello"))
        png_ihdr = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">IIBBBBB", 800, 600, 8, 2, 0, 0, 0)
        )
        self.assertEqual(image_dimensions(png_ihdr), (800, 600))
        self.assertIsNone(image_dimensions(b"hello"))

    def test_list_clipboard_types_wayland(self):
        from unittest.mock import MagicMock

        from betterclip.clipboard import list_clipboard_types

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b"text/plain\nimage/png\n"
        with patch("betterclip.clipboard.is_wayland", return_value=True):
            with patch("betterclip.clipboard.find_executable", return_value="/usr/bin/wl-paste"):
                with patch("subprocess.run", mock_run):
                    types = list_clipboard_types()
        self.assertEqual(types, ["text/plain", "image/png"])
        self.assertEqual(mock_run.call_args[0][0][:2], ["/usr/bin/wl-paste", "-l"])

    def test_list_clipboard_types_x11_needs_xclip(self):
        from betterclip.clipboard import list_clipboard_types

        with patch("betterclip.clipboard.is_wayland", return_value=False):
            with patch("betterclip.clipboard.find_executable", return_value=None):
                self.assertEqual(list_clipboard_types(), [])

    def test_read_and_write_clipboard_image_mocked(self):
        from unittest.mock import MagicMock

        from betterclip.clipboard import read_clipboard_image, write_clipboard_image

        png = b"\x89PNG\r\n\x1a\n" + b"data"
        list_run = MagicMock()
        list_run.return_value.returncode = 0
        list_run.return_value.stdout = b"image/png\ntext/plain\n"
        paste_run = MagicMock()
        paste_run.return_value.returncode = 0
        paste_run.return_value.stdout = png

        def run_side_effect(args, **kwargs):
            if "-l" in args:
                return list_run.return_value
            return paste_run.return_value

        with patch("betterclip.clipboard.is_wayland", return_value=True):
            with patch("betterclip.clipboard.find_executable", return_value="/usr/bin/wl-paste"):
                with patch("subprocess.run", side_effect=run_side_effect):
                    got = read_clipboard_image()
        self.assertEqual(got, (png, "image/png"))

        copy_run = MagicMock()
        copy_run.return_value = MagicMock()
        with patch("betterclip.clipboard.is_wayland", return_value=True):
            with patch("betterclip.clipboard.find_executable", return_value="/usr/bin/wl-copy"):
                with patch("subprocess.run", copy_run):
                    self.assertTrue(write_clipboard_image(png, "image/png"))
                    self.assertFalse(write_clipboard_image(b"", "image/png"))
        self.assertEqual(copy_run.call_args[0][0], ["/usr/bin/wl-copy", "-t", "image/png"])
        self.assertEqual(copy_run.call_args.kwargs.get("input"), png)

    def test_read_clipboard_accepts_charset_utf8_mime(self):
        """GNOME/XWayland often offers text/plain;charset=utf-8, not ;utf-8."""
        from unittest.mock import MagicMock

        from betterclip.clipboard import read_clipboard

        def run_side_effect(args, **kwargs):
            r = MagicMock()
            if "-l" in args:
                r.returncode = 0
                r.stdout = b"text/plain;charset=utf-8\nUTF8_STRING\nTARGETS\n"
                return r
            if any("charset=utf-8" in str(a) for a in args):
                r.returncode = 0
                r.stdout = b"hola gnome"
                return r
            r.returncode = 1
            r.stdout = b""
            return r

        with patch("betterclip.clipboard.is_wayland", return_value=True):
            with patch("betterclip.clipboard.find_executable", return_value="/usr/bin/wl-paste"):
                with patch("betterclip.clipboard._read_text_x11", return_value=None):
                    with patch("subprocess.run", side_effect=run_side_effect):
                        self.assertEqual(read_clipboard(), "hola gnome")


class TestPicker(unittest.TestCase):
    """Test picker module (no rofi subprocess)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("betterclip.config.Path.home", return_value=Path(self.tmp))
        self.patcher.start()
        self.config_patcher = patch("betterclip.storage.load_config", return_value={"max_items": 50})
        self.config_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.config_patcher.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_show_picker_empty_history_returns_none(self):
        from betterclip.picker import show_picker

        with patch("betterclip.picker.find_executable", return_value="/usr/bin/rofi"):
            result = show_picker()
        self.assertIsNone(result)

    def test_truncate(self):
        from betterclip.picker import _truncate

        self.assertEqual(_truncate("short", 120), "short")
        self.assertEqual(_truncate("a" * 150, 120), "a" * 117 + "...")
        self.assertIn("\\\\", _truncate("back\\slash", 120))

    def test_format_stamp_local_day_hour_minute(self):
        from datetime import datetime, timezone

        from betterclip.picker import _format_stamp, _picker_line

        ts = "2026-10-03T14:54:00Z"
        expected = datetime(2026, 10, 3, 14, 54, tzinfo=timezone.utc).astimezone().strftime("%d/%H:%M")
        self.assertEqual(_format_stamp(ts), expected)
        self.assertEqual(_format_stamp("2026-10-03T14:54:00+00:00"), expected)
        self.assertEqual(_format_stamp(""), "--/--:--")
        self.assertEqual(_format_stamp("not-a-date"), "--/--:--")
        line = _picker_line(2, {"text": "copied", "timestamp": ts})
        self.assertEqual(line, f"2\t[{expected}] copied")
        image_line = _picker_line(
            0,
            {
                "kind": "image",
                "mime": "image/png",
                "timestamp": ts,
                "path": "images/abc.png",
                "width": 1920,
                "height": 1080,
                "bytes": 245760,
            },
        )
        self.assertEqual(image_line, f"0\t[{expected}] Imagen · PNG · 1920×1080 · 240 KB")

    def test_show_picker_with_mocked_rofi(self):
        """When rofi returns a selection, we get the full text back."""
        from unittest.mock import MagicMock

        from betterclip.picker import show_picker
        from betterclip.storage import add_entry

        add_entry("first item")
        add_entry("second item")

        mock_proc = MagicMock()
        # history reversed: [0]=second (most recent), [1]=first (older)
        mock_proc.communicate.return_value = ("0\tsecond item", None)

        with patch("betterclip.picker.find_executable", return_value="/usr/bin/rofi"):
            with patch("subprocess.Popen", return_value=mock_proc):
                result = show_picker()
        self.assertEqual(result["text"], "second item")
        fed = mock_proc.communicate.call_args.kwargs.get("input")
        if fed is None:
            fed = mock_proc.communicate.call_args[0][0]
        if isinstance(fed, bytes):
            fed = fed.decode("utf-8")
        first = fed.split("\n", 1)[0]
        self.assertRegex(first, r"^0\t\[\d{2}/\d{2}:\d{2}\] second item$")

    def test_rofi_env_clears_wayland_display_on_gnome(self):
        """rofi 2.x needs X11 on GNOME (no wlr layer-shell)."""
        from betterclip.picker import _rofi_env

        with patch.dict(
            os.environ,
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            clear=False,
        ):
            env = _rofi_env()
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertEqual(env.get("DISPLAY"), ":0")

    def test_show_picker_modern_mac_passes_theme_file(self):
        """modern_mac theme adds -theme pointing at bundled modern_mac.rasi."""
        from unittest.mock import MagicMock

        from betterclip.picker import show_picker
        from betterclip.rofi_theme import _THEMES_DIR
        from betterclip.storage import add_entry

        add_entry("only")

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("0\tonly", None)

        with patch("betterclip.picker.find_executable", return_value="/usr/bin/rofi"):
            with patch("betterclip.picker.load_config", return_value={"cli_mode": False, "theme": "modern_mac"}):
                with patch("betterclip.picker.is_wayland", return_value=True):
                    with patch("betterclip.picker._wait_for_shortcut_modifiers_release"):
                        with patch("subprocess.Popen", return_value=mock_proc) as popen_mock:
                            show_picker()
        argv = popen_mock.call_args[0][0]
        self.assertIn("-theme", argv)
        theme_idx = argv.index("-theme")
        self.assertTrue(str(argv[theme_idx + 1]).endswith("modern_mac.rasi"))
        self.assertEqual(Path(argv[theme_idx + 1]), _THEMES_DIR / "modern_mac.rasi")
        self.assertEqual(argv[argv.index("-scroll-method") + 1], "0")
        self.assertIn("-normal-window", argv)
        self.assertIn("-steal-focus", argv)
        self.assertIn("-click-to-exit", argv)

    def test_terminate_rofi_on_focus_loss_after_focus(self):
        """Once rofi had focus, leaving it cancels the picker (like Esc)."""
        from unittest.mock import MagicMock

        from betterclip import picker as picker_mod

        proc = MagicMock()
        # Alive until terminate; poll sequence driven by focus checks.
        alive = {"n": 0}

        def poll():
            return None if alive["n"] < 10 else 0

        proc.poll.side_effect = poll
        proc.pid = 4242

        focus_seq = [True, True, False]

        def fake_active(_dpy, _root, pid):
            self.assertEqual(pid, 4242)
            alive["n"] += 1
            if focus_seq:
                return focus_seq.pop(0)
            return False

        with patch.object(picker_mod, "_x11_active_window_is_pid", side_effect=fake_active):
            with patch.object(picker_mod, "_FOCUS_POLL_S", 0):
                with patch.dict("sys.modules", {"Xlib": MagicMock(), "Xlib.display": MagicMock()}):
                    import sys

                    sys.modules["Xlib"].display.Display.return_value = MagicMock()
                    picker_mod._terminate_rofi_on_focus_loss(proc)

        proc.terminate.assert_called_once()

    def test_show_picker_cli_mode_returns_selection(self):
        """When cli_mode is True, selection comes from stdin (no rofi)."""
        from io import StringIO

        from betterclip.picker import show_picker
        from betterclip.storage import add_entry

        add_entry("first")
        add_entry("second")

        with patch("betterclip.picker.load_config", return_value={"cli_mode": True}):
            with patch("sys.stdin", StringIO("1\n")):
                result = show_picker()
        self.assertEqual(result["text"], "first")


class TestRofiThemeAsset(unittest.TestCase):
    """Rofi .rasi guardrails (parser quirks differ from CSS)."""

    def _modern_mac_path(self) -> Path:
        repo_root = Path(__file__).resolve().parent.parent
        return repo_root / "betterclip" / "themes" / "modern_mac.rasi"

    def test_modern_mac_rasi_avoids_hex_inside_border_shorthand(self):
        """rofi 1.7 fails on `#hex` inside `border: … #…` shorthand."""
        path = self._modern_mac_path()
        self.assertTrue(path.is_file(), msg=f"missing {path}")
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bborder\s*:\s*[^;\n]*#", text):
            self.fail(
                "Avoid #colors inside `border:` shorthand in .rasi; use `border: …` plus "
                "a separate `border-color:` line (rofi parser limitation)."
            )

    def test_modern_mac_rasi_no_css_border_style_property(self):
        """rofi rasi is not CSS: `border-style:` / `solid` are rejected by the parser."""
        path = self._modern_mac_path()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bborder-style\s*:", text):
            self.fail(
                "Do not use `border-style:` in .rasi; use rofi border syntax like "
                "`border: 1px dash 0px 0px;` with `border-color:`."
            )

    def test_modern_mac_rasi_rofi_parses_when_display_available(self):
        """Optional: launch rofi briefly — parse errors exit immediately with stderr."""
        import shutil
        import subprocess

        rofi = shutil.which("rofi")
        if not rofi:
            self.skipTest("rofi not in PATH")
        if not os.environ.get("DISPLAY"):
            self.skipTest("no DISPLAY")

        path = self._modern_mac_path()
        proc = subprocess.Popen(
            [rofi, "-no-config", "-dmenu", "-theme", str(path.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ,
        )
        try:
            out, err = proc.communicate(timeout=0.4)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=2)
        combined = (err or "") + (out or "")

        self.assertNotIn("Error while parsing", combined)
        self.assertNotIn("syntax error", combined.lower())
        self.assertNotIn("parser error", combined.lower())


class TestDaemonSessionEnv(unittest.TestCase):
    def test_import_user_manager_environment_sets_all_keys(self):
        from betterclip.daemon import import_user_manager_environment

        stdout = (
            "DISPLAY=:0\n"
            "WAYLAND_DISPLAY=wayland-0\n"
            "XDG_SESSION_TYPE=wayland\n"
            "XAUTHORITY=/tmp/xauth\n"
            "UNRELATED=ignore\n"
        )
        with patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
            os.environ.pop("WAYLAND_DISPLAY", None)
            import_user_manager_environment(stdout)
            self.assertEqual(os.environ.get("DISPLAY"), ":0")
            self.assertEqual(os.environ.get("WAYLAND_DISPLAY"), "wayland-0")
            self.assertEqual(os.environ.get("XDG_SESSION_TYPE"), "wayland")
            self.assertEqual(os.environ.get("XAUTHORITY"), "/tmp/xauth")

    def test_run_daemon_falls_back_when_wl_paste_watch_exits(self):
        from unittest.mock import MagicMock

        from betterclip import daemon as daemon_mod

        fake_proc = MagicMock()
        fake_proc.wait.return_value = 1
        calls: list[str] = []

        def fake_fallback():
            calls.append("fallback")

        with (
            patch.object(daemon_mod, "_wait_for_display", return_value=":0"),
            patch.object(daemon_mod, "find_executable", return_value="/usr/bin/wl-paste"),
            patch.object(daemon_mod, "_wayland_wlroots_watch_supported", return_value=True),
            patch.object(daemon_mod, "_wayland_run_watcher", return_value=fake_proc),
            patch.object(daemon_mod, "_monitor_via_x11_or_poll", side_effect=fake_fallback),
            patch("betterclip.clipboard.is_wayland", return_value=True),
        ):
            daemon_mod.run_daemon()

        fake_proc.wait.assert_called_once()
        self.assertEqual(calls, ["fallback"])

    def test_on_new_clipboard_prefers_image(self):
        from unittest.mock import MagicMock

        from betterclip import daemon as daemon_mod

        png = b"\x89PNG\r\n\x1a\n" + b"shot"
        added: list[tuple] = []

        def fake_payload(kind, mime, data):
            added.append((kind, mime, data))

        with (
            patch.object(daemon_mod, "_on_clipboard_payload", side_effect=fake_payload),
            patch("betterclip.clipboard.read_clipboard_image", return_value=(png, "image/png")),
            patch("betterclip.clipboard.read_clipboard", MagicMock()) as read_text,
        ):
            daemon_mod._on_new_clipboard()

        self.assertEqual(added, [("image", "image/png", png)])
        read_text.assert_not_called()

    def test_on_clipboard_payload_ignores_picker_self_write(self):
        """Reselecting in Super+V must not append the line again."""
        from betterclip import daemon as daemon_mod
        from betterclip.storage import add_entry, load_history, mark_self_write

        tmp = tempfile.mkdtemp()
        try:
            with patch("betterclip.config.Path.home", return_value=Path(tmp)):
                with patch("betterclip.storage.load_config", return_value={"max_items": 50}):
                    add_entry("older")
                    add_entry("newer")
                    mark_self_write("text", b"older")
                    daemon_mod._on_clipboard_payload("text", "text/plain", b"older")
                    hist = load_history()
                    self.assertEqual([e.get("text") for e in hist], ["older", "newer"])
                    # A real copy of the same text after the marker is gone is recorded.
                    daemon_mod._on_clipboard_payload("text", "text/plain", b"older")
                    hist = load_history()
                    self.assertEqual([e.get("text") for e in hist], ["older", "newer", "older"])
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_picker_marks_self_write_before_clipboard(self):
        from unittest.mock import MagicMock

        from betterclip import picker as picker_mod
        from betterclip.storage import take_self_write_ignore

        tmp = tempfile.mkdtemp()
        try:
            with patch("betterclip.config.Path.home", return_value=Path(tmp)):
                with patch.object(
                    picker_mod,
                    "show_picker",
                    return_value={"text": "from history", "timestamp": "2026-01-01T00:00:00Z"},
                ):
                    with patch.object(picker_mod, "load_config", return_value={"cli_mode": False}):
                        with patch.object(
                            picker_mod, "get_write_tool", return_value=("/bin/true", [])
                        ):
                            with patch("subprocess.run", MagicMock()) as run:
                                self.assertTrue(picker_mod.run_picker())
                                run.assert_called_once()
                self.assertTrue(take_self_write_ignore("text", b"from history"))
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestSystemdUnit(unittest.TestCase):
    def _unit_text(self) -> str:
        path = Path(__file__).resolve().parent.parent / "systemd" / "betterclip.service"
        return path.read_text(encoding="utf-8")

    def test_restart_always_and_start_limit_in_unit_section(self):
        text = self._unit_text()
        self.assertRegex(text, r"(?m)^Restart=always$")
        unit_section = text.split("[Service]", 1)[0]
        self.assertIn("StartLimitIntervalSec=", unit_section)
        service_section = text.split("[Service]", 1)[1]
        self.assertNotIn("StartLimitIntervalSec=", service_section)


if __name__ == "__main__":
    unittest.main()
