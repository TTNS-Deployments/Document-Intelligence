"""Settings an Admin can change at runtime (Settings page), stored as settings.json in the config container.

Precedence: saved value > environment variable > Config/settings.yaml (the last two are merged in ``config``).
"""

from __future__ import annotations

import threading
import time

from .config import get_settings
from .factory import get_blob_store

SETTINGS_BLOB = "settings.json"
EDITABLE = {
    # name: (type, minimum, maximum)
    "review_threshold": (float, 0.0, 1.0),
    "daily_page_limit": (int, 0, 1_000_000),
    "max_pages": (int, 1, 2000),
}
_CACHE_SECONDS = 10.0
_cache: dict = {"at": 0.0, "values": None}
_lock = threading.Lock()


class SettingsError(ValueError):
    pass


def clear_cache() -> None:
    with _lock:
        _cache.update(at=0.0, values=None)


def _saved() -> dict:
    s = get_settings()
    return get_blob_store().get_json_or_none(s.container_config, SETTINGS_BLOB) or {}


def get_runtime_settings() -> dict:
    """Effective values. Cached for a few seconds so pages do not read the blob on every request."""
    with _lock:
        if _cache["values"] is not None and time.monotonic() - _cache["at"] < _CACHE_SECONDS:
            return dict(_cache["values"])
    s = get_settings()
    values = {
        "review_threshold": s.review_threshold,
        "daily_page_limit": s.daily_page_limit,
        "max_pages": s.max_pages,
        "max_upload_mb": s.max_upload_mb,
        "retention_days": s.retention_days,
    }
    saved = _saved()
    for name, (kind, lo, hi) in EDITABLE.items():
        if name in saved:
            try:
                values[name] = min(hi, max(lo, kind(saved[name])))
            except (TypeError, ValueError):
                pass  # a hand-edited blob with a bad value: keep the default
    with _lock:
        _cache.update(at=time.monotonic(), values=dict(values))
    return values


def save_runtime_settings(changes: dict) -> dict:
    clean = {}
    for name, raw in changes.items():
        if name not in EDITABLE:
            raise SettingsError(f"{name} cannot be changed here")
        kind, lo, hi = EDITABLE[name]
        try:
            value = kind(raw)
        except (TypeError, ValueError):
            raise SettingsError(f"{name} must be a {'number' if kind is float else 'whole number'}") from None
        if not lo <= value <= hi:
            raise SettingsError(f"{name} must be between {lo} and {hi}")
        clean[name] = value
    s = get_settings()
    saved = _saved()
    saved.update(clean)
    get_blob_store().put_json(s.container_config, SETTINGS_BLOB, saved)
    clear_cache()
    return get_runtime_settings()
