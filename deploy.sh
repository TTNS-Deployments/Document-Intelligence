#!/usr/bin/env bash
# ==============================================================================
# deploy.sh - Deploys the Document Intelligence solution on Azure
#
# Order:
#   1. Network            (VNet with GatewaySubnet)
#   2. VPN Gateway        (started first and left running; takes 30-45 minutes)
#   3. Storage Account    (incoming + results containers)
#   4. Document Intelligence (prebuilt + custom models)
#   5. Function app       (Consumption, Linux, Python)
#   6. Access roles       (Function identity -> Storage, Document Intelligence)
#      then the Function code is deployed from functions/
#   7. API Management     (Consumption; subscription key, CORS, rate limit)
#      then the upload page is published to the storage static website
#
# SKUs and limits are read from config/skus.env.
# Requires: az cli logged in, jq, Owner (or Contributor + User Access Administrator)
# on the subscription or resource group (step 6 creates role assignments).
#
# Usage: ./deploy.sh [--yes] [--help]
# ==============================================================================
set -euo pipefail

# shellcheck disable=SC2034
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=true ;;
    -h|--help) sed -n '2,23p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/common.sh"

require_tools
load_skus
require_publisher_email

cat <<PLAN

Deployment plan
  Resource group:    $RESOURCE_GROUP  ($LOCATION)
  Name prefix/env:   $NAME_PREFIX / $ENVIRONMENT
  SKU file:          $SKU_FILE
  Document Intel.:   $DOCINT_SKU
  VPN Gateway:       $VPN_GATEWAY_SKU ($VPN_GATEWAY_GENERATION)
  Functions:         $FUNCTION_PLAN_SKU, $FUNCTION_RUNTIME
  API Management:    $APIM_SKU  (publisher: $APIM_PUBLISHER_EMAIL)
  Storage:           $STORAGE_SKU ($STORAGE_ACCESS_TIER)
  Upload limit:      ${MAX_UPLOAD_MB} MB, ${APIM_RATE_LIMIT_CALLS_PER_MIN} calls per minute per key

PLAN
confirm "Deploy this to subscription $SUBSCRIPTION_ID?" || { echo "Cancelled."; exit 0; }

log "Creating resource group: $RESOURCE_GROUP"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none

COMMON=(namePrefix="$NAME_PREFIX" environment="$ENVIRONMENT" location="$LOCATION")

# ---------- 1. Network ----------
log "Deploying network"
NET=$(deploy_template 01-network "${COMMON[@]}" vnetAddressPrefix="$VNET_ADDRESS_PREFIX" gatewaySubnetPrefix="$GATEWAY_SUBNET_PREFIX")
GATEWAY_SUBNET_ID=$(get_output "$NET" .gatewaySubnetId.value)

# ---------- 2. VPN Gateway (runs in the background) ----------
log "Starting VPN Gateway deployment in the background (30 to 45 minutes)"
deploy_template_nowait 02-vpn-gateway "${COMMON[@]}" gatewaySku="$VPN_GATEWAY_SKU" \
  gatewayGeneration="$VPN_GATEWAY_GENERATION" gatewaySubnetId="$GATEWAY_SUBNET_ID"

# ---------- 3. Storage ----------
log "Deploying Storage Account"
ST=$(deploy_template 03-storage "${COMMON[@]}" skuName="$STORAGE_SKU" accessTier="$STORAGE_ACCESS_TIER")
STORAGE_NAME=$(get_output "$ST" .storageAccountName.value)
WEB_ENDPOINT=$(get_output "$ST" .webEndpoint.value)
echo "Storage Account: $STORAGE_NAME"

# ---------- 4. Document Intelligence ----------
log "Deploying Azure Document Intelligence"
DI=$(deploy_template 04-docintelligence "${COMMON[@]}" skuName="$DOCINT_SKU")
DOCINT_NAME=$(get_output "$DI" .accountName.value)
DOCINT_ENDPOINT=$(get_output "$DI" .endpoint.value)
echo "Document Intelligence: $DOCINT_NAME"

# ---------- 5. Function app ----------
log "Deploying the Function app"
FN=$(deploy_template 05-functionapp "${COMMON[@]}" planSku="$FUNCTION_PLAN_SKU" linuxFxVersion="$FUNCTION_RUNTIME" \
  storageAccountName="$STORAGE_NAME" docIntEndpoint="$DOCINT_ENDPOINT" defaultModel="$DEFAULT_MODEL" \
  availableModels="$AVAILABLE_MODELS" maxUploadMb="$MAX_UPLOAD_MB")
FUNCTION_NAME=$(get_output "$FN" .functionAppName.value)
FUNCTION_HOST=$(get_output "$FN" .defaultHostName.value)
FUNCTION_PRINCIPAL=$(get_output "$FN" .principalId.value)
echo "Function app: $FUNCTION_NAME"

# ---------- 6. Access roles + code ----------
log "Granting the Function app's identity access to Storage and Document Intelligence"
deploy_template 06-rbac principalId="$FUNCTION_PRINCIPAL" storageName="$STORAGE_NAME" docIntName="$DOCINT_NAME" >/dev/null

log "Deploying the Function code from functions/"
mkdir -p "$BUILD_DIR"
make_zip "$ROOT/functions" "$BUILD_DIR/functionapp.zip"
az functionapp deploy --resource-group "$RESOURCE_GROUP" --name "$FUNCTION_NAME" \
  --src-path "$BUILD_DIR/functionapp.zip" --type zip -o none

log "Waiting for the Function host key"
FUNCTION_KEY=$(wait_for_function_key "$FUNCTION_NAME") || die "No host key after 6 minutes. Check the Function app logs in the portal, then re-run ./deploy.sh."

# ---------- 7. API Management ----------
log "Deploying API Management (Consumption)"
APIM=$(deploy_template 07-apim "${COMMON[@]}" skuName="$APIM_SKU" capacity="$APIM_CAPACITY" \
  publisherEmail="$APIM_PUBLISHER_EMAIL" publisherName="$APIM_PUBLISHER_NAME" \
  functionHostName="$FUNCTION_HOST" functionKey="$FUNCTION_KEY" allowedOrigin="$WEB_ENDPOINT" \
  rateLimitCallsPerMinute="$APIM_RATE_LIMIT_CALLS_PER_MIN")
APIM_NAME=$(get_output "$APIM" .apimName.value)
API_BASE_URL=$(get_output "$APIM" .apiBaseUrl.value)
APIM_SUBSCRIPTION=$(get_output "$APIM" .subscriptionName.value)
echo "API Management: $APIM_NAME"

# ---------- Upload page ----------
log "Publishing the upload page to the storage static website"
rm -rf "$BUILD_DIR/web" && mkdir -p "$BUILD_DIR/web"
cp -R "$ROOT/web/." "$BUILD_DIR/web/"
cat > "$BUILD_DIR/web/config.js" <<CONFIG
window.APP_CONFIG = {
  apiBaseUrl: "$API_BASE_URL",
  defaultModel: "$DEFAULT_MODEL",
  maxUploadMb: $MAX_UPLOAD_MB,
  reviewThreshold: $REVIEW_THRESHOLD
};
CONFIG
az storage blob service-properties update --account-name "$STORAGE_NAME" --static-website \
  --index-document index.html --404-document index.html --auth-mode key -o none
az storage blob upload-batch --account-name "$STORAGE_NAME" --destination '$web' \
  --source "$BUILD_DIR/web" --overwrite --auth-mode key -o none

SUB_KEY=$(az rest --method post \
  --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ApiManagement/service/$APIM_NAME/subscriptions/$APIM_SUBSCRIPTION/listSecrets?api-version=2022-08-01" \
  --query primaryKey -o tsv 2>/dev/null || true)

# ---------- VPN Gateway ----------
log "Waiting for the VPN Gateway deployment to finish"
VPN_PUBLIC_IP="(not ready)"
if az deployment group wait --resource-group "$RESOURCE_GROUP" --name 02-vpn-gateway --created -o none 2>/dev/null; then
  VPN=$(deployment_outputs 02-vpn-gateway)
  VPN_PUBLIC_IP=$(get_output "$VPN" .publicIpAddress.value)
else
  warn "The VPN Gateway deployment did not succeed. See: az deployment group show -g $RESOURCE_GROUP -n 02-vpn-gateway"
fi

log "Deployment complete"
cat <<SUMMARY

Resource Group:        $RESOURCE_GROUP  ($LOCATION)
Upload page:           ${WEB_ENDPOINT}
API base URL:          $API_BASE_URL
API key for the page:  ${SUB_KEY:-"(run: az rest ... listSecrets, see the README)"}
Function app:          $FUNCTION_NAME
Document Intelligence: $DOCINT_NAME  ($DOCINT_ENDPOINT)
Storage Account:       $STORAGE_NAME  (containers "incoming" and "results")
API Management:        $APIM_NAME
VPN Gateway public IP: $VPN_PUBLIC_IP

Open the upload page, paste the API key, pick a document and choose "Extract fields".
Treat the API key like a password and share it only with people who should upload documents.
To connect the VPN Gateway to another network, run ./connect-vpn.sh (see the README).

SUMMARY
