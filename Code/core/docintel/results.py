"""Result records: one JSON blob per document in the ``results`` container, the original in ``uploads``.

There is no database. The History page lists the ``results`` container and reads each blob's metadata (status,
file name, model, pages, review count, time, owner), so it never downloads the full records.

Layout::

    uploads/<id>/<file name>     the original file (deleted with the result, and by the lifecycle policy)
    results/<id>.json            the record: status, selection, full analysis, edits
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote, unquote

from .config import get_settings
from .factory import get_blob_store
from .storage import PreconditionFailed

from .models import STATUSES  # noqa: F401 - re-exported
_ID = re.compile(r"[a-f0-9]{16}")


class NotFound(KeyError):
    pass


def new_id() -> str:
    return secrets.token_hex(8)


def valid_id(doc_id: str) -> bool:
    return bool(doc_id) and bool(_ID.fullmatch(doc_id))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _result_blob(doc_id: str) -> str:
    if not valid_id(doc_id):
        raise NotFound(doc_id)
    return f"{doc_id}.json"


def upload_blob(record: dict) -> str:
    return f"{record['id']}/{record['filename']}"


def new_record(*, doc_id: str, filename: str, kind: str, content_type: str, size: int, pages: int, sha256: str,
               model_id: str, api_version: str, selection: list[str], owner: str, owner_role: str,
               batch_id: str = "", sample: str | None = None, include_images: bool = False) -> dict:
    return {
        "id": doc_id, "batch_id": batch_id or doc_id, "filename": filename, "kind": kind,
        "content_type": content_type, "size": size, "pages": pages, "sha256": sha256,
        "model_id": model_id, "api_version": api_version, "selection": selection,
        "status": "queued", "error": None, "attempts": 0,
        "created_at": now_iso(), "started_at": None, "finished_at": None, "duration_ms": None,
        "owner": owner, "owner_role": owner_role, "sample": sample, "mock": None,
        "include_images": include_images, "image_handling": None, "figures": [], "figures_error": None,
        "claimed_by": None, "claim_expires": None,
        "analysis": None, "edits": {}, "reviewed": [], "review_count": 0,
    }


def _metadata(record: dict) -> dict:
    """Blob metadata for listing. Values must be ASCII, so text is percent-encoded."""
    from . import normalize, settings_store

    threshold = settings_store.get_runtime_settings()["review_threshold"]
    record["review_count"] = normalize.review_count(record, threshold) if record["status"] == "done" else 0
    return {
        "status": record["status"],
        "filename": quote(record["filename"], safe=""),
        "model": record["model_id"],
        "pages": str(record.get("pages") or 0),
        "review": str(record["review_count"]),
        "fields": str(len(record.get("selection") or [])),
        "created": record["created_at"],
        "finished": record.get("finished_at") or "",
        "owner": record.get("owner") or "",
        "batch": record.get("batch_id") or "",
        "sample": record.get("sample") or "",
        "edited": str(len(record.get("edits") or {})),
        "error": quote(((record.get("error") or {}).get("message") or "")[:300], safe=""),
        "images": "1" if record.get("include_images") else "0",
        "pictures": str(len(record.get("figures") or [])),
    }


def create(record: dict, data: bytes) -> None:
    s = get_settings()
    store = get_blob_store()
    store.put_bytes(s.container_uploads, upload_blob(record), data, record["content_type"],
                    metadata={"doc": record["id"]})
    store.put_json(s.container_results, _result_blob(record["id"]), record, metadata=_metadata(record),
                   if_none_match=True)


def get_with_etag(doc_id: str) -> tuple[dict, str]:
    s = get_settings()
    try:
        return get_blob_store().get_json_with_etag(s.container_results, _result_blob(doc_id))
    except FileNotFoundError:
        raise NotFound(doc_id) from None


def get(doc_id: str) -> dict:
    return get_with_etag(doc_id)[0]


def save(record: dict, etag: str | None = None) -> str:
    """Write a record (conditionally when ``etag`` is given; raises PreconditionFailed if it changed)."""
    s = get_settings()
    return get_blob_store().put_json(s.container_results, _result_blob(record["id"]), record,
                                     metadata=_metadata(record), if_match=etag)


def update(doc_id: str, change) -> dict:
    """Read-modify-write with optimistic concurrency. ``change(record)`` edits the record in place."""
    for _ in range(10):
        record, etag = get_with_etag(doc_id)
        change(record)
        try:
            save(record, etag)
            return record
        except PreconditionFailed:
            continue
    raise RuntimeError(f"Could not update {doc_id} (too many concurrent changes)")


_FIGURE_ID = re.compile(r"\d{1,4}\.\d{1,4}")


def figure_blob(record: dict, figure_id: str) -> str:
    if not _FIGURE_ID.fullmatch(figure_id or ""):
        raise NotFound(figure_id)
    return f"{record['id']}/figures/{figure_id}.png"


def save_figure(record: dict, figure: dict, index: int) -> dict:
    """Store one extracted picture next to the original (same retention and deletion) and describe it.

    Picture IDs are ``<page>.<n>`` as the service returns them; anything else is replaced by ``<page>.<index>``.
    """
    s = get_settings()
    figure_id = str(figure.get("id"))
    if not _FIGURE_ID.fullmatch(figure_id):
        figure_id = f"{int(figure.get('page') or 1)}.{index}"
    get_blob_store().put_bytes(s.container_uploads, figure_blob(record, figure_id), figure["png"], "image/png",
                               metadata={"doc": record["id"]})
    return {"id": figure_id, "page": figure.get("page", 1), "polygon": figure.get("polygon") or [],
            "caption": figure.get("caption") or "", "size": len(figure["png"])}


def read_figure(record: dict, figure_id: str) -> bytes:
    s = get_settings()
    try:
        return get_blob_store().get_bytes(s.container_uploads, figure_blob(record, figure_id))
    except FileNotFoundError:
        raise NotFound(figure_id) from None


def read_original(record: dict) -> bytes:
    s = get_settings()
    try:
        return get_blob_store().get_bytes(s.container_uploads, upload_blob(record))
    except FileNotFoundError:
        raise NotFound(record["id"]) from None


def iter_original(record: dict):
    s = get_settings()
    return get_blob_store().iter_chunks(s.container_uploads, upload_blob(record))


def delete(doc_id: str) -> bool:
    """Delete the result and its original now (not waiting for the retention policy)."""
    s = get_settings()
    store = get_blob_store()
    existed = store.delete(s.container_results, _result_blob(doc_id))
    for name in store.list(s.container_uploads, prefix=f"{doc_id}/"):
        store.delete(s.container_uploads, name)
    return existed


def _row(info) -> dict:
    m = info.metadata
    return {
        "id": info.name[:-5],
        "status": m.get("status", "queued"),
        "filename": unquote(m.get("filename", "")) or info.name,
        "model_id": m.get("model", ""),
        "pages": int(m.get("pages") or 0),
        "review_count": int(m.get("review") or 0),
        "fields": int(m.get("fields") or 0),
        "created_at": m.get("created") or info.created.isoformat(),
        "finished_at": m.get("finished") or None,
        "owner": m.get("owner", ""),
        "batch_id": m.get("batch", ""),
        "sample": m.get("sample", ""),
        "edited": int(m.get("edited") or 0),
        "error": unquote(m.get("error", "")),
        "include_images": m.get("images") == "1",
        "pictures": int(m.get("pictures") or 0),
    }


def summary(doc_id: str) -> dict:
    """One History row, from the blob's metadata only (no download)."""
    s = get_settings()
    try:
        return _row(get_blob_store().get_info(s.container_results, _result_blob(doc_id)))
    except FileNotFoundError:
        raise NotFound(doc_id) from None


def list_summaries() -> list[dict]:
    """History rows from blob metadata, newest first."""
    s = get_settings()
    rows = [_row(info) for info in get_blob_store().list_info(s.container_results)
            if info.name.endswith(".json") and valid_id(info.name[:-5])]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


def batch(batch_id: str) -> list[dict]:
    """The documents of one upload batch, in upload order."""
    return sorted((r for r in list_summaries() if r["batch_id"] == batch_id), key=lambda r: r["created_at"])
