# Deployment

| File | Purpose |
|---|---|
| `ARM/azuredeploy.json` | The ARM template for every Azure resource, role assignment and app setting |
| `ARM/parameters/demo.parameters.json`, `dev.parameters.json`, `prod.parameters.json` | **The SKU files.** Pick the tier and size of every service per environment. Copy one to add an environment (`test`, `uat`). |
| `ARM/createUiDefinition.json` | Portal form used by the *Deploy to Azure* button (a dropdown per SKU) |
| `environments/demo.env` | Deployment variables for the demo: subscription, resource group, region, shared App Service plan |
| `scripts/deploy.sh` | Infrastructure, then code, in one command (`-e <env> [-g <rg>] [--param name=value]`) |
| `scripts/deploy_code_arm.sh` | Code deployment through the management API only: package upload with the storage key, run from package |
| `scripts/package.sh` | Builds `build/webapp.zip` (`--vendor`: every Python library included, static files collected) |

Step-by-step instructions are in [Documents/deployment-guide.md](../Documents/deployment-guide.md).

> **What has been verified.** The template passes JSON checks, parameter and portal-form consistency tests, and a
> Bicep decompile and build. The scripts pass `bash -n` and `shellcheck` and are tested against a fake `az`
> (including failure paths). `package.sh --vendor` was run and the package was started under gunicorn with
> Python 3.12. **No deployment to Azure has been run from this repository yet**: the demo is the first one.
> The dev and prod parameter files are **untested**.

## Demo environment

For a demo or proof of concept, use the `demo` files. They choose the cheapest settings that still run the whole
system:

| File | Contents |
|---|---|
| `ARM/parameters/demo.parameters.json` | No new App Service plan (the web app is a separate app on the shared B1 plan, passed in by `deploy.sh`); Document Intelligence **S0** in `centralindia`; Storage `Standard_LRS`; uploads and results deleted after **7 days**; Log Analytics 30 days and 1 GB/day; Key Vault standard; demo password sign-in; public endpoints; tags `owner=TTNS`, `project=document-intelligence`, `purpose=demo` |
| `environments/demo.env` | Resource group `Vaibhav.Chaudhary` (reused, never recreated), region `centralindia`, shared plan `ccai-demo-gqausd-web-plan` in that resource group |

```bash
Deployment/scripts/deploy.sh -e demo --param demoPassword='<choose a password>'
```

`deploy.sh` looks up the shared plan's resource ID with `az appservice plan show` and passes it as
`existingAppServicePlanId`, so no subscription ID is stored in the repository. If the plan is not found, or is in
another region, it stops before deploying anything. The template **never modifies** an existing plan. Because the
plan's 1.75 GB of memory is shared with other apps, the web app runs gunicorn with 1 worker and 4 threads and keeps
one file and one result in memory per job.

The password is stored in Key Vault only when you pass it, so later deployments without `--param demoPassword`
keep it. Remove the demo by deleting the `docint-demo-*` resources (and `docintdemo*st`) in the resource group.

## SKU and sizing parameters

The values below are those in the three parameter files. "Options" are the values the template accepts.

| Parameter | demo | dev | prod | Options / notes |
|---|---|---|---|---|
| `location` | centralindia | centralindia | centralindia | Region of every resource except Document Intelligence |
| **Document Intelligence** | | | | |
| `docIntelSku` | S0 | S0 | S0 | `S0` (pay per page), `F0` (free: 500 pages a month, first 2 pages of each document, one F0 account per subscription) |
| `docIntelLocation` | centralindia | centralindia | centralindia | Any region that offers the 2024-11-30 pre-built models. Changing it is the only change needed if a region lacks them |
| **Compute** | | | | |
| `existingAppServicePlanId` | set by `deploy.sh` (shared B1) | "" (new plan) | "" (new plan) | Resource ID of an existing Linux plan in the same region; empty = create one |
| `webAppSku` | (not used) | B1 | P0v3 | `B1`–`B3`, `S1`–`S3`, `P0v3`–`P3v3`. Used only when a plan is created |
| `webAppInstanceCount` | (not used) | 1 | 2 | 1–10 |
| **Storage** | | | | |
| `storageSku` | Standard_LRS | Standard_LRS | Standard_ZRS | `Standard_LRS`, `Standard_ZRS`, `Standard_GRS`, `Standard_RAGRS`, `Standard_GZRS` |
| `allowSharedKeyAccess` | true | true | false | `deploy_code_arm.sh` needs `true` (it uploads the package with the account key) |
| `retentionDays` | 7 | 30 | 90 | Days after which uploads and results are deleted (1–3650) |
| **Operations** | | | | |
| `logAnalyticsRetentionDays` | 30 | 30 | 90 | 30–730 |
| `logAnalyticsDailyQuotaGb` | 1 | 1 | 5 | Daily ingestion cap in GB (-1 = none) |
| `keyVaultSku` | standard | standard | standard | `standard`, `premium` |
| **Network** | | | | |
| `privateNetworking` | false | false | true | Private endpoints and DNS for Blob, Document Intelligence and Key Vault; VNet integration of the web app |
| `vnetAddressPrefix`, `appSubnetPrefix`, `privateEndpointSubnetPrefix` | (defaults) | (defaults) | 10.40.0.0/16, 10.40.1.0/24, 10.40.2.0/24 | Used only with private networking |
| **Application** | | | | |
| `authMode` | password | password | password | `password` (shared demo password plus Admin or User). Entra ID sign-in is a roadmap item |
| `maxUploadMb` | 10 | 10 | 10 | 1–500 (F0 accepts at most 4 MB) |
| `maxPages` | 10 | 10 | 10 | Admins can change it at runtime |
| `dailyPageLimit` | 200 | 500 | 5000 | Cost guard; Admins can change it at runtime |
| `reviewThreshold` | 0.80 | 0.80 | 0.80 | 0 to 1; Admins can change it at runtime |
| `displayTimeZone` | Asia/Kolkata | Asia/Kolkata | Asia/Kolkata | Also the day boundary of the page budget |
| `tags` | owner, project, purpose | | | Added to every resource |

The secrets `demoPassword` and `djangoSecretKey` are **not** stored in the parameter files. Pass the password with
`--param demoPassword='...'`; the Django secret key is generated on every deployment (which signs users out).

The template deploys no VPN or virtual network gateway, no API Management and no Function app: the web app does all
the work itself.
