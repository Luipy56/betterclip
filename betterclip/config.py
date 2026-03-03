"""Configuration loading for betterClip."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MAX_ITEMS = 50
MAX_ITEMS_LIMIT = 1000
DEFAULT_CONFIG = {
    "max_items": DEFAULT_MAX_ITEMS,
    "hotkey": "Super+V",
}

# Cache: (config, mtime) to avoid repeated file reads in daemon
_config_cache: tuple[dict, float] | None = None


def get_config_dir() -> Path:
    """Return XDG config directory for betterClip."""
    xdg = Path.home() / ".config" / "betterclip"
    xdg.mkdir(parents=True, exist_ok=True)
    return xdg


def get_data_dir() -> Path:
    """Return XDG data directory for betterClip."""
    xdg = Path.home() / ".local" / "share" / "betterclip"
    xdg.mkdir(parents=True, exist_ok=True)
    return xdg


def get_history_path() -> Path:
    """Return path to history JSON file."""
    return get_data_dir() / "history.json"


def get_config_path() -> Path:
    """Return path to config JSON file."""
    return get_config_dir() / "config.json"


def load_config(*, use_cache: bool = True) -> dict:
    """Load config from JSON, merging with defaults."""
    global _config_cache
    path = get_config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    if use_cache and _config_cache is not None:
        cached_config, cached_mtime = _config_cache
        if mtime == cached_mtime:
            return cached_config.copy()

    config = DEFAULT_CONFIG.copy()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                user = json.load(f)
            config.update(user)
        except (json.JSONDecodeError, OSError):
            pass

    # Validate max_items: clamp to [1, MAX_ITEMS_LIMIT] or use default
    mi = config.get("max_items", DEFAULT_MAX_ITEMS)
    try:
        mi = int(mi)
        config["max_items"] = max(1, min(mi, MAX_ITEMS_LIMIT)) if mi > 0 else DEFAULT_MAX_ITEMS
    except (TypeError, ValueError):
        config["max_items"] = DEFAULT_MAX_ITEMS

    _config_cache = (config, mtime)
    return config.copy()


def save_config(config: dict) -> None:
    """Save config to JSON and invalidate cache."""
    global _config_cache
    _config_cache = None
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
