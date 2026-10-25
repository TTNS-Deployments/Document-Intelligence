"""Analysis jobs inside the web app process: submission, a small worker pool, claims, retries and recovery.

* ``submit_file`` checks the upload (pages.inspect_upload), the model and the fields, counts the pages against
  the daily budget, saves the original and a ``queued`` record, and queues the job.
* ``JobRunner`` runs ``WORKER_THREADS`` (default 2) daemon threads. Each job holds only its own file in memory.
* A job is **claimed** by rewriting its record from ``queued`` to ``processing`` with the record's ETag as a
  condition, so two processes (or two threads) never run the same job.
* Transient errors (HTTP 429, 5xx, network) are retried with exponential back-off, up to ``ANALYZE_MAX_ATTEMPTS``.
* On start-up, ``recover`` re-queues ``queued`` jobs and ``processing`` jobs whose process is gone (a restart on
  this instance, or a claim that expired).

Logs contain job IDs, model, page counts, durations and status only, never field values or file content.
"""

from __future__ import annotations

import logging
import os
import queue
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import results
from .analyze import AnalyzeError
from .catalog import load_catalog
from .config import get_settings
from .factory import get_analyzer
from .pages import inspect_upload, reserve_pages
from .settings_store import get_runtime_settings
from .storage import PreconditionFailed

log = logging.getLogger(__name__)

CLAIM_MINUTES = 15
_identity = {"value": ""}


def instance_id() -> str:
    return os.environ.get("WEBSITE_INSTANCE_ID", "")[:12] or socket.gethostname()


def process_identity() -> str:
    """``<instance>:<pid>:<random>``. A new process (after a restart) gets a new identity."""
    if not _identity["value"]:
        _identity["value"] = f"{instance_id()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    return _identity["value"]


def reset_process_identity() -> None:
    _identity["value"] = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------------------- submission

def submit_file(filename: str, data: bytes, *, model_id: str, fields, owner: str, owner_role: str,
                batch_id: str = "", sample: str | None = None, start: bool = True) -> dict:
    """Validate, count pages, store and queue one file. Raises UploadRejected, CatalogError or BudgetExceeded."""
    s = get_settings()
    rt = get_runtime_settings()
    catalog = load_catalog()
    model = catalog.enabled_model(model_id)
    selection = catalog.validate_selection(model.id, fields)
    info = inspect_upload(filename, data, max_mb=rt["max_upload_mb"], max_pages=rt["max_pages"])
    reserve_pages(info.pages, rt["daily_page_limit"])  # counted before the call; raises when over budget
    doc_id = results.new_id()
    record = results.new_record(doc_id=doc_id, filename=info.filename, kind=info.kind,
                                content_type=info.content_type, size=info.size, pages=info.pages, sha256=info.sha256,
                                model_id=model.id, api_version=s.docintel_api_version, selection=selection,
                                owner=owner, owner_role=owner_role, batch_id=batch_id or doc_id, sample=sample)
    results.create(record, data)
    log.info("job %s queued model=%s pages=%d", doc_id, model.id, info.pages)
    if start:
        from .factory import get_job_runner

        get_job_runner().submit(doc_id)
    return record


def retry(doc_id: str, *, start: bool = True) -> dict:
    """Queue a failed job again. Its pages are counted again, because it calls the service again."""
    record = results.get(doc_id)
    if record["status"] != "failed":
        raise ValueError("Only failed documents can be retried")
    reserve_pages(record.get("pages") or 1, get_runtime_settings()["daily_page_limit"])

    def change(r):
        if r["status"] != "failed":
            raise ValueError("Only failed documents can be retried")
        r.update(status="queued", error=None, claimed_by=None, claim_expires=None, attempts=0)

    record = results.update(doc_id, change)
    log.info("job %s re-queued", doc_id)
    if start:
        from .factory import get_job_runner

        get_job_runner().submit(doc_id)
    return record


# --------------------------------------------------------------------------------------------- processing

def claim(doc_id: str) -> tuple[dict, str] | None:
    """Move a job from queued to processing, atomically. None when it is not queued or another process won."""
    try:
        record, etag = results.get_with_etag(doc_id)
    except results.NotFound:
        return None
    if record["status"] != "queued":
        return None
    record.update(status="processing", claimed_by=process_identity(), started_at=results.now_iso(),
                  claim_expires=(_now() + timedelta(minutes=CLAIM_MINUTES)).isoformat(),
                  attempts=int(record.get("attempts") or 0))
    try:
        return record, results.save(record, etag)
    except PreconditionFailed:
        log.info("job %s already claimed elsewhere", doc_id)
        return None


def process(doc_id: str, *, sleep=time.sleep) -> str | None:
    """Run one job end to end. Returns the final status, or None when this process did not claim it."""
    claimed = claim(doc_id)
    if claimed is None:
        return None
    record, etag = claimed
    s = get_settings()
    started = time.monotonic()
    outcome: dict
    try:
        data = results.read_original(record)
    except results.NotFound:
        data = None
    if data is None:
        outcome = {"status": "failed", "error": {"code": "missing", "message": "The original file is missing."}}
    else:
        outcome = _analyze_with_retries(record, data, s.max_attempts, s.retry_base_seconds, sleep)
        del data  # only one file in memory per job
    duration_ms = int((time.monotonic() - started) * 1000)

    def finish(r):
        if r.get("claimed_by") != process_identity():
            raise _LostClaim()
        r.update(outcome, finished_at=results.now_iso(), duration_ms=duration_ms, claimed_by=None,
                 claim_expires=None)
        if outcome["status"] == "done":
            r["error"] = None

    try:
        results.update(doc_id, finish)
    except results.NotFound:
        log.info("job %s was deleted while processing", doc_id)
        return None
    except _LostClaim:
        log.warning("job %s was taken over by another process; result discarded", doc_id)
        return None
    log.info("job %s %s model=%s pages=%s attempts=%s duration_ms=%d", doc_id, outcome["status"],
             record["model_id"], record.get("pages"), outcome.get("attempts"), duration_ms)
    return outcome["status"]


class _LostClaim(Exception):
    pass


def _analyze_with_retries(record: dict, data: bytes, max_attempts: int, base: float, sleep) -> dict:
    analyzer = get_analyzer()
    attempts = 0
    while True:
        attempts += 1
        try:
            analysis = analyzer.analyze(data, record["model_id"])
            mock = analysis.pop("_mock", None)
            return {"status": "done", "analysis": analysis, "mock": mock, "attempts": attempts,
                    "api_version": analysis.get("apiVersion") or record.get("api_version")}
        except AnalyzeError as exc:
            if exc.transient and attempts < max_attempts:
                delay = base * (2 ** (attempts - 1))
                log.info("job %s transient error %s (attempt %d), retrying in %.1fs", record["id"], exc.code,
                         attempts, delay)
                sleep(delay)
                continue
            message = exc.message
            if exc.transient:
                message += f" (tried {attempts} times)"
            return {"status": "failed", "error": {"code": exc.code, "message": message}, "attempts": attempts}
        except Exception as exc:  # noqa: BLE001 - unexpected: never leave a job in processing
            log.error("job %s unexpected error %s", record["id"], type(exc).__name__)
            return {"status": "failed", "attempts": attempts,
                    "error": {"code": "internal", "message": "Analysis failed because of an unexpected error. "
                                                             "Retry, and contact support if it happens again."}}


# --------------------------------------------------------------------------------------------- recovery

def recover(runner: "JobRunner | None" = None) -> list[str]:
    """Re-queue jobs left behind by a restart. Returns the IDs that were queued."""
    me = process_identity()
    here = instance_id()
    queued = []
    for row in results.list_summaries():
        if row["status"] == "queued":
            queued.append(row["id"])
        elif row["status"] == "processing":
            try:
                record, etag = results.get_with_etag(row["id"])
            except results.NotFound:
                continue
            claimed_by = record.get("claimed_by") or ""
            expires = record.get("claim_expires")
            expired = not expires or datetime.fromisoformat(expires) < _now()
            restarted_here = claimed_by.split(":")[0] == here and claimed_by != me
            if record["status"] == "processing" and (expired or restarted_here):
                record.update(status="queued", claimed_by=None, claim_expires=None)
                try:
                    results.save(record, etag)
                    queued.append(row["id"])
                    log.info("job %s re-queued after restart", row["id"])
                except PreconditionFailed:
                    continue
    if runner is not None:
        for doc_id in queued:
            runner.submit(doc_id, recovering=True)
    return queued


class JobRunner:
    """A small pool of daemon threads fed by an in-process queue. Started on first use."""

    def __init__(self, threads: int | None = None):
        self.threads = threads or get_settings().worker_threads
        self.queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._started = False

    def ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for i in range(self.threads):
                t = threading.Thread(target=self._loop, name=f"docintel-worker-{i}", daemon=True)
                t.start()
                self._workers.append(t)
        try:
            recover(self)
        except Exception:  # noqa: BLE001 - storage may be briefly unavailable; new jobs still run
            log.exception("job recovery failed")

    def submit(self, doc_id: str, recovering: bool = False) -> None:
        if not recovering:
            self.ensure_started()
        self.queue.put(doc_id)

    def _loop(self) -> None:
        while True:
            doc_id = self.queue.get()
            try:
                if doc_id is None:
                    return
                process(doc_id)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("job %s crashed the worker loop", doc_id)
            finally:
                self.queue.task_done()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Tests and the CLI: wait until the queue is empty and every job has finished."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        with self._lock:
            workers, self._workers, self._started = self._workers, [], False
        for _ in workers:
            self.queue.put(None)
        for t in workers:
            t.join(timeout=5)
