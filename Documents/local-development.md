# Local Development

Local mode runs the whole app on your machine without Azure: storage is a folder and Document Intelligence is
replaced by a mock that returns the expected results of the bundled sample invoices. Jobs, review, corrections,
exports, History, presets, settings and the highlight boxes all run for real.

## Setup

Python 3.12 is recommended (the version App Service runs).

```bash
make setup     # .venv, requirements-dev.txt, Chromium for the UI tests
make run       # http://localhost:8000: choose Admin or User (no password in local mode)
```

Without `make`:

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cd Code/webapp && python manage.py runserver
```

`make seed` analyses all eight sample invoices so History has content. `make reset` deletes the local data in
`.localdata/`.

## How local mode works

| Part | Local mode | Azure |
|---|---|---|
| Storage | Folder `.localdata/storage/<container>/…`, with metadata and ETags in `.meta/` | Blob Storage |
| Document Intelligence | `MockAnalyzer`: a bundled sample (matched by SHA-256) returns its sidecar values in the SDK's own result shape (PDF pages in inches, PNG pages in pixels, rotation applied for the scanned sample); other PDFs get best-effort values from simple text rules, without boxes; other images return no fields. Each result says it is a mock. | `begin_analyze_document`, API 2024-11-30 |
| Sign-in | `AUTH_MODE=dev`: choose a role. Set `AUTH_MODE=password` and `DEMO_PASSWORD` to try the password flow | Shared password from Key Vault |
| Secrets | Built-in development secret key | Key Vault references |

Test hooks in the mock: a PDF whose text contains `DOCINTEL-MOCK-FAIL` fails as unsupported, and one with
`DOCINTEL-MOCK-THROTTLE` fails with HTTP 429 on every attempt (to see retries and the failed state).

## Useful commands

```bash
make test         # core tests (pytest) and web tests (manage.py test)
make test-ui      # Playwright UI tests and deployment script tests
make check        # bash -n, shellcheck, JSON syntax, Markdown links, content rules
make package      # build/webapp.zip with every library (as deployed)
make screenshots  # retake the README screenshots
python -m docintel analyze Data/sample_invoices/inv-03-uk-interiors.pdf --model prebuilt-invoice --fields InvoiceId,InvoiceTotal
python -m docintel models
```

## Using real Azure services from your machine

Swap one service at a time with variables in `.env` (see [`.env.example`](../.env.example)). For example, the real
Document Intelligence with local storage:

```bash
ANALYZE_BACKEND=azure
DOCINTEL_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com
# DOCINTEL_KEY=<key>   # or sign in with `az login` and give yourself Cognitive Services User on the account
```

Azure deployments disable key access to Document Intelligence; a separate development account is the easiest way
to use a key. Blob Storage works the same way with `STORAGE_BACKEND=azure` and `AZURE_STORAGE_ACCOUNT_URL`.

## Docker

`make docker-up` runs the web app with the Azurite storage emulator, so the real Blob Storage SDK code path (ETags,
metadata, conditional writes) runs against an emulator. Open http://localhost:8000. `make docker-down` stops it.

## Sample invoices

`Data/sample_invoices/generate.py` regenerates the eight invented invoices and their sidecars (see the
[folder README](../Data/sample_invoices/README.md)).

## Code map

| Path | Contents |
|---|---|
| `Code/core/docintel/config.py` | Settings from environment variables |
| `storage.py` | Local folder and Blob Storage, with metadata, ETags and conditional writes |
| `catalog.py` | Field catalog and presets (built-in and Admin changes) |
| `pages.py` | Upload checks, page counting, daily page budget |
| `analyze.py` | Azure client, error mapping, mock analyzer |
| `samples.py` | Sample sidecars, polygon mapping for PDF and PNG variants |
| `jobs.py` | Submission, claims, worker threads, retries, restart recovery |
| `results.py` | Result records, History rows, deletion |
| `normalize.py` | The review view: selected fields, normalised values, review flags, corrections |
| `export.py` | JSON, CSV, XLSX |
| `settings_store.py` | Settings Admins change at runtime |
| `cli.py` | `python -m docintel analyze / seed / reset / models` |
| `Code/webapp/accounts` | Sign-in, roles, lock-out |
| `Code/webapp/portal` | Pages, htmx partials, JSON API, security headers |
| `Code/webapp/templates`, `static` | Templates, CSS, JavaScript, vendored htmx and pdf.js |
