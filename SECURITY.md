# Security

## Reporting a vulnerability

Do **not** open a public issue for security problems. Raise a ticket marked *Security* in the DBCH support portal
(see [SUPPORT.md](SUPPORT.md)), or contact the TTNS service delivery team directly. Include the steps to reproduce
and the potential impact. Never attach real invoices; reproduce with the bundled sample invoices.

## How the solution protects documents

Invoices are sensitive: they carry names, addresses, tax IDs, bank details and amounts.

| Area | Control |
|---|---|
| Sign-in | One shared demo password plus an Admin or User choice, kept in Key Vault. Compared in constant time; 5 wrong passwords from one address lock sign-in for 15 minutes; an empty password refuses sign-in. **This is for demos only.** Microsoft Entra ID sign-in with real roles is on the roadmap. |
| Authorisation | A role check on every page and API route. Admins manage presets and settings and can delete any result; Users can delete only the documents uploaded in their own sign-in session. |
| Service access | The web app's **system-assigned managed identity** with least-privilege roles: Storage Blob Data Contributor, Cognitive Services User, Key Vault Secrets User. Key access to Document Intelligence is disabled. There are no service keys in app settings. |
| Secrets | The demo password and the Django secret key are in **Key Vault** (RBAC mode) and reach the app through Key Vault references. Nothing secret is stored in this repository. |
| Uploads | Extension, file signature (magic bytes), size, image dimensions, PDF page count and encryption are checked **before** anything is stored or sent to Azure. File names are sanitised. |
| Data at rest | Private blob containers, encryption at rest, TLS 1.2 minimum. A lifecycle policy deletes uploads and results after `retentionDays` (demo 7, dev 30, prod 90). Users can delete a result and its file at once. Blob soft delete keeps deleted blobs for 7 more days, then removes them. |
| Logs | Only job IDs, model, page counts, durations and status are logged. Field values and file content are never logged. |
| Web | HTTPS only, HSTS, secure and HttpOnly cookies, CSRF protection, a strict Content-Security-Policy (scripts only from the app itself, no inline scripts, no CDN), `X-Frame-Options: DENY`, `no-store` caching for document data. Exports neutralise spreadsheet formulas. |
| Network (prod) | `privateNetworking=true`: private endpoints and private DNS for Blob, Document Intelligence and Key Vault, public network access disabled on those three, and all web app outbound traffic routed through the VNet. |
| Cost guard | A daily page budget (`DAILY_PAGE_LIMIT`) refuses new jobs once reached. |

Not covered by the template: Microsoft Defender for Cloud plans (a subscription-level setting), WAF or DDoS
protection in front of the web app, and security or legal compliance audits.
