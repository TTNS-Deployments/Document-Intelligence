# Architecture

Document Intelligence is one Django web app on Azure App Service that does everything itself: sign-in, upload
checks, a small job queue, analysis with Azure AI Document Intelligence, review, corrections, exports and History.
There is no database, no Function app, no API Management and no gateway.

![Architecture](../imgs/architecture.svg)

## 1. Components

| Component | Azure service | Role |
|---|---|---|
| Web app | App Service (Linux, Python 3.12), gunicorn 1 worker × 4 threads | UI (Django templates, htmx, pdf.js), JSON API, upload checks, job queue with 2 worker threads, normalisation, exports |
| Document storage | Blob Storage (StorageV2) | `uploads/` originals, `results/` one JSON record per document, `config/` presets, settings and the daily page counter, `code-packages/` the deployed app |
| Extraction | Azure AI Document Intelligence (kind `FormRecognizer`), API 2024-11-30 | Pre-built models `prebuilt-invoice`, `prebuilt-receipt`, `prebuilt-idDocument`; `prebuilt-layout` extracts pictures when *Include images* is on |
| Secrets | Key Vault (RBAC) | `demo-password`, `django-secret-key`, read by the web app through Key Vault references |
| Monitoring | Application Insights, Log Analytics | Console, HTTP and app logs of the web app; availability (health check `/healthz`) |
| Identity | System-assigned managed identity of the web app | Blob Data Contributor, Cognitive Services User, Key Vault Secrets User, assigned by the template |
| Private network (prod) | VNet, private endpoints, private DNS zones | Blob, Document Intelligence and Key Vault reachable only from the VNet; the web app integrates with the VNet and sends all outbound traffic through it |

`prebuilt-businessCard` is listed in the model dropdown but disabled: Microsoft deprecated it from API version
2024-11-30 (v4.0).

## 2. Data flow

1. A signed-in user chooses a model and fields, and uploads one or more PDF, JPEG or PNG files (or runs a sample).
2. The web app checks each file **before** anything is stored or sent: extension, file signature, size, image
   dimensions, PDF page count and encryption. File names are sanitised.
3. The pages are counted against the daily page budget (a small blob updated with optimistic concurrency).
4. The original goes to `uploads/<id>/<file name>` and a `queued` record to `results/<id>.json`. The job is queued
   in the web app process.
5. A worker thread **claims** the job by rewriting the record from `queued` to `processing` with the blob's ETag as
   a condition, so two processes never run the same job.
6. With *Include images* off (the default), embedded pictures are left out of typed PDFs first, so only typed text
   is read. The worker runs `begin_analyze_document` (the SDK polls until the analysis is complete); with *Include
   images* on, a second analysis by the Layout model extracts the pictures as PNGs. Throttling (HTTP 429),
   server errors and network errors are retried with exponential back-off.
7. The full analysis (every field the model found) is stored in the record with status `done`, or the record gets
   `failed` with a readable reason.
8. The browser polls (htmx) until the job is done, then shows the review: the document with highlight boxes on the
   left, the selected fields with their confidence on the right.
9. Corrections, "reviewed" marks and selection changes are written to the record; no new analysis is needed.
10. Exports (JSON, CSV, XLSX) are built on request from the record. History lists the `results` container and reads
    each blob's metadata.
11. The storage lifecycle policy deletes uploads and results `retentionDays` after they were created.

## 3. Security

See [SECURITY.md](../SECURITY.md). In short: managed identity for every service, secrets in Key Vault, key access to
Document Intelligence disabled, a strict Content-Security-Policy, no field values in logs, automatic deletion after
the retention period, and private endpoints in prod.

The demo sign-in is a **shared password with a role choice**. It is meant for demos only; Entra ID sign-in with real
roles is a roadmap item.

## 4. Scaling and cost

| Item | Behaviour |
|---|---|
| Web app | One gunicorn worker with 4 threads, 2 analysis threads. On the shared B1 plan (1.75 GB shared with other apps) memory stays low: one file and one result per job in memory. Scale out by giving the environment its own plan (`webAppSku`, `webAppInstanceCount`); claims keep jobs from running twice across instances. |
| Document Intelligence | S0 is billed per page analysed. F0 is free but limited to 500 pages a month and the first 2 pages of each document. Throttling is retried automatically. |
| Cost guard | `DAILY_PAGE_LIMIT` (default 200 pages a day) refuses new jobs once reached; Admins can change it at runtime. |
| Storage | Small: originals and JSON records, deleted after `retentionDays`. |
| Logs | Capped by `logAnalyticsDailyQuotaGb`. |

## 5. Jobs and restarts

The queue lives in the web app process, so a restart loses its in-memory list. On the first request after a start,
the app re-queues `queued` jobs and any `processing` job whose process is gone (a restart on the same instance, or a
claim older than 15 minutes). Every job that was accepted therefore finishes, at worst once more after a restart.

## 6. Environments

| Environment | Plan | Network | Retention | Status |
|---|---|---|---|---|
| demo | Shared existing B1 plan | Public endpoints | 7 days | First deployment pending (see the deployment guide) |
| dev | Own B1 plan | Public endpoints | 30 days | Untested |
| prod | Own P0v3 plan, 2 instances | Private endpoints | 90 days | Untested; code must be deployed from inside the network |
