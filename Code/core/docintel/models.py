"""Shapes of the stored records (documentation and type hints; records are plain JSON dictionaries)."""

from __future__ import annotations

from typing import TypedDict

QUEUED, PROCESSING, DONE, FAILED = "queued", "processing", "done", "failed"
STATUSES = (QUEUED, PROCESSING, DONE, FAILED)
STATUS_LABELS = {QUEUED: "Queued", PROCESSING: "Processing", DONE: "Done", FAILED: "Failed"}


class JobError(TypedDict):
    code: str  # throttled | service | quota | access | model | unsupported | network | missing | internal | error
    message: str  # readable text, never document content


class Edit(TypedDict):
    value: str  # the corrected value as typed
    at: str  # ISO timestamp (UTC)
    by: str  # role of the reviewer (Admin or User)


class ResultRecord(TypedDict, total=False):
    """``results/<id>.json``. ``analysis`` is the full ``AnalyzeResult.as_dict()`` of the SDK."""

    id: str
    batch_id: str
    filename: str
    kind: str  # pdf | jpeg | png
    content_type: str
    size: int
    pages: int
    sha256: str
    model_id: str
    api_version: str
    selection: list[str]
    status: str
    error: JobError | None
    attempts: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    owner: str  # sign-in session ID of the uploader
    owner_role: str
    sample: str | None
    mock: dict | None  # set only by the local mock analyzer
    claimed_by: str | None
    claim_expires: str | None
    analysis: dict | None
    edits: dict[str, Edit]  # by field path: "InvoiceTotal" or "Items[2].Amount"
    reviewed: list[str]  # field paths marked as reviewed
    review_count: int
