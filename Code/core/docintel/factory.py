"""Builds the configured implementation of each dependency (cached per process)."""

from __future__ import annotations

from functools import lru_cache

from .config import get_settings


def _unknown(kind: str, value: str):
    return ValueError(f"Unknown {kind} backend '{value}'")


@lru_cache(maxsize=1)
def get_blob_store():
    from . import storage

    s = get_settings()
    if s.storage_backend == "local":
        return storage.LocalBlobStore(s.local_data_dir / "storage")
    if s.storage_backend == "azure":
        return storage.AzureBlobStore(s)
    raise _unknown("storage", s.storage_backend)


@lru_cache(maxsize=1)
def get_analyzer():
    from . import analyze

    s = get_settings()
    if s.analyze_backend == "mock":
        return analyze.MockAnalyzer(s)
    if s.analyze_backend == "azure":
        return analyze.AzureAnalyzer(s)
    raise _unknown("analyze", s.analyze_backend)


@lru_cache(maxsize=1)
def get_job_runner():
    from . import jobs

    return jobs.JobRunner()


def reset() -> None:
    from . import azure_auth, catalog, jobs, settings_store

    runner = get_job_runner() if get_job_runner.cache_info().currsize else None
    if runner is not None:
        runner.stop()
    for fn in (get_blob_store, get_analyzer, get_job_runner, azure_auth.get_credential, catalog.load_catalog):
        fn.cache_clear()
    settings_store.clear_cache()
    jobs.reset_process_identity()
