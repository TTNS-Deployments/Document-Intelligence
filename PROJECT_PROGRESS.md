# Project progress and context

Read this first when continuing work in a new session. Keep it updated after each piece of work.
Last updated: 2026-10-25 (all ten build stages done and pushed; first Azure deployment pending, run by the user).

## What this is

Document Intelligence: upload an invoice (or receipt, ID document), choose which fields to capture, and get
those fields back with a confidence score for each, using Azure AI Document Intelligence **pre-built models only**
(API version 2024-11-30). A Django web app on Azure App Service does all the work (upload checks, analysis jobs,
review with highlights, correction, exports, History). Storage is Blob Storage, secrets are in Key Vault, and every
service is reached with the web app's managed identity.

Repository: https://github.com/TTNS-Deployments/Document-Intelligence, branch `main`.
Work happens in a GitHub Codespace, which **cannot sign in to Azure**. Deployment runs from Azure Cloud Shell.

## Stages

| # | Stage | Status |
|---|---|---|
| 1 | Remove legacy files, scaffolding, this file | Done |
| 2 | Config catalogs (`Config/fields.yaml`, `presets.yaml`, `settings.yaml`) | Done |
| 3 | Core package `Code/core/docintel` + pytest | Done (100 tests incl. deployment consistency) |
| 4 | Sample invoices (`Data/sample_invoices`) | Done (8 invoices, PDF and PNG, sidecars) |
| 5 | Web app (`Code/webapp`): sign-in, Extract, Review, History, Settings | Done (40 tests) |
| 6 | ARM template, parameter files, portal form | Done (Bicep decompile + build pass; **not deployed**) |
| 7 | Deployment scripts + fake-`az` tests | Done (22 script tests + real package build) |
| 8 | Playwright UI tests, screenshots, architecture diagram | Done (34 UI tests) |
| 9 | Documentation and README | Done |
| 10 | CI, test report, final checks, push | Done |

## Decisions

- Layout and deployment approach follow the agreed project structure (`Code/core`, `Code/webapp`, `Config`, `Data`,
  `Deployment`, `Documents`, `qa`). Python 3.12, Django 5.2, no relational database, signed-cookie sessions.
- Document Intelligence SDK `azure-ai-documentintelligence` 1.0.x, API `2024-11-30`, `DefaultAzureCredential`;
  key access to the account is disabled by the template (`disableLocalAuth`).
- Field names checked against Microsoft's published 2024-11-30 schemas
  (`Azure-Samples/document-intelligence-code-samples/schema/2024-11-30-ga/*.md`) on 2026-10-25.
- **`prebuilt-businessCard` is deprecated from API v4.0 (2024-11-30).** It stays in the catalog and the dropdown,
  shown as unavailable; jobs for it are refused. Re-enabling it needs the older v3.1 SDK (out of scope).
- **`CurrencyCode` is not a standalone invoice field in 2024-11-30.** The catalog lists it as *derived*: taken from
  the currency code of `InvoiceTotal`, `AmountDue`, `SubTotal` or `TotalTax` (with that field's confidence and box).
- Front-end libraries vendored: htmx 2.0.10, pdf.js 5.4.624 (plus standard fonts); axe-core 4.11.0 under
  `qa/vendor` for tests only. CSP: scripts from `/static` only, no inline scripts. htmx removes `<script>` tags
  from swapped content, so per-document data travels in `data-*` attributes.
- Review boxes: an SVG overlay whose `viewBox` is the page size from the result (inches for PDFs, pixels for
  images), so polygons are drawn unchanged.
- Jobs: in-process queue, 2 worker threads, claim by conditional write (ETag) of the record from `queued` to
  `processing`, retries for 429/5xx/network with back-off, recovery on the first request after a start.
- Pages are counted against the daily budget when a job is accepted (before any call) and again on a retry.
- Ownership: each sign-in gets a random session ID that owns its uploads. Users delete their own; Admins any.
  History shows all documents to everyone signed in.
- Lifecycle policy deletes `uploads/` and `results/` blobs `retentionDays` after **creation** (edits do not extend
  retention). Blob soft delete keeps them 7 more days.
- Demo: the web app is a separate app on the shared plan `ccai-demo-gqausd-web-plan` (looked up by `deploy.sh`,
  never modified), gunicorn 1 worker × 4 threads. Document Intelligence S0 in `centralindia`.
- MIT licence (as requested), copyright Tata Tele NXTGEN Solutions Limited.
- Sample data is invented; tax IDs, IBANs and bank codes are deliberately fake-looking (`TEST`, zeros).

## Verified locally only

Core (100), web (40), UI (34, Playwright headless Chromium, run twice), deployment scripts against a fake `az`
(22), the real `package.sh --vendor` build started under gunicorn with Python 3.12, `shellcheck`, `bash -n`, JSON
and Markdown link checks, Bicep decompile + build. See `qa/TEST_REPORT.md`.

## Untested on Azure

Everything that needs Azure: real analyses, managed identity and role assignments, Key Vault references, the ARM
deployment itself, run-from-package on App Service, lifecycle policy, private networking (prod), App Insights,
the Deploy to Azure button, the GitHub *Deploy* workflow. Docker/Azurite was not run in the Codespace. dev and prod
parameter files are untested.

## Open items

- First demo deployment and the checks in `qa/TEST_REPORT.md` ("What to verify after the first Azure deployment").
- Prod code deployment from inside the network (documented, not scripted or tested).
- Roadmap: Entra ID sign-in with real roles, custom models, more pre-built models, an integration API.

## Next steps for the user (Azure Cloud Shell, Bash)

1. Check the provider and Document Intelligence availability:

   ```bash
   az provider register -n Microsoft.CognitiveServices --wait
   az cognitiveservices account list-skus --kind FormRecognizer --location centralindia -o table
   az cognitiveservices account list --query "[?kind=='FormRecognizer'].{n:name,sku:sku.name,rg:resourceGroup,loc:location}" -o table
   ```

   `S0` must be listed for Central India. The last command shows whether an F0 account already exists (the default
   is S0 anyway). If the region lacks the 2024-11-30 pre-built models, change only `docIntelLocation` in
   `Deployment/ARM/parameters/demo.parameters.json`.

2. Deploy (choose your own password, at least 8 characters):

   ```bash
   cd ~ && git clone https://github.com/TTNS-Deployments/Document-Intelligence.git ; cd ~/Document-Intelligence && git pull && Deployment/scripts/deploy.sh -e demo --param demoPassword='<password>'
   ```

3. Open the printed URL, sign in as Admin, run **Try a sample**, then upload a real invoice. If anything fails,
   send the script output and the App Service *Log stream* text.
