"""Tests for betterclip - run with pytest or python -m pytest."""

from __future__ import annotations

import os
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


if __name__ == "__main__":
    unittest.main()
