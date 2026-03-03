"""Storage for clipboard history (JSON, max N items)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import get_history_path, load_config


def _ensure_data_dir() -> Path:
    path = get_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_history() -> list[dict]:
    """Load history from JSON file. Returns list ordered oldest-first."""
    path = get_history_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history: list[dict]) -> None:
    """Save history to JSON file."""
    _ensure_data_dir()
    path = get_history_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def add_entry(text: str, history: list[dict] | None = None) -> list[dict]:
    """
    Add text to history. Deduplicates consecutive duplicates.
    Respects max_items from config.
    Returns updated history (oldest-first).
    """
    if history is None:
        history = load_history()

    text = text.strip()
    if not text:
        return history

    # Skip if same as last entry (consecutive duplicate)
    if history and history[-1].get("text") == text:
        return history

    config = load_config()
    max_items = config.get("max_items", 50)

    entry = {
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    history.append(entry)

    if len(history) > max_items:
        history = history[-max_items:]

    save_history(history)
    return history


def get_history_reversed() -> list[dict]:
    """Return history in reverse order (most recent first) for display."""
    return list(reversed(load_history()))
