# Technical Specification

How Document Intelligence processes a document, what it stores and how results are normalised. Code references are
to `Code/core/docintel` unless stated otherwise.

## 1. Accepted files and limits (`pages.py`)

| Check | Rule | Message when refused |
|---|---|---|
| Extension | `.pdf`, `.jpg`, `.jpeg`, `.png` | "only PDF, JPEG and PNG files are accepted" |
| File signature | PDF `%PDF-`, JPEG `FF D8 FF`, PNG `89 50 4E 47 0D 0A 1A 0A`; must match the extension | "the content does not match the file type" |
| Size | ≤ `MAX_UPLOAD_MB` (default 10) | "the file is N MB; the limit is 10 MB" |
| Empty | > 0 bytes | "the file is empty" |
| PDF pages | 1 ≤ pages ≤ `MAX_PAGES` (default 10), counted with `pypdf` | "the PDF has N pages; the limit is 10 per file" |
| PDF encryption | not password-protected | "the PDF is password-protected" |
| Damaged PDF | `pypdf` can read it | "the PDF could not be read" |
| Image size | 50 to 10,000 pixels per side (read from the PNG/JPEG header, no image library) | "the image is W x H pixels…" |
| Files per request | ≤ `MAX_FILES_PER_UPLOAD` (default 10); the browser sends a batch one file per request | "Upload at most 10 files at a time" |
| Files per batch | ≤ `MAX_BATCH_FILES` (default 100) | "A batch holds at most 100 documents" |
| Daily budget | pages used today + pages of this file ≤ `DAILY_PAGE_LIMIT` | "The daily page limit is reached…" |

File names are sanitised (`sanitize_filename`): the path is dropped, control and bidirectional characters removed,
characters other than letters, digits, space, `-`, `.`, `(`, `)` replaced by `_`, the extension lower-cased, the
name cut to 100 characters.

Checks run in this order and **before** anything is stored or sent to Azure. Pages are counted against the daily
budget when a job is accepted (that is, before the analysis call) and again when a failed job is retried. The
budget blob `config/usage/<YYYY-MM-DD>.json` (date in `DISPLAY_TIME_ZONE`) is updated with an ETag condition and
retried on conflict, so concurrent uploads never exceed the limit.

## 2. Processing (`jobs.py`, `analyze.py`)

```
upload ──► checks ──► page budget ──► uploads/<id>/<name> + results/<id>.json (queued) ──► in-process queue
   worker thread: claim (queued → processing, ETag condition) ──► begin_analyze_document ──► done | failed
   browser: htmx polls the batch list and the review panel every 1.5 s until done or failed
```

| Status | Meaning |
|---|---|
| `queued` | Accepted and waiting for one of the 2 worker threads |
| `processing` | Claimed by a worker (`claimed_by` = `<instance>:<pid>:<random>`, `claim_expires` = now + 15 min) |
| `done` | The full analysis is stored |
| `failed` | `error.code` and a readable `error.message`; the user can retry |

* **Include images** (`include_images`, per document, off by default):
  * **off** and a PDF: `pages.strip_pdf_images` removes embedded images (XObject and inline images) from every page
    that has a text layer, so the model sees typed text only; pages without a text layer (scans) are left as they
    are. The record's `image_handling` says `{"mode": "text_only", "images_removed", "text_pages", "scanned_pages"}`.
  * **off** and a JPEG or PNG: nothing can be separated (`{"mode": "picture_file"}`).
  * **on**: the original is analysed, then a second analysis with `prebuilt-layout` and `output=figures` returns the
    detected pictures; each is downloaded with `get_analyze_result_figure` (PNG) and stored as
    `uploads/<id>/figures/<page>.<n>.png` (at most 20). Pages are counted twice. If only the picture step fails, the
    document is still `done` and `figures_error` explains why. Microsoft documents figures and `output=figures` as a
    Layout model feature; the invoice, receipt and ID models do not return pictures.
* **Batches:** every upload request may carry `batch=<id>` to add to an existing batch (the browser sends large
  batches one file per request). `batch_id` is stored on each record and in its blob metadata.
* **Client:** `DocumentIntelligenceClient(endpoint, DefaultAzureCredential(), api_version="2024-11-30")`,
  `begin_analyze_document(model_id, AnalyzeDocumentRequest(bytes_source=...))`, then `poller.result().as_dict()`.
  The SDK retries twice itself; the job retries transient errors (HTTP 429, 5xx, network) up to
  `ANALYZE_MAX_ATTEMPTS` (3) times with back-off of 2 s, 4 s, ….
* **Claims:** a job runs only after a conditional write of its record from `queued` to `processing`. A second
  process reading the same record loses the race. A worker writes its result only if it still owns the claim.
* **Restart recovery:** on the first request after a start, `queued` jobs are queued again, and `processing` jobs are
  queued again when their process is gone (same instance, different process) or the claim has expired.
* **Errors shown to users** (`map_http_error`):

| Code | Cause | Message (shortened) |
|---|---|---|
| `throttled` | HTTP 429 | Document Intelligence is busy… wait a minute and retry |
| `service` | HTTP 5xx | temporary problem… retry later |
| `quota` | HTTP 403 with a quota error | the quota is used up (F0: 500 pages a month)… |
| `access` | HTTP 401/403, credential failure | the managed identity lacks Cognitive Services User, or network rules block it |
| `model` | HTTP 404 / ModelNotFound | the model is not available in this region (`docIntelLocation`) |
| `unsupported` | HTTP 400 InvalidContent, UnsupportedContent… | the file is damaged, protected, too small or too large |
| `network` | connection errors | could not reach Document Intelligence |
| `internal` | anything else | unexpected error; retry |

* **Logs** contain the job ID, model, page count, attempts, duration and status only.

## 3. Result record (`results/<id>.json`)

```json
{
  "id": "3f9a1c0d2b7e4a51", "batch_id": "3f9a1c0d2b7e4a51",
  "filename": "invoice-0142.pdf", "kind": "pdf", "content_type": "application/pdf", "size": 45263, "pages": 1,
  "sha256": "…", "model_id": "prebuilt-invoice", "api_version": "2024-11-30",
  "selection": ["VendorName", "InvoiceId", "InvoiceDate", "InvoiceTotal", "Items"],
  "status": "done", "error": null, "attempts": 1,
  "created_at": "2026-10-25T10:00:00.000+00:00", "started_at": "…", "finished_at": "…", "duration_ms": 1830,
  "owner": "<sign-in session ID>", "owner_role": "User", "sample": null, "mock": null,
  "claimed_by": null, "claim_expires": null,
  "analysis": { "apiVersion": "2024-11-30", "modelId": "prebuilt-invoice", "pages": [ … ], "documents": [ … ] },
  "edits": { "InvoiceId": { "value": "INV-0143", "at": "2026-10-25T10:05:00+00:00", "by": "User" } },
  "reviewed": ["InvoiceId", "Items"],
  "review_count": 1
}
```

`analysis` is the SDK's `AnalyzeResult.as_dict()`: every field the model returned, not only the selected ones, so
the selection can change later without a second analysis. Blob metadata on the record (status, percent-encoded file
name, model, pages, review count, number of fields, created/finished time, owner, batch, sample, edited count,
error) is what History lists.

## 4. Normalisation (`normalize.py`)

For each **selected** field, in catalog order:

| SDK type | Normalised value | Shown as |
|---|---|---|
| `string` | `valueString` | as is |
| `date` | `valueDate` (ISO `YYYY-MM-DD`) | ISO; the printed text is kept in `content` |
| `time` | `valueTime` | `HH:MM:SS` |
| `number`, `integer` | `valueNumber`, `valueInteger` | number |
| `currency` | `valueCurrency.amount` plus ISO code (`currencyCode`, else an unambiguous symbol: ₹ INR, € EUR, £ GBP, ¥ JPY, …; `$` alone gives no code) | `1,234.50 INR` |
| `address` | the printed lines joined with commas (from `content`; from the address parts if there is no text) | one line |
| `phoneNumber`, `countryRegion`, `boolean` | the typed value | as is |
| `array` of objects | a table: one row per item, one column per sub-field found, each cell with its own value, confidence and box | table |
| `array` of values | the values joined with `; ` | one line |
| `object` | its parts | one line |

Each value carries `content` (the raw text as printed), `confidence` (0 to 1), the page number and the bounding
polygon(s) of `boundingRegions`. Polygons stay in the page's own unit (inches for PDFs, pixels for images); the page
`width`, `height` and `unit` come with the result.

* **Not found:** a selected field the model did not return (or returned without a value and without text) is kept
  with `found: false` and shown as "Not found". It is never dropped.
* **Review flag:** `confidence < review_threshold` (default 0.80) and not reviewed and not corrected. A value exactly
  at the threshold is not flagged. A table counts as one field and is flagged when any cell is.
* **Summary:** "N of M fields need review", where M is the number of selected fields (tables count once).
* **Corrections:** `edits[path]` (path `InvoiceTotal` or `Items[2].Amount`) replaces the shown and exported value;
  the model value is kept and shown as "Model value". A corrected field counts as reviewed. Numbers typed for
  numeric fields are exported as numbers.
* **`CurrencyCode`:** API 2024-11-30 has no separate invoice currency field. The app shows a *derived* field from the
  first of `InvoiceTotal`, `AmountDue`, `SubTotal`, `TotalTax` that has a currency code, with that field's
  confidence and box.
* **Several documents in one file:** the first is shown, with a note.

## 5. Storage layout and retention

| Container | Content | Deleted |
|---|---|---|
| `uploads` | `<id>/<file name>`: the original | by the lifecycle policy after `retentionDays` (days since creation), or when the user deletes the result |
| `results` | `<id>.json`: the record | same |
| `config` | `presets.json` (Admin presets), `settings.json` (Admin settings), `usage/<date>.json` (page budget) | never (small) |
| `code-packages` | `webapp-<timestamp>.zip`: the deployed app (newest 3 kept) | by `deploy_code_arm.sh` |

Blob soft delete keeps deleted blobs for 7 days. Retention is shown on the Extract and History pages from
`RETENTION_DAYS`, which the template sets from the same `retentionDays` parameter as the policy.

## 6. Exports (`export.py`)

| Format | Content |
|---|---|
| JSON | One document: summary, the selected fields (value, text, raw text, currency, confidence, review flag, edited flag, model value, boxes), tables, edits and the full analysis. Several documents: `{"documents": [...]}` |
| CSV | One row per document: file, ID, model, pages, status, then per selected field a value column and a confidence column, the number of line items, the number of fields needing review, the edited fields, the number of pictures and any problem. UTF-8 with BOM |
| XLSX | Sheet **Documents** (one row per document, with *Status* and *Problem*), sheet **Line items** (one row per table row, with the document name), sheet **Details** (every value with raw text, confidence, review flag, edited flag, model value, page), sheet **Pictures** (when pictures were extracted: document, picture, page, caption, file name in the pictures ZIP) |
| Pictures ZIP | Every extracted picture as `<document>-<id>/picture-<page>.<n>.png` |

A **batch export** (`?batch=<id>`) lists every document of the upload, including failed ones with their reason; the
browser offers it only when every document has finished. A selection from History (`?ids=`) exports finished
documents only.

Corrected values are exported, with columns that say what was edited. Text that starts with `=`, `+`, `-` or `@`
is prefixed with `'` so spreadsheets do not run it as a formula. Selections may differ between documents: columns
are the union, and cells of fields not selected for a document are empty (not "Not found").

## 7. Web app API (`Code/webapp/portal`)

All routes need a signed-in session; POST routes need the CSRF token. Admin-only routes are marked.

| Method and path | Purpose |
|---|---|
| `GET /` | Extract page |
| `GET /documents/<id>` | Review page of one document |
| `GET /history` | History (filters `q`, `model`, `status`, `review=1`, `mine=1`, `sort`) |
| `GET, POST /settings` | Settings (Admin) |
| `POST /api/documents` | Upload: `files` (repeatable), `model`, `fields` (repeatable), `include_images` (`1`/`0`), optional `batch` to add to a batch. Returns `{batch_id, accepted, rejected}` |
| `POST /api/samples/<sample id>` | Run a bundled sample (optional `fields`, `variant`) |
| `GET /api/documents/<id>` | Status, error and normalised view |
| `GET /api/documents/<id>/file` | The original (streamed) |
| `GET /api/documents/<id>/figures/<page>.<n>` | One extracted picture (PNG; `?download=1` to save it) |
| `GET /api/documents/<id>/pictures.zip` | Every picture of one document |
| `POST /api/documents/<id>/retry` | Queue a failed document again |
| `POST /api/documents/<id>/delete` | Delete the result and its original now (owner or Admin) |
| `GET /api/documents/<id>/export.{json,csv,xlsx}` | Export one document |
| `GET /api/export.{json,csv,xlsx}?batch=<id>` | One file for a whole upload batch (failed documents listed) |
| `GET /api/export.{json,csv,xlsx}?ids=a,b` | Export several finished documents |
| `GET /api/export-pictures.zip?batch=<id>` (or `ids=`) | Every picture of a batch or a selection |
| `GET /api/catalog` | Models, field groups and presets |
| `POST /api/presets/<model>` | Create or update a preset (Admin) |
| `POST /api/presets/<model>/<preset>/delete` | Delete a preset (Admin) |
| `POST /documents/<id>/selection`, `/edit`, `/reviewed` | htmx: change fields, correct a value, mark reviewed |
| `GET /partials/batch?batch=<id>&expected=<n>`, `/partials/review/<id>` | htmx: batch progress (complete only when `n` documents exist and all have finished), review panel |
| `GET /healthz` | Health check (no sign-in) |

## 8. Front end

Server-rendered Django templates with htmx 2.0.10 and pdf.js 5.4.624, both vendored under `static/vendor` (no CDN),
plus small vanilla scripts. The Content-Security-Policy allows scripts only from the app and no inline scripts.
Highlight boxes are an SVG laid over the rendered page whose `viewBox` is the page size from the result, so a
polygon is drawn unchanged and scales with zoom. Light and dark themes follow the system, with a toggle stored in
the browser. A personal field selection can be remembered per model in the browser (`localStorage`).

## 9. Testing

| Suite | Command | Covers |
|---|---|---|
| Core | `pytest Code/core` | catalog, presets, normalisation from SDK-built results, selection, review flags, edits, page counting, budget with concurrency, jobs (claims, retries, recovery), exports, storage, deployment consistency |
| Web | `cd Code/webapp && python manage.py test` | sign-in and lock-out, role protection of every route, upload validation, results, History, edits, deletion, exports, CSRF, static files |
| UI and scripts | `pytest qa/tests` | Playwright in headless Chromium against local mode; deployment scripts against a fake `az` |

Results and gaps: [qa/TEST_REPORT.md](../qa/TEST_REPORT.md).
