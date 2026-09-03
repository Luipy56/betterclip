"""Rofi theme ids and argv fragments for the clipboard picker."""

from __future__ import annotations

from pathlib import Path

THEMES = frozenset({"classic", "modern_mac"})
DEFAULT_THEME = "modern_mac"

_THEMES_DIR = Path(__file__).resolve().parent / "themes"


def rofi_theme_args(theme_id: str) -> list[str]:
    """Extra rofi argv for the given theme (empty for classic)."""
    if theme_id == "classic":
        return []
    if theme_id == "modern_mac":
        path = _THEMES_DIR / "modern_mac.rasi"
        if path.is_file():
            return ["-theme", str(path)]
        return []
    return []


def rofi_scroll_method_args(theme_id: str) -> list[str]:
    """
    Pager-style scrolling (0) tends to feel steadier than centered (1) on themed dmenu.
    Only applied where we ship a custom theme that stresses the listview.
    """
    if theme_id == "modern_mac":
        return ["-scroll-method", "0"]
    return []
