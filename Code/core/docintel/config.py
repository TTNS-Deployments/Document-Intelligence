"""Runtime settings, read from environment variables.

``DOCINTEL_MODE`` sets the default for every backend:

* ``local`` (default): files in a folder, mock Document Intelligence analyzer.
* ``azure``: Blob Storage and Azure AI Document Intelligence, reached with the managed identity.

Each backend can be overridden on its own, for example run locally but call the real service with
``ANALYZE_BACKEND=azure``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    # An unresolved App Service Key Vault reference arrives as the literal reference string.
    return "" if value.startswith("@Microsoft.KeyVault(") else value


def _env_int(name: str, default: int) -> int:
    value = _env(name) or str(default)
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def _env_float(name: str, default: float) -> float:
    value = _env(name) or str(default)
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {value!r}") from None


MODES = ("local", "azure")


def find_repo_dir(name: str) -> Path | None:
    """Walk up from this package looking for a sibling folder (``Config``, ``Data``).

    Works both in the repo (Code/core/docintel -> repo root) and in a deployed app package where the folder is
    copied next to the package.
    """
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    return None


def _yaml_defaults(config_dir: Path | None) -> dict:
    path = (config_dir / "settings.yaml") if config_dir else None
    if path and path.is_file():
        return yaml.safe_load(path.read_text()) or {}
    return {}


@dataclass(frozen=True)
class Settings:
    mode: str = "local"
    environment_name: str = "local"

    # Storage
    storage_backend: str = "local"
    local_data_dir: Path = field(default_factory=lambda: Path(".localdata"))
    storage_connection_string: str = ""
    storage_account_url: str = ""
    container_uploads: str = "uploads"
    container_results: str = "results"
    container_config: str = "config"

    # Document Intelligence
    analyze_backend: str = "mock"
    docintel_endpoint: str = ""
    docintel_key: str = ""  # developer machines only; Azure uses the managed identity
    docintel_api_version: str = "2024-11-30"
    mock_delay_seconds: float = 0.8

    # Limits (defaults from Config/settings.yaml, then env; review/limit/pages are also editable at runtime)
    max_upload_mb: int = 10
    max_pages: int = 10
    daily_page_limit: int = 200
    review_threshold: float = 0.80
    retention_days: int = 7  # display only: the storage lifecycle policy does the deleting
    worker_threads: int = 2
    max_attempts: int = 3
    retry_base_seconds: float = 2.0

    display_time_zone: str = "Asia/Kolkata"
    azure_client_id: str = ""  # user-assigned identity; empty = system-assigned / developer login

    config_dir: Path | None = None
    data_dir: Path | None = None

    @property
    def is_local(self) -> bool:
        return self.mode == "local"

    @property
    def sample_dir(self) -> Path | None:
        return (self.data_dir / "sample_invoices") if self.data_dir else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    mode = _env("DOCINTEL_MODE", "local").lower()
    if mode not in MODES:
        raise ValueError(f"Unknown DOCINTEL_MODE {mode!r} (local or azure)")
    azure = mode == "azure"

    config_dir_env = _env("DOCINTEL_CONFIG_DIR")
    data_dir_env = _env("DOCINTEL_DATA_DIR")
    config_dir = Path(config_dir_env) if config_dir_env else find_repo_dir("Config")
    data_dir = Path(data_dir_env) if data_dir_env else find_repo_dir("Data")
    y = _yaml_defaults(config_dir)

    return Settings(
        mode=mode,
        environment_name=_env("ENVIRONMENT_NAME", "local" if not azure else "azure"),
        storage_backend=_env("STORAGE_BACKEND", "azure" if azure else "local").lower(),
        local_data_dir=Path(_env("LOCAL_DATA_DIR", str(_default_local_data_dir()))),
        storage_connection_string=_env("AZURE_STORAGE_CONNECTION_STRING"),
        storage_account_url=_env("AZURE_STORAGE_ACCOUNT_URL").rstrip("/"),
        container_uploads=_env("CONTAINER_UPLOADS", "uploads"),
        container_results=_env("CONTAINER_RESULTS", "results"),
        container_config=_env("CONTAINER_CONFIG", "config"),
        analyze_backend=_env("ANALYZE_BACKEND", "azure" if azure else "mock").lower(),
        docintel_endpoint=_env("DOCINTEL_ENDPOINT").rstrip("/"),
        docintel_key=_env("DOCINTEL_KEY"),
        docintel_api_version=_env("DOCINTEL_API_VERSION", "2024-11-30"),
        mock_delay_seconds=_env_float("MOCK_ANALYZE_DELAY", 0.8),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", int(y.get("max_upload_mb", 10))),
        max_pages=_env_int("MAX_PAGES", int(y.get("max_pages", 10))),
        daily_page_limit=_env_int("DAILY_PAGE_LIMIT", int(y.get("daily_page_limit", 200))),
        review_threshold=_env_float("REVIEW_THRESHOLD", float(y.get("review_threshold", 0.80))),
        retention_days=_env_int("RETENTION_DAYS", 7),
        worker_threads=max(1, _env_int("WORKER_THREADS", int(y.get("worker_threads", 2)))),
        max_attempts=max(1, _env_int("ANALYZE_MAX_ATTEMPTS", int(y.get("max_attempts", 3)))),
        retry_base_seconds=_env_float("ANALYZE_RETRY_BASE_SECONDS", 2.0),
        display_time_zone=_env("DISPLAY_TIME_ZONE", "Asia/Kolkata"),
        azure_client_id=_env("AZURE_CLIENT_ID"),
        config_dir=config_dir,
        data_dir=data_dir,
    )


def _default_local_data_dir() -> Path:
    root = find_repo_dir("Code")
    # repo/Code exists -> keep local data at repo/.localdata
    return (root.parent / ".localdata") if root else Path(".localdata")


def reset_settings_cache() -> None:
    """Used by tests after changing environment variables."""
    get_settings.cache_clear()
    from . import factory

    factory.reset()
