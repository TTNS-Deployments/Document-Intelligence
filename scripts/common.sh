#!/usr/bin/env bash
# common.sh - shared settings and helpers for deploy.sh and connect-vpn.sh.
# Meant to be sourced, not run directly.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT/templates"
# shellcheck disable=SC2034
BUILD_DIR="$ROOT/.build"
SKU_FILE="${SKU_FILE:-$ROOT/config/skus.env}"

# ---------- Configuration (override with environment variables or edit here) ----------
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-docint-dev}"
LOCATION="${LOCATION:-centralindia}"
NAME_PREFIX="${NAME_PREFIX:-docint}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
VNET_ADDRESS_PREFIX="${VNET_ADDRESS_PREFIX:-10.30.0.0/24}"
GATEWAY_SUBNET_PREFIX="${GATEWAY_SUBNET_PREFIX:-10.30.0.0/27}"
# API Management needs a publisher name and email (shown in the developer portal and used for
# service notifications). Set APIM_PUBLISHER_EMAIL before running, or you will be asked.
APIM_PUBLISHER_NAME="${APIM_PUBLISHER_NAME:-Document Intelligence}"
APIM_PUBLISHER_EMAIL="${APIM_PUBLISHER_EMAIL:-}"
ASSUME_YES="${ASSUME_YES:-false}"
# -------------------------------------------------------------------------------------------

log()  { echo -e "\n\033[1;36m==> $1\033[0m"; }
warn() { echo -e "\033[1;33m! $1\033[0m"; }
die()  { echo -e "\033[1;31mError: $1\033[0m" >&2; exit 1; }

require_tools() {
  command -v az >/dev/null 2>&1 || die "Azure CLI not found. Install it first."
  command -v jq >/dev/null 2>&1 || die "jq not found. Install it first (used to parse deployment outputs)."
  az account show >/dev/null 2>&1 || die "Run 'az login' first."
  SUBSCRIPTION_ID=$(az account show --query id -o tsv)
  echo "Using subscription: $SUBSCRIPTION_ID"
}

load_skus() {
  [[ -f "$SKU_FILE" ]] || die "SKU file not found: $SKU_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$SKU_FILE"
  set +a
  local required=(
    DOCINT_SKU VPN_GATEWAY_SKU VPN_GATEWAY_GENERATION FUNCTION_PLAN_SKU FUNCTION_RUNTIME
    APIM_SKU APIM_CAPACITY STORAGE_SKU STORAGE_ACCESS_TIER MAX_UPLOAD_MB
    APIM_RATE_LIMIT_CALLS_PER_MIN DEFAULT_MODEL AVAILABLE_MODELS REVIEW_THRESHOLD
  )
  local v missing=()
  for v in "${required[@]}"; do
    [[ -n "${!v:-}" ]] || missing+=("$v")
  done
  (( ${#missing[@]} == 0 )) || die "Missing values in $SKU_FILE: ${missing[*]}"
  [[ "$APIM_SKU" == "Consumption" ]] || die "APIM_SKU=$APIM_SKU is not supported by this repository. Use Consumption."
  case "$VPN_GATEWAY_SKU" in
    VpnGw[1-5]) die "VPN_GATEWAY_SKU=$VPN_GATEWAY_SKU can no longer be created for new gateways. Use ${VPN_GATEWAY_SKU}AZ." ;;
  esac
  [[ "$MAX_UPLOAD_MB" =~ ^[0-9]+$ ]] && (( MAX_UPLOAD_MB >= 1 && MAX_UPLOAD_MB <= 100 )) || die "MAX_UPLOAD_MB must be a whole number from 1 to 100."
  [[ "$FUNCTION_RUNTIME" == Python\|* ]] || die "FUNCTION_RUNTIME must be a Python runtime (for example Python|3.11); the code in functions/ is Python."
}

require_publisher_email() {
  if [[ -z "$APIM_PUBLISHER_EMAIL" && -t 0 && "$ASSUME_YES" != "true" ]]; then
    read -r -p "API Management publisher email: " APIM_PUBLISHER_EMAIL
  fi
  [[ "$APIM_PUBLISHER_EMAIL" == *@*.* ]] || die "Set APIM_PUBLISHER_EMAIL to a valid email address (API Management requires one)."
}

confirm() {
  [[ "$ASSUME_YES" == "true" ]] && return 0
  local ans
  read -r -p "$1 [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]]
}

# deploy_template <name> <param>...   (prints outputs JSON; deployment is named after the template)
deploy_template() {
  local name="$1"; shift
  az deployment group create \
    --name "$name" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_DIR/$name.json" \
    --parameters "$@" \
    --query properties.outputs -o json
}

# deploy_template_nowait <name> <param>...   (starts the deployment and returns at once)
deploy_template_nowait() {
  local name="$1"; shift
  az deployment group create \
    --name "$name" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_DIR/$name.json" \
    --parameters "$@" \
    --no-wait -o none
}

# get_output <json> <jq-path>
get_output() { jq -r "$2" <<<"$1"; }

# deployment_outputs <deployment-name>   (outputs of an earlier deployment in the resource group)
deployment_outputs() {
  az deployment group show --resource-group "$RESOURCE_GROUP" --name "$1" \
    --query properties.outputs -o json 2>/dev/null || die "Deployment '$1' not found in $RESOURCE_GROUP. Run ./deploy.sh first."
}

# make_zip <source-dir> <zip-file>   (uses zip, python, or PowerShell, whichever exists)
make_zip() {
  local src="$1" dest="$2"
  rm -f "$dest"
  if command -v zip >/dev/null 2>&1; then
    (cd "$src" && zip -qr "$dest" . -x '__pycache__' '__pycache__/*' '*/__pycache__/*' '*.pyc' '.venv/*' 'local.settings.json')
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$src" "$dest" <<'PY'
import os, sys, zipfile
src, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".venv")]
        for f in files:
            if f.endswith(".pyc") or f == "local.settings.json":
                continue
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, src))
PY
  elif command -v python >/dev/null 2>&1; then
    python -m zipfile -c "$dest" "$src"/* >/dev/null
  elif command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Compress-Archive -Path '$(cygpath -w "$src" 2>/dev/null || echo "$src")\\*' -DestinationPath '$(cygpath -w "$dest" 2>/dev/null || echo "$dest")' -Force"
  else
    die "Need zip, python, or PowerShell to package the Function app code."
  fi
}

# wait_for_function_key <function-app>   (prints the default host key; retries while the host starts)
wait_for_function_key() {
  local app="$1" key=""
  for _ in $(seq 1 24); do
    key=$(az functionapp keys list --resource-group "$RESOURCE_GROUP" --name "$app" --query "functionKeys.default" -o tsv 2>/dev/null || true)
    if [[ -n "$key" && "$key" != "None" && "$key" != "null" ]]; then echo "$key"; return 0; fi
    sleep 15
  done
  return 1
}
