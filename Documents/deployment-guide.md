# Deployment Guide

Deploy Document Intelligence to Azure: one ARM template for the infrastructure, then the code as a package that
the web app runs from. Everything goes through the Azure **management API**, so it works in **Azure Cloud Shell
(Bash)**, where tokens for App Service (Kudu), Microsoft Graph, Storage and Key Vault data planes are not
available.

> **Status.** The template, scripts and package are tested locally (JSON and Bicep checks, consistency tests,
> `shellcheck`, a fake `az`, and the package running under gunicorn). **No deployment to Azure has been run from
> this repository yet.** The demo command below is the first real run; dev and prod are untested.

## Prerequisites

- Azure Cloud Shell (Bash), or any shell with the Azure CLI, Python 3 with `pip`, `git` and `tar`.
- **Owner** on the resource group (or Contributor plus User Access Administrator): the template creates role
  assignments for the web app's managed identity.
- For the demo: the resource group `Vaibhav.Chaudhary` (Central India) and the Linux App Service plan
  `ccai-demo-gqausd-web-plan` in it. The web app is added to that plan as a **separate web app**; the plan is never
  changed.

## Before the first deployment: check Document Intelligence

Run these once in Cloud Shell:

```bash
az provider register -n Microsoft.CognitiveServices --wait
az cognitiveservices account list-skus --kind FormRecognizer --location centralindia -o table
az cognitiveservices account list --query "[?kind=='FormRecognizer'].{n:name,sku:sku.name,rg:resourceGroup,loc:location}" -o table
```

1. Registers the resource provider (nothing happens if it is already registered).
2. Lists the Document Intelligence tiers offered in Central India: `S0` must be in the list (and `F0` if you want the
   free tier).
3. Lists existing Document Intelligence accounts in the subscription. Only one **F0** account is allowed per
   subscription; if one already exists, keep the default `S0`.

If Central India does not offer the 2024-11-30 pre-built models, change only `docIntelLocation` in
`Deployment/ARM/parameters/demo.parameters.json` (for example to `southindia` or `eastus`). Everything else stays in
Central India. `deploy.sh` also registers any missing provider among `Microsoft.CognitiveServices`,
`Microsoft.Web`, `Microsoft.KeyVault`, `Microsoft.Storage`, `Microsoft.Insights`, `Microsoft.OperationalInsights`
(and `Microsoft.Network` when private networking is on), and prints a clear warning if it cannot.

## 1. Choose SKUs

Edit the parameter file of the environment, `Deployment/ARM/parameters/<env>.parameters.json`. Every tier and size
is a parameter; see the [SKU and sizing parameters](../Deployment/README.md#sku-and-sizing-parameters). The demo
file already holds the cheapest settings that run everything (shared plan, Document Intelligence S0, LRS storage,
7-day retention, 1 GB/day logs).

## 2. Deploy the demo from Cloud Shell

Choose a password for signing in (at least 8 characters; it is stored in Key Vault, not in the repository), and
replace `<password>` with it:

```bash
cd ~ && git clone https://github.com/TTNS-Deployments/Document-Intelligence.git ; cd ~/Document-Intelligence && git pull && Deployment/scripts/deploy.sh -e demo --param demoPassword='<password>'
```

What it does:

1. Reads `Deployment/environments/demo.env` (resource group, region, shared plan).
2. Reuses the existing resource group, checks and registers resource providers.
3. Reads your object ID from the ARM access token (no Microsoft Graph), so you get data access to Storage and Key
   Vault.
4. Looks up the shared App Service plan's resource ID and stops with a clear message if it is missing or in another
   region.
5. Deploys `azuredeploy.json` with `demo.parameters.json` as deployment `docintel-demo`.
6. Builds the code package with every Python library included (`package.sh --vendor`, about a minute), uploads it to
   the `code-packages` container with the storage account key, points the web app at it with a one-year read-only
   SAS URL (`WEBSITE_RUN_FROM_PACKAGE`), sets the startup command (gunicorn, 1 worker, 4 threads) and restarts it.
7. Prints the web app URL.

The code step always runs after the infrastructure step, because an infrastructure deployment resets the app
settings, including `WEBSITE_RUN_FROM_PACKAGE`.

Later updates (after `git pull`): run the same command. Without `--param demoPassword` the existing password is
kept. Code only: `Deployment/scripts/deploy.sh -e demo --skip-infra`.

### Other environments

```bash
Deployment/scripts/deploy.sh -e dev -g rg-docint-dev -l centralindia --param demoPassword='<password>'
Deployment/scripts/deploy.sh -e prod -g rg-docint-prod -l centralindia --param demoPassword='<password>'
```

A missing resource group is created. dev and prod create their own App Service plan. Both are **untested**.

### Deploy with the button

The **Deploy to Azure** button in the README opens a portal form (`createUiDefinition.json`) with a dropdown per
SKU. It deploys the infrastructure only. Then deploy the code from Cloud Shell, with the deployment name the portal shows
under *Resource group → Deployments*:

```bash
Deployment/scripts/deploy_code_arm.sh -g <resource group> -e <environment> --deployment <deployment name>
```

The button works only while the repository is public.

### Deploy with GitHub Actions

`.github/workflows/deploy.yml` (manual, untested) runs `deploy.sh` with OIDC sign-in. Once per environment:

1. Create an app registration or user-assigned managed identity with Owner (or Contributor plus User Access
   Administrator) on the resource group, and a federated credential for `repo:<org>/<repo>:environment:<env>`.
2. In the repository, create a GitHub environment named like the parameters file (`demo`, `dev`, `prod`) with the
   variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, and the secret
   `DEMO_PASSWORD`.
3. Run *Deploy* from the Actions tab and choose the environment and scope.

## 3. After deployment

1. Open the printed URL. The first request after a restart takes up to a minute on B1.
2. Sign in with the password you chose, as **Admin**.
3. On **Extract**, choose **Try a sample** and run one. A real analysis appears in a few seconds, with highlight
   boxes on the page.
4. Upload one of your own invoices (PDF, JPEG or PNG, up to 10 MB and 10 pages).
5. Check **History** and **Settings**.

Logs: *App Service → Log stream*, or Log Analytics (`AppServiceConsoleLogs`).

## Production (private network)

`prod.parameters.json` sets `privateNetworking=true` and `allowSharedKeyAccess=false`:

- A VNet with an app-integration subnet and a private-endpoint subnet, private endpoints for Blob, Document
  Intelligence and Key Vault, the private DNS zones `privatelink.blob.core.windows.net`,
  `privatelink.cognitiveservices.azure.com` and `privatelink.vaultcore.azure.net` linked to the VNet, and public
  network access disabled on those three services.
- The web app integrates with the VNet and routes all outbound traffic through it; it stays reachable on its public
  HTTPS address.
- **Code deployment must run from inside the network.** `deploy_code_arm.sh` needs the storage account key and
  public access to Blob Storage, so it stops with a message in prod. From a machine or self-hosted runner in the
  VNet, deploy with `az webapp deploy` (Kudu) or temporarily allow your address on the storage account. This path is
  untested.
- Add Entra ID sign-in before real production use (roadmap).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `App Service plan '…' was not found` | Check `EXISTING_PLAN_NAME` and `EXISTING_PLAN_RESOURCE_GROUP` in `Deployment/environments/demo.env`, or clear `EXISTING_PLAN_NAME` to create a plan. |
| `the shared plan is in '…' but the web app would go to '…'` | A web app must be in its plan's region: set `location` in the parameters file to the plan's region. |
| `MissingSubscriptionRegistration` | Register the provider: `az provider register -n <namespace> --wait`. |
| `InsufficientQuota` / `SpecialFeatureOrQuotaIdRequired` for Document Intelligence | Use `S0`, or another region with `docIntelLocation`. |
| `Only one free account is allowed` (F0) | The subscription already has an F0 account: use `S0`. |
| `CustomSubDomainName already in use` or `FlagMustBeSetForRestore` | A deleted account with the same name is soft-deleted. Purge it: `az cognitiveservices account purge -g <rg> -n <name> -l <region>`, then redeploy. |
| Key Vault name already in use | A soft-deleted vault holds the name. `az keyvault purge -n <name>` (or recover it). |
| `AuthorizationFailed` on role assignments | You need Owner (or User Access Administrator) on the resource group. |
| Sign-in page says **not configured** | No demo password has been set, or the Key Vault reference had not resolved yet when the app started. Set it with `deploy.sh -e demo --param demoPassword='…'` (the infrastructure step writes it to Key Vault), wait a minute and reload. |
| `Could not read the key of storage account` | `allowSharedKeyAccess` is false (prod): deploy the code from inside the network. |
| Documents fail with **busy (HTTP 429)** | Throttling. The app retries automatically; wait and use **Retry**. On F0, move to S0. |
| Documents fail with **quota is used up** | F0 allows 500 pages a month. Move to S0 or wait for the next month. |
| Documents fail with **model is not available** | The region lacks the 2024-11-30 pre-built models: change `docIntelLocation` and redeploy. |
| Documents fail with **not allowed to call Document Intelligence** | The role assignment is missing or still propagating (a few minutes after the first deployment), or network rules block the app. |
| The app shows an error page right after deployment | Look at *Log stream*. A missing `WEBSITE_RUN_FROM_PACKAGE` means the code step did not run: `deploy.sh -e demo --skip-infra`. |
| New uploads are refused with **daily page limit** | Raise it on the Settings page (Admin) or wait for the next day. |
