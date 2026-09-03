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
        self.assertEqual(result, "second item")

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
        self.assertEqual(result, "first")


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


if __name__ == "__main__":
    unittest.main()
