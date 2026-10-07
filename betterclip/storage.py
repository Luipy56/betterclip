"""Storage for clipboard history (JSON, max N items)."""

from __future__ import annotations

import hashlib
import json
import time
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

# Picker re-writes CLIPBOARD so the user can paste; the daemon must not treat
# that as a fresh Ctrl+C. Marker TTL covers XFixes/wl-paste latency.
_SELF_WRITE_TTL_S = 5.0
_SELF_WRITE_NAME = "self_write.json"


def _ensure_data_dir() -> Path:
    path = get_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_image_path(rel: str) -> Path:
    """Absolute path for a history-relative image blob."""
    return get_data_dir() / rel


def _self_write_path() -> Path:
    return get_data_dir() / _SELF_WRITE_NAME


def mark_self_write(kind: str, data: bytes) -> None:
    """
    Announce that betterclip itself is about to write CLIPBOARD.

    The daemon will ignore one matching capture within _SELF_WRITE_TTL_S.
    """
    if kind not in ("text", "image") or not data:
        return
    path = _self_write_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": kind,
        "sha256": hashlib.sha256(data).hexdigest(),
        "ts": time.time(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def take_self_write_ignore(kind: str, data: bytes) -> bool:
    """
    Return True if this clipboard payload is our own picker write (and clear it).

    Mismatched events leave the marker in place so a later matching capture
    (the real picker write) can still be ignored. Stale markers are dropped.
    """
    if kind not in ("text", "image") or not data:
        return False
    path = _self_write_path()
    try:
        raw = path.read_text(encoding="utf-8")
        marker = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return False

    def _clear() -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    if not isinstance(marker, dict):
        _clear()
        return False
    try:
        ts = float(marker.get("ts", 0))
    except (TypeError, ValueError):
        _clear()
        return False
    if time.time() - ts > _SELF_WRITE_TTL_S:
        _clear()
        return False
    digest = hashlib.sha256(data).hexdigest()
    if marker.get("kind") != kind or marker.get("sha256") != digest:
        return False
    _clear()
    return True


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
