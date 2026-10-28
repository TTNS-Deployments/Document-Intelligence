# Test report: Document Intelligence (local mode)

**Verdict: everything that can run without Azure passes. The demo environment has been deployed; checks against the live service are in progress.**

The GitHub Codespace this was built in cannot sign in to Azure, so every result below comes from local mode (folder
storage, mock Document Intelligence) and from static checks of the deployment files. The real Document Intelligence
service, managed identity, Key Vault references, the ARM deployment and private networking are **not verified**.

## Environment

| | |
|---|---|
| Date | 2026-10-28 (images and batch features); first run 2026-10-25 |
| Mode | `DOCINTEL_MODE=local`, mock analyzer, `AUTH_MODE=password` for the UI tests |
| Python | 3.12.3 |
| Tools | Django 5.2.18, pytest 9.1.1, Playwright 1.64.1 (Chromium headless shell 156), axe-core 4.11.0, openpyxl 3.1.5, azure-ai-documentintelligence 1.0.2, ShellCheck 0.9.0, Bicep CLI 0.38.33 |
| Data | A fresh temporary data folder per test run |

## Results

| Suite | Command | Result |
|---|---|---|
| Core | `pytest Code/core` | **109 passed** |
| Web | `cd Code/webapp && python manage.py check && python manage.py test` | **48 passed**, no check issues |
| UI | `pytest qa/tests/test_ui.py` | **36 passed** |
| Deployment scripts | `pytest qa/tests/test_deploy_scripts.py` (with `PACKAGE_TEST=1`) | **23 passed** (22 against the fake `az`, plus the real package build) |
| Shell | `bash -n`, `shellcheck` on the three scripts | clean |
| Repository | `python qa/check_repo.py` (JSON, Markdown links and anchors, no build output, content rules) | clean |
| ARM template | Bicep `decompile` then `build` | builds; only style warnings from the decompiled Bicep (`use-resource-symbol-reference`, `use-parent-property`) |
| Package | `package.sh --vendor`, unzipped and started with Python 3.12 and `python -m gunicorn --workers 1 --threads 4` | health check, sign-in, hashed static files, pdf.js module and fonts, a sample analysis and History all worked |

## Problems the tests found, and fixed

| Found by | Problem | Fix |
|---|---|---|
| U21 | Pages overflowed horizontally at 375 px: grid columns sized to long unwrapped text, and a visually hidden table header escaped its scroll container | `minmax(0, 1fr)` grid columns; positioned scroll containers |
| U22, U23 | Low contrast on small tags, the Done chip, the Not found chip and the selected role card; an `aria-label` on an element without a role | Darker text tokens; `role="region"` on the preview |
| UI smoke run | The review viewer did not start after an htmx swap (htmx removes `<script>` tags; the swapped element was not searched) | Viewer settings moved to a `data-` attribute; the swapped element itself is initialised |
| C-12 | A portal-form dropdown default was a value, not a label | Fixed in `createUiDefinition.json` |
| D-07 | `package.sh` failed with a relative `PYTHON` path | The interpreter path is made absolute |
| Review of docs vs code | Restart recovery only ran on the first upload, not on the first request | `StartJobsMiddleware` starts the workers (and recovery) on the first request |
| U20 (repeated runs) | Pressing Enter on the upload area always activated the file input, but headless Chromium reported the native file dialog to Playwright only about half the time | The test checks that the file input was activated, then supplies the file |
| User testing on Azure | The vendor name was taken from the text in a logo instead of the typed company name | *Include images* switch: off by default, pictures are left out of typed PDFs before analysis |

## Not covered

- **Pictures on Azure:** picture extraction uses the Layout model with `output=figures` and
  `get_analyze_result_figure`; it is implemented against the installed SDK (1.0.2) and tested with the mock only.
  Whether real logos and ID photos are detected as pictures, and how well text-only mode works on real invoices,
  must be checked on the demo environment.
- **Azure services:** real analyses by Azure AI Document Intelligence (field values, confidences and polygons for
  real invoices, other languages, throttling and quota responses), Blob Storage with the managed identity (the
  Azure storage code is unit-tested only through the shared interface; `make docker-up` exercises it against
  Azurite but was not run here), Key Vault references, Application Insights telemetry.
- **Deployment:** the demo deployment (`deploy.sh -e demo`, shared plan, run from package) succeeded on 2026-10-25.
  Private endpoints and DNS, VNet integration, and the dev and prod parameter files are untested.
  The Deploy to Azure button and the GitHub *Deploy* workflow have not been run.
- **Browsers:** only Chromium (headless). Firefox, Safari and real mobile devices were not tested; mobile layout was
  checked at 375 px.
- **Scale:** no load test. Memory use on the shared B1 plan is expected to be low (one worker, one file per job) but
  was not measured on App Service.
- **Docker:** the image and the Azurite compose file were not built or run in this Codespace.

## What to verify after the first Azure deployment

1. Sign in with the demo password as Admin and as User.
2. Try each sample; confirm boxes line up on the real results (they come from the service, not the sidecars).
3. Upload a real invoice (PDF and photo), a receipt and an ID document.
4. Delete a document and check that its blobs are gone; check the lifecycle policy in the storage account.
5. Look at *Log stream* and Log Analytics for errors; check that no field values appear in the logs.
