# Test cases

Scope: what runs without Azure. Core and web tests live next to the code; UI and deployment-script tests live in
`qa/tests` and are named after the IDs below (`test_U05_…`). Priority: C = critical, H = high, M = medium.

## Core (`pytest Code/core`, 113 tests)

| ID | Pri | Area | Covered by | Expected |
|---|---|---|---|---|
| C-01 | C | Catalog | `test_catalog.py` | 4 models load; every required invoice field exists with label, type, description; line-item sub-fields; business card listed but unavailable; unknown models and fields refused |
| C-02 | H | Presets | `test_catalog.py` | Built-in presets reference real fields, one default per model; Admin create, edit, hide and delete through `config/presets.json` with optimistic concurrency |
| C-03 | C | Normalisation | `test_normalize.py` | Results built with the SDK's model classes: strings, ISO dates with printed text kept, currency with ISO code or symbol, one-line addresses, tables with per-cell confidence and boxes, pages and units (inch and pixel) |
| C-04 | C | Not found and review flags | `test_normalize.py` | Missing selected fields kept as Not found; flag below the threshold and not at it; tables count once; reviewed and edited fields clear the flag |
| C-05 | H | Corrections | `test_normalize.py` | Edited value replaces the shown value, model value kept, numbers parsed, cell edits |
| C-06 | C | Upload checks | `test_pages.py` | Extensions, magic bytes, size, empty, page count, encrypted and damaged PDFs, image dimensions, sanitised names |
| C-07 | C | Daily budget | `test_pages.py` | Counts and refuses; 30 concurrent reservations never exceed the limit |
| C-08 | C | Job state machine | `test_jobs.py` | queued → processing → done / failed; exclusive and lost-race claims; retries with exponential back-off; permanent errors not retried; unexpected exceptions never leave `processing`; restart recovery; take-over and deletion during processing; worker pool runs a batch |
| C-09 | C | Exports | `test_export.py` | XLSX opened with openpyxl (sheets, columns, values, edited flags, Not found, formula neutralised); CSV; JSON with the full analysis |
| C-10 | H | Storage and results | `test_results_and_storage.py` | Local ETags and conditions, metadata listing, History rows, deletion of result and original, invalid IDs, concurrent update retry, settings precedence, Key Vault reference treated as empty |
| C-11 | H | Analyzer | `test_analyze_and_samples.py` | Azure errors mapped to readable messages; Azure client builds `AnalyzeDocumentRequest`; mock returns sidecar values in SDK shape for PDF and PNG (rotation); text rules for other PDFs |
| C-13 | C | Images and pictures | `strip_pdf_images` removes embedded images from typed pages and keeps scans; text-only vs with-images results for the logo sample; ID card photo extracted; photos cannot be split; picture failure keeps the fields; pages counted twice, also on retry; pictures deleted with the document |
| C-14 | C | Batches | Progress through uploading, running, complete; review counts follow corrections; an interrupted upload completes with the files that arrived; list, rename, delete |
| C-12 | C | Deployment consistency | `test_deployment.py` | Parameter files against the template (names, allowed values, ranges, types); portal form outputs and dropdowns; every setting the code reads is set by the template; outputs; no gateway, APIM or Function app; hardening; lifecycle; roles; environment choices; no secrets, subscription IDs or e-mail addresses in the repository |

## Web (`manage.py test`, 55 tests)

| ID | Pri | Area | Expected |
|---|---|---|---|
| W-01 | C | Sign-in | Wrong password 403, then 429 after 5 (also with the right password); lock-out per client address; right password signs in with the chosen role; unknown role 400; empty configured password refused; dev mode; sign-out; no open redirect; tampered roles rejected |
| W-02 | C | Roles | Every portal route declares a permission; Users get 403 on Settings and preset APIs; Admin reaches everything |
| W-03 | H | Security | CSP, frame and content-type headers, `no-store` on document data, no inline scripts in any page, CSRF enforced |
| W-04 | C | Upload validation | Wrong type, wrong magic bytes, too large, too many pages, odd names, mixed batch, too many files, unavailable model, unknown fields, daily budget |
| W-05 | H | Results | JSON view, review page (model and API version), original file stream, selection change with Not found, edits and revert, mark reviewed and all, failed document and retry, pending review polls |
| W-06 | H | Exports | JSON, CSV, XLSX for one document and in bulk |
| W-07 | H | History and deletion | Listing, filters, htmx partial, retention note; owner and Admin can delete, others cannot |
| W-10 | C | Batches | Files sent one by one join one batch; the panel is complete only when every document has finished and the expected number is there; batch Excel lists failures with the reason; batch size limit |
| W-11 | C | Include images | Off by default: typed vendor name, "Typed text only" note; on: logo name, pictures; picture download, ZIPs, 404 for unknown pictures; pages counted twice |
| W-12 | C | Batch pages | Bulk upload becomes a named batch; single uploads and samples do not; batch page opens the first document needing review; corrections reach the batch Excel; no Excel and polling while running; rename escaped and validated; only Admins delete; unknown batch 404 |
| W-08 | M | Settings | Admin saves settings and presets; invalid values refused |
| W-09 | M | Static files | `collectstatic` with the hashed manifest storage succeeds |

## UI (Playwright, headless Chromium, `qa/tests/test_ui.py`, 40 tests)

| ID | Pri | Steps | Expected |
|---|---|---|---|
| U01 | C | Sign in as Admin, sign out, sign in as User, open /settings | Role badge and navigation per role; User gets the 403 page |
| U02 | H | Wrong password | Error message, still on the sign-in page |
| U03 | C | Model, preset, search, select all, clear, model change | Business card disabled; counts and preset switch to Custom correctly |
| U04 | M | Remember my selection, reload | "My saved selection" chosen and restored |
| U05 | C | Upload one PDF | Batch shows Done, review opens with file name and API version, stepper on Review |
| U06 | C | Upload 4 files | Statuses update live; Excel locked ("Waiting…") until all finish, then downloads by itself once; one row per document; the button gives the same file |
| U07 | H | Upload a .txt and a PNG named .pdf | Both refused with reasons |
| U08 | C | Sample PDF; compare boxes | Every checked box within 1.5 px of the sidecar polygon, also after zooming |
| U09 | C | Scanned PNG sample (rotated) | Boxes within 1.5 px of the rotated sidecar polygons |
| U10 | C | Hover a row; click a box | Box highlighted; row selected and stays selected |
| U11 | H | Two-page invoice | Hovering a page-2 field turns the page; 42 line items with 2 cells flagged |
| U12 | C | Header preset | Not found chip on Shipping address; Review chip on Purchase order; "1 of 13" |
| U13 | H | Change fields | New field and box appear, removed field disappears, no new analysis |
| U14 | C | Correct a field and a cell; Mark all reviewed | Edited chip, model value shown, counts update, all reviewed |
| U15 | C | Download XLSX, CSV, JSON; Copy JSON | Files open with the expected sheets and values; clipboard holds the JSON |
| U16 | H | Upload a file the mock fails | Failure reason and Retry; retry queues it again |
| U17 | H | History search, filters, bulk export, delete with confirmation | Filters update the URL and table; cancel keeps the row; delete removes it |
| U18 | H | Admin creates and deletes a preset; saves settings | Preset offered on Extract; deleted preset gone; settings saved |
| U19 | M | Theme toggle and reload | Theme switches and persists; colours change |
| U20 | H | Keyboard: skip link, Enter on the upload area, arrow keys and Enter on fields | File chooser opens; focus moves; Enter highlights the box; focus ring visible |
| U21 | H | 375 px wide: sign-in, Extract, History, Settings, review | No horizontal overflow |
| U22 | H | axe-core (WCAG 2.1 A and AA) on 5 pages | No serious or critical violations |
| U23 | H | Colour contrast in light and dark themes | No contrast violations |
| U24 | M | Reduced motion | Transitions effectively off |
| U26 | C | Include images off, then on, with the logo sample | Off: vendor name from the typed text, "Typed text only" note, no pictures. On: vendor name from the logo, picture shown, its box linked, download works |
| U27 | H | ID card sample with Include images on | Model switches to ID document; photo extracted and shown with its box |
| U28 | C | Name and upload 4 files, leave the page, open Batches, open the batch, Previous/Next, correct a field, Next needing review, download Excel, rename | Batch completes while away; first document needing review opens; counts update after the correction; the Excel file has 4 rows with the correction; no serious accessibility issues; no overflow at 375 px |
| U29 | H | Admin deletes a batch | Confirmation dialog; batch and its documents gone |
| U25 | C | Main flow with the CSP enforced (all other UI tests bypass the CSP for Playwright and axe) | No console errors, no CSP violations; pdf.js and its worker run |

Every UI test also fails on any browser console error.

## Deployment scripts (`qa/tests/test_deploy_scripts.py`, 22 tests + 1 opt-in)

| ID | Pri | Expected |
|---|---|---|
| D-01 | C | Demo: shared plan looked up (never changed), deployer object ID from the token, demo parameters and password passed, infrastructure before code, run-from-package settings, startup command (1 worker, 4 threads), read-only HTTPS SAS, restart, no Graph, Kudu or data-plane commands, URL and sign-in hint printed |
| D-02 | C | Failure paths: plan missing, plan in another region, not signed in, failed infrastructure deployment, no storage key (prod), no deployment outputs |
| D-03 | H | Providers checked and registered; registration failure warns with the command; Microsoft.Network checked with private networking |
| D-04 | H | New resource group created when missing; `--skip-infra`, `--skip-code`, `--seed`, `--deployment`; old packages pruned |
| D-05 | H | `--help` and unknown options for all three scripts; usage errors |
| D-06 | H | `bash -n` and `shellcheck` |
| D-07 | M | `PACKAGE_TEST=1`: `package.sh` builds a package with the app, `docintel`, `Config`, samples and collected static files |
