import pytest

from docintel.config import reset_settings_cache


@pytest.fixture(autouse=True)
def local_mode(tmp_path, monkeypatch):
    """Every test runs in local mode against a fresh, empty data folder, with no delays."""
    for name in ("DOCINTEL_MODE", "STORAGE_BACKEND", "ANALYZE_BACKEND", "REVIEW_THRESHOLD", "DAILY_PAGE_LIMIT",
                 "MAX_PAGES", "MAX_UPLOAD_MB", "WORKER_THREADS", "ANALYZE_MAX_ATTEMPTS", "RETENTION_DAYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOCK_ANALYZE_DELAY", "0")
    monkeypatch.setenv("ANALYZE_RETRY_BASE_SECONDS", "0")
    reset_settings_cache()
    yield
    reset_settings_cache()
