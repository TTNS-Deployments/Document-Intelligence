"""Upload batches: many documents uploaded together, processed in the background, reviewed and exported together.

A batch record is a small JSON blob, ``results/batches/<id>.json`` (so the retention policy of the results container
removes it with its documents). The documents themselves are ordinary results whose ``batch_id`` is the batch ID;
progress is computed from their blob metadata, so nothing has to be kept in step.

The browser sends a batch one file per request and then marks the upload as finished. If it never does (the tab
was closed while uploading), the upload counts as interrupted after ``UPLOAD_IDLE_MINUTES`` without a new file, and
the batch can still be completed with the files that arrived.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import results
from .config import get_settings
from .factory import get_blob_store
from .storage import PreconditionFailed

UPLOAD_IDLE_MINUTES = 10
MAX_NAME = 80


class BatchNotFound(KeyError):
    pass


def _blob(batch_id: str) -> str:
    if not results.valid_id(batch_id):
        raise BatchNotFound(batch_id)
    return f"batches/{batch_id}.json"


def default_name(created: datetime | None = None, files: int = 0) -> str:
    from zoneinfo import ZoneInfo

    when = (created or datetime.now(timezone.utc)).astimezone(ZoneInfo(get_settings().display_time_zone))
    return f"Upload of {when.strftime('%d %b %Y, %H:%M')}" + (f" ({files} files)" if files else "")


def clean_name(name: str) -> str:
    return " ".join((name or "").split())[:MAX_NAME]


def create(batch_id: str, *, name: str, expected: int, owner: str, owner_role: str, model_id: str,
           selection: list[str], include_images: bool) -> dict:
    s = get_settings()
    record = {"id": batch_id, "name": clean_name(name) or default_name(files=expected), "expected": int(expected),
              "uploading": True, "created_at": results.now_iso(), "upload_finished_at": None,
              "owner": owner, "owner_role": owner_role, "model_id": model_id, "selection": selection,
              "include_images": include_images}
    get_blob_store().put_json(s.container_results, _blob(batch_id), record, if_none_match=True)
    return record


def get(batch_id: str) -> dict:
    s = get_settings()
    record = get_blob_store().get_json_or_none(s.container_results, _blob(batch_id))
    if record is None:
        raise BatchNotFound(batch_id)
    return record


def update(batch_id: str, change) -> dict:
    s = get_settings()
    store = get_blob_store()
    for _ in range(10):
        try:
            record, etag = store.get_json_with_etag(s.container_results, _blob(batch_id))
        except FileNotFoundError:
            raise BatchNotFound(batch_id) from None
        change(record)
        try:
            store.put_json(s.container_results, _blob(batch_id), record, if_match=etag)
            return record
        except PreconditionFailed:
            continue
    raise RuntimeError(f"Could not update batch {batch_id}")


def finish_upload(batch_id: str, arrived: int) -> dict:
    """The browser has sent every file it could: the batch now expects exactly the documents that arrived."""
    def change(r):
        r.update(uploading=False, expected=int(arrived), upload_finished_at=results.now_iso())

    return update(batch_id, change)


def rename(batch_id: str, name: str) -> dict:
    name = clean_name(name)
    if not name:
        raise ValueError("A batch needs a name")
    return update(batch_id, lambda r: r.__setitem__("name", name))


def summarise(record: dict, rows: list[dict], now: datetime | None = None) -> dict:
    """Progress of one batch from its record and its documents' History rows."""
    now = now or datetime.now(timezone.utc)
    arrived = len(rows)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("queued", "processing", "done", "failed")}
    last_file = max((datetime.fromisoformat(r["created_at"]) for r in rows), default=None)
    started = datetime.fromisoformat(record["created_at"])
    idle_since = last_file or started
    uploading = bool(record.get("uploading")) and now - idle_since < timedelta(minutes=UPLOAD_IDLE_MINUTES)
    interrupted = bool(record.get("uploading")) and not uploading
    expected = arrived if interrupted else max(int(record.get("expected") or 0), arrived)
    running = counts["queued"] + counts["processing"]
    finished = counts["done"] + counts["failed"]
    complete = not uploading and running == 0 and arrived > 0 and finished == expected
    status = "uploading" if uploading else ("running" if running or finished < expected else "complete")
    to_review = [r for r in rows if r["status"] == "done" and r["review_count"] > 0]
    return {
        **record, "arrived": arrived, "expected": expected, "uploading_now": uploading, "interrupted": interrupted,
        "queued": counts["queued"], "processing": counts["processing"], "done": counts["done"],
        "failed": counts["failed"], "running": running, "finished": finished, "complete": complete,
        "status": status, "documents_to_review": len(to_review),
        "fields_to_review": sum(r["review_count"] for r in to_review),
        "pictures": sum(r.get("pictures", 0) for r in rows),
        "percent": round(100 * finished / max(expected, 1)),
        "last_activity": (last_file or started).isoformat(),
    }


def detail(batch_id: str) -> tuple[dict, list[dict]]:
    """(summary, documents in upload order)."""
    record = get(batch_id)
    rows = results.batch(batch_id)
    return summarise(record, rows), rows


def list_all() -> list[dict]:
    """Every batch with its progress, newest first (one listing of the results container)."""
    s = get_settings()
    store = get_blob_store()
    by_batch: dict[str, list[dict]] = {}
    for row in results.list_summaries():
        by_batch.setdefault(row["batch_id"], []).append(row)
    out = []
    for info in store.list_info(s.container_results, prefix="batches/"):
        batch_id = info.name.removeprefix("batches/").removesuffix(".json")
        record = store.get_json_or_none(s.container_results, info.name)
        if record and results.valid_id(batch_id):
            out.append(summarise(record, sorted(by_batch.get(batch_id, []), key=lambda r: r["created_at"])))
    out.sort(key=lambda b: b["created_at"], reverse=True)
    return out


def delete(batch_id: str) -> int:
    """Delete a batch and every document in it. Returns the number of documents deleted."""
    s = get_settings()
    get(batch_id)
    rows = results.batch(batch_id)
    for r in rows:
        results.delete(r["id"])
    get_blob_store().delete(s.container_results, _blob(batch_id))
    return len(rows)
