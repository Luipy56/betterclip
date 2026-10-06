"""Storage for clipboard history (JSON, max N items)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .clipboard import image_dimensions, normalize_mime
from .config import get_data_dir, get_history_path, load_config
from .utils import IMAGE_MAX_BYTES, IMAGE_MIMES

_IMAGE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _ensure_data_dir() -> Path:
    path = get_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_image_path(rel: str) -> Path:
    """Absolute path for a history-relative image blob."""
    return get_data_dir() / rel


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


def _delete_image_blob(entry: dict) -> None:
    if entry.get("kind") != "image":
        return
    rel = entry.get("path")
    if not rel or not isinstance(rel, str):
        return
    path = resolve_image_path(rel)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _trim_history(history: list[dict], max_items: int) -> list[dict]:
    if len(history) <= max_items:
        return history
    dropped = history[:-max_items]
    kept = history[-max_items:]
    for entry in dropped:
        _delete_image_blob(entry)
    return kept


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
    if history and history[-1].get("kind") != "image" and history[-1].get("text") == text:
        return history

    config = load_config()
    max_items = config.get("max_items", 50)

    entry = {
        "text": text,
        "timestamp": _utc_now(),
    }
    history.append(entry)
    history = _trim_history(history, max_items)

    save_history(history)
    return history


def add_image_entry(
    data: bytes,
    mime: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """
    Store an image blob and append a history entry.
    Consecutive duplicates are skipped by SHA-256. Oversized payloads are ignored.
    """
    if history is None:
        history = load_history()

    mime = normalize_mime(mime)
    if not data or mime not in IMAGE_MIMES or len(data) > IMAGE_MAX_BYTES:
        return history

    sha = hashlib.sha256(data).hexdigest()
    if (
        history
        and history[-1].get("kind") == "image"
        and history[-1].get("sha256") == sha
    ):
        return history

    ext = _IMAGE_EXT.get(mime, ".bin")
    rel = f"images/{sha}{ext}"
    dest = resolve_image_path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)

    config = load_config()
    max_items = config.get("max_items", 50)
    entry: dict = {
        "kind": "image",
        "mime": mime,
        "path": rel,
        "sha256": sha,
        "bytes": len(data),
        "timestamp": _utc_now(),
    }
    dims = image_dimensions(data)
    if dims:
        entry["width"], entry["height"] = dims
    history.append(entry)
    history = _trim_history(history, max_items)
    save_history(history)
    return history


def get_history_reversed() -> list[dict]:
    """Return history in reverse order (most recent first) for display."""
    return list(reversed(load_history()))
