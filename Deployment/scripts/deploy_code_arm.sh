#!/usr/bin/env bash
# Deploys the web app code using ONLY the Azure management API (works in Azure Cloud Shell, where tokens for
# App Service/Kudu, Storage, Key Vault and Microsoft Graph are refused).
#
#   Deployment/scripts/deploy_code_arm.sh -g <resource-group> -e <environment> [--no-build]
#
#   -g, --resource-group   resource group of the deployment [required]
#   -e, --environment      environment name; the infrastructure deployment is "docintel-<environment>" [required]
#       --no-build         reuse build/webapp.zip instead of running package.sh --vendor
#   -h, --help             show this help
#
# Steps:
#   1. package.sh --vendor builds build/webapp.zip with every Python library included
#   2. the zip is uploaded to the "code-packages" container with the storage account key (read via the
#      management API; needs allowSharedKeyAccess=true)
#   3. the web app runs from that package: WEBSITE_RUN_FROM_PACKAGE = read-only SAS URL valid for one year
#   4. the startup command is set (gunicorn, 1 worker, 4 threads) and the web app is restarted
# Run it after every infrastructure deployment: the template resets the app settings (deploy.sh does this).
set -euo pipefail

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RG="" ENV="" BUILD_PACKAGE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--resource-group) RG="${2:-}"; shift 2 ;;
    -e|--environment) ENV="${2:-}"; shift 2 ;;
    --no-build) BUILD_PACKAGE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option $1 (see --help)" >&2; exit 1 ;;
  esac
done
[[ -n "$RG" && -n "$ENV" ]] || { echo "Usage: $0 -g <resource-group> -e <environment>  (see --help)" >&2; exit 1; }

DEPLOYMENT="docintel-$ENV"
STARTUP="python -m gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 1 --threads 4 config.wsgi"
CONTAINER="code-packages"
KEEP_PACKAGES=3

out() { az deployment group show -g "$RG" -n "$DEPLOYMENT" --query "properties.outputs.$1.value" -o tsv; }
WEB_APP="$(out webAppName 2>/dev/null || true)"
STORAGE="$(out storageAccountName 2>/dev/null || true)"
if [[ -z "$WEB_APP" || -z "$STORAGE" ]]; then
  echo "Could not read the outputs of deployment '$DEPLOYMENT' in resource group '$RG'." >&2
  echo "Deploy the infrastructure first: Deployment/scripts/deploy.sh -e $ENV" >&2
  exit 1
fi

if [[ $BUILD_PACKAGE -eq 1 ]]; then
  echo "==> Packaging with all Python libraries included"
  "$ROOT/Deployment/scripts/package.sh" --vendor
fi
[[ -f "$ROOT/build/webapp.zip" ]] || { echo "build/webapp.zip not found: run package.sh --vendor" >&2; exit 1; }

echo "==> Reading the storage account key of $STORAGE (management API)"
if ! KEY="$(az storage account keys list -g "$RG" -n "$STORAGE" --query "[0].value" -o tsv 2>/dev/null)" || [[ -z "$KEY" ]]; then
  echo "Could not read the key of storage account $STORAGE." >&2
  echo "This script needs allowSharedKeyAccess=true (demo and dev). For prod (keys disabled, private endpoints)," >&2
  echo "deploy the code from inside the network: see Documents/deployment-guide.md, 'Production (private network)'." >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d%H%M%S)"
BLOB="webapp-$STAMP.zip"
EXPIRY="$(date -u -d '+365 days' '+%Y-%m-%dT%H:%MZ')"
echo "==> Uploading $BLOB to $STORAGE/$CONTAINER"
az storage container create --account-name "$STORAGE" --account-key "$KEY" -n "$CONTAINER" -o none
az storage blob upload --account-name "$STORAGE" --account-key "$KEY" -c "$CONTAINER" -n "$BLOB" \
  -f "$ROOT/build/webapp.zip" --overwrite -o none
PACKAGE_URL="$(az storage blob generate-sas --account-name "$STORAGE" --account-key "$KEY" -c "$CONTAINER" -n "$BLOB" \
  --permissions r --expiry "$EXPIRY" --https-only --full-uri -o tsv)"
[[ "$PACKAGE_URL" == https://* ]] || { echo "Could not create a SAS URL for the package" >&2; exit 1; }

echo "==> Pointing web app $WEB_APP at the package"
az webapp config appsettings set -g "$RG" -n "$WEB_APP" -o none --settings \
  WEBSITE_RUN_FROM_PACKAGE="$PACKAGE_URL" SCM_DO_BUILD_DURING_DEPLOYMENT=false \
  PYTHONPATH=/home/site/wwwroot/.packages
az webapp config set -g "$RG" -n "$WEB_APP" -o none --startup-file "$STARTUP"
echo "==> Restarting $WEB_APP"
az webapp restart -g "$RG" -n "$WEB_APP" -o none

# Keep the newest packages only (the running one is the newest).
OLD="$(az storage blob list --account-name "$STORAGE" --account-key "$KEY" -c "$CONTAINER" --prefix webapp- \
  --query "[].name" -o tsv | sort -r | tail -n +$((KEEP_PACKAGES + 1)))"
for name in $OLD; do
  az storage blob delete --account-name "$STORAGE" --account-key "$KEY" -c "$CONTAINER" -n "$name" -o none || true
done

HOST="$(az webapp show -g "$RG" -n "$WEB_APP" --query defaultHostName -o tsv)"
echo "Code deployed. Web app: https://$HOST (the first request after a restart can take about a minute)"
