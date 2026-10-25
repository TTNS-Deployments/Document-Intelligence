# Project progress and context

Read this first when continuing work in a new session. Keep it updated after each piece of work.
Last updated: 2026-10-25 (stage 5: web app).

## What this is

Document Intelligence: upload an invoice (or receipt, ID document), choose which fields to capture, and get
those fields back with a confidence score for each, using Azure AI Document Intelligence **pre-built models only**
(API version 2024-11-30). A Django web app on Azure App Service does all the work (upload, validation, analysis
jobs, review with highlights, correction, exports, history). Storage is Blob Storage, secrets are in Key Vault,
and every service is reached with the web app's managed identity.

Repository: https://github.com/TTNS-Deployments/Document-Intelligence, branch `main`.
Work happens in a GitHub Codespace, which **cannot sign in to Azure**. Deployment runs from Azure Cloud Shell.

## Stages

| # | Stage | Status |
|---|---|---|
| 1 | Remove legacy files, scaffolding, this file | Done |
| 2 | Config catalogs (`Config/fields.yaml`, `presets.yaml`, `settings.yaml`) | Done |
| 3 | Core package `Code/core/docintel` + pytest | Done (86 tests) |
| 4 | Sample invoices (`Data/sample_invoices`) | Done (8 invoices) |
| 5 | Web app (`Code/webapp`): sign-in, Extract, Review, History, Settings | Done (40 tests) |
| 6 | ARM template, parameter files, portal form | Not started |
| 7 | Deployment scripts + fake-`az` tests | Not started |
| 8 | Playwright UI tests, screenshots, architecture diagram | Not started |
| 9 | Documentation and README | Not started |
| 10 | CI, final checks, push | Not started |

## Decisions

- Layout, conventions and deployment approach follow the agreed project structure (`Code/core`, `Code/webapp`,
  `Config`, `Data`, `Deployment`, `Documents`, `qa`).
- Python 3.12, Django 5.2, no relational database (`DATABASES = {}`), signed-cookie sessions.
- Document Intelligence SDK `azure-ai-documentintelligence` 1.0.x, API version `2024-11-30`.
- Field names checked against Microsoft's published 2024-11-30 schemas
  (`Azure-Samples/document-intelligence-code-samples/schema/2024-11-30-ga/*.md`) on 2026-10-25.
- **`prebuilt-businessCard` is deprecated from API v4.0 (2024-11-30)** (Microsoft Learn: "Starting with Document
  Intelligence v4.0, and going forward, the business card model is deprecated"). It stays in the catalog, so the
  dropdown lists it, but it is shown as unavailable and the app refuses jobs for it. Re-enabling it would need the
  older v3.1 SDK (`azure-ai-formrecognizer`), which is out of scope.
- **`CurrencyCode` is not a standalone invoice field in 2024-11-30**: each currency value carries its own
  `currencyCode`. The catalog lists `CurrencyCode` as a *derived* field: the app uses a top-level `CurrencyCode`
  field if the service ever returns one, otherwise it takes the code from `InvoiceTotal`, `AmountDue`,
  `SubTotal` or `TotalTax` (with that field's confidence and box) and labels it "derived".

- Front-end libraries are vendored: htmx 2.0.10, pdf.js 5.4.624 (with its standard fonts). axe-core 4.11.0 is
  vendored under `qa/vendor` for the accessibility check only. No CDN at runtime; the CSP allows scripts from
  `/static` only, and templates contain no inline scripts.
- Review boxes: an SVG overlay whose `viewBox` is the page size Document Intelligence reports (inches for PDFs,
  pixels for images), so result polygons are drawn unchanged and scale with the rendered page.
- Ownership: each sign-in gets a random session ID that owns the documents uploaded in that session. Users can
  delete their own documents; Admins can delete any. History shows all documents to everyone signed in.
- Pages are counted against the daily budget when a job is accepted (before any call), and again on a retry.
- htmx removes `<script>` tags from swapped content (`allowScriptTags: false`), so per-document data travels in
  `data-*` attributes.

## Next steps

Continue with stage 6 (ARM template).
