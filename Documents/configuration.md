# Configuration Reference

## Where each setting comes from

| Source | Used for |
|---|---|
| App Service app settings (set by `azuredeploy.json`) | Everything the web app needs in Azure: endpoints, containers, limits, secrets as Key Vault references |
| `.env` (local, read by `make`) | Local overrides; see [`.env.example`](../.env.example) |
| `Config/fields.yaml` | The field catalog per model (read at start-up) |
| `Config/presets.yaml` | Built-in presets |
| `Config/settings.yaml` | Defaults for limits and review threshold |
| `config` container: `presets.json`, `settings.json` | Changes Admins make on the Settings page (no redeploy) |

Precedence for the review threshold, daily page limit and maximum pages: **Settings page** > **environment
variable** > **`Config/settings.yaml`**. An unresolved Key Vault reference (the literal `@Microsoft.KeyVault(...)`
string) is treated as empty.

## Environment variables

| Variable | Default | Set by the template | Meaning |
|---|---|---|---|
| `DOCINTEL_MODE` | `local` | `azure` | Default for every backend: `local` = folder storage and mock analyzer, `azure` = Blob Storage and Document Intelligence |
| `STORAGE_BACKEND` | from mode | | `local` or `azure` |
| `ANALYZE_BACKEND` | from mode | | `mock` or `azure` |
| `ENVIRONMENT_NAME` | `local` | `environmentName` | Shown in the footer |
| `AZURE_STORAGE_ACCOUNT_URL` | | blob endpoint | Storage account (managed identity) |
| `AZURE_STORAGE_CONNECTION_STRING` | | | Azurite or development only |
| `CONTAINER_UPLOADS`, `CONTAINER_RESULTS`, `CONTAINER_CONFIG` | `uploads`, `results`, `config` | same | Container names |
| `DOCINTEL_ENDPOINT` | | account endpoint | `https://<name>.cognitiveservices.azure.com/` (custom subdomain, required for managed identity) |
| `DOCINTEL_API_VERSION` | `2024-11-30` | `2024-11-30` | Document Intelligence API version |
| `DOCINTEL_KEY` | | | Developer machines only. Azure deployments disable key access and use the managed identity |
| `AZURE_CLIENT_ID` | | | Client ID of a user-assigned identity, if one is used instead of the system-assigned one |
| `MAX_UPLOAD_MB` | 10 | `maxUploadMb` | Largest file (also the request limit) |
| `MAX_PAGES` | 10 | `maxPages` | Largest PDF in pages |
| `MAX_FILES_PER_UPLOAD` | 10 | | Files per upload request (the browser sends a batch one file per request) |
| `MAX_BATCH_FILES` | 100 | | Documents in one upload batch (one Excel file for all of them) |
| `DAILY_PAGE_LIMIT` | 200 | `dailyPageLimit` | Pages per day, all users together |
| `REVIEW_THRESHOLD` | 0.80 | `reviewThreshold` | Confidence below which a field is flagged |
| `RETENTION_DAYS` | 7 | `retentionDays` | Shown to users; the lifecycle policy does the deleting |
| `DISPLAY_TIME_ZONE` | `Asia/Kolkata` | `displayTimeZone` | Times in the UI and the page-budget day |
| `WORKER_THREADS` | 2 | | Analysis threads in the web app |
| `ANALYZE_MAX_ATTEMPTS` | 3 | | Attempts for transient errors |
| `ANALYZE_RETRY_BASE_SECONDS` | 2 | | First back-off delay (doubles each time) |
| `MOCK_ANALYZE_DELAY` | 0.8 | | Seconds the mock analyzer waits (local mode) |
| `LOCAL_DATA_DIR` | `<repo>/.localdata` | | Local storage folder |
| `DOCINTEL_CONFIG_DIR`, `DOCINTEL_DATA_DIR` | found next to the code | | Override where `Config/` and `Data/` are |
| `AUTH_MODE` | `dev` (local), `password` (azure) | `authMode` | `password`: shared password plus Admin or User. `dev`: choose a role without a password (local mode only; refused otherwise) |
| `DEMO_PASSWORD` | | Key Vault reference `demo-password` | Shared password. Empty = sign-in refused ("not configured") |
| `DJANGO_SECRET_KEY` | local-only value | Key Vault reference `django-secret-key` | Required outside local mode |
| `DJANGO_DEBUG` | false | | Django debug pages (developer machines only) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | localhost | | Extra hosts; App Service's `WEBSITE_HOSTNAME` is added automatically |
| `DJANGO_SSL_REDIRECT` | true (azure) | | HTTPS redirect outside local mode |
| `CONTENT_SECURITY_POLICY` | built in | | Replace the default policy |
| `LOG_LEVEL` | `INFO` | | Python log level |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | | App Insights | Telemetry (App Service auto-instrumentation, `ApplicationInsightsAgent_EXTENSION_VERSION=~3`) |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | | `false` | The package already contains every library |
| `PYTHONPATH` | | `/home/site/wwwroot/.packages` | Where the bundled libraries are |
| `WEBSITE_RUN_FROM_PACKAGE` | | set by `deploy_code_arm.sh` | Read-only SAS URL of the code package |

## `Config/fields.yaml`

| Key | Meaning |
|---|---|
| `api_version` | API version the field names were checked against (2024-11-30) |
| `default_model` | Model selected on the Extract page |
| `models.<id>.label`, `.description` | Shown in the model dropdown |
| `models.<id>.enabled`, `.unavailable_reason` | `false` lists the model as unavailable and refuses jobs for it (`prebuilt-businessCard`) |
| `models.<id>.groups[].name` | Group heading in the field picker |
| `groups[].fields[].name` | Exact Document Intelligence field name |
| `.label`, `.type`, `.description` | Friendly label (also the export column), type, help text |
| `.items` | Sub-fields of an array of objects (a table) |
| `.item_type` | Type of the values of an array of plain values |
| `.derived` | `true` = computed by the app (`CurrencyCode`) |

## `Config/presets.yaml`

`presets.<model id>` is a list of presets with `id` (letters, digits, dashes), `name`, `fields` (field names) and
optionally `default: true` (one per model). Admin changes are stored in `config/presets.json`: `custom` presets
(created or edited) and `hidden` built-in presets (deleted).

## `Config/settings.yaml`

| Key | Default | Editable on the Settings page |
|---|---|---|
| `review_threshold` | 0.80 | yes |
| `daily_page_limit` | 200 | yes |
| `max_pages` | 10 | yes |
| `max_upload_mb` | 10 | no (it is also the request size limit) |
| `worker_threads` | 2 | no |
| `max_attempts` | 3 | no |

## ARM parameters

Every tier, size and option is a template parameter. See the
[SKU and sizing parameters](../Deployment/README.md#sku-and-sizing-parameters) table.
