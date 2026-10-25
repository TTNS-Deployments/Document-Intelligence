#!/usr/bin/env bash
# One-command deployment: infrastructure (ARM) and then the application code, with management-API calls only.
#
#   Deployment/scripts/deploy.sh -e <environment> [options]
#
#   -e, --environment      demo | dev | test | uat | prod: uses Deployment/ARM/parameters/<env>.parameters.json [required]
#                          and, if present, Deployment/environments/<env>.env (resource group, region, shared plan)
#   -g, --resource-group   resource group (default RESOURCE_GROUP from the env file). Reused if it exists.
#   -l, --location         region for a new resource group (default LOCATION from the env file, else centralindia)
#   -s, --subscription     subscription ID or name (default: the current az account)
#       --param name=value extra ARM parameter, repeatable, e.g. --param demoPassword='...'
#       --skip-infra       only deploy the code
#       --skip-code        only deploy the infrastructure (the web app then has no code until the code step runs)
#       --seed             accepted for compatibility; nothing to do (the sample invoices ship inside the package)
#   -h, --help             show this help
#
# Works in Azure Cloud Shell, where only management (ARM) tokens are available: no Microsoft Graph, Kudu, Storage
# or Key Vault data-plane calls. The deploying identity needs Owner (or Contributor + User Access Administrator)
# on the resource group, because the template creates role assignments.
set -euo pipefail

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$ROOT/Deployment/scripts"
RG="" ENV="" LOCATION="" SUBSCRIPTION="" SKIP_INFRA=0 SKIP_CODE=0
EXTRA_PARAMS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--environment) ENV="${2:-}"; shift 2 ;;
    -g|--resource-group) RG="${2:-}"; shift 2 ;;
    -l|--location) LOCATION="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    --param) [[ "${2:-}" == *=* ]] || { echo "--param needs name=value" >&2; exit 1; }; EXTRA_PARAMS+=("$2"); shift 2 ;;
    --skip-infra) SKIP_INFRA=1; shift ;;
    --skip-code) SKIP_CODE=1; shift ;;
    --seed) echo "Note: --seed is not needed: the sample invoices are part of the web app package."; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option $1 (see --help)" >&2; exit 1 ;;
  esac
done
[[ -n "$ENV" ]] || { echo "Usage: $0 -e <environment> [options]  (see --help)" >&2; exit 1; }
[[ "$ENV" =~ ^[a-z0-9]+$ ]] || { echo "Invalid environment name: $ENV" >&2; exit 1; }

PARAMS="$ROOT/Deployment/ARM/parameters/$ENV.parameters.json"
[[ -f "$PARAMS" ]] || { echo "Parameters file not found: $PARAMS" >&2; exit 1; }

# Per-environment variables. Command-line options win.
EXISTING_PLAN_NAME="" EXISTING_PLAN_RESOURCE_GROUP=""
ENV_FILE="$ROOT/Deployment/environments/$ENV.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "Using variables from Deployment/environments/$ENV.env"
  CLI_RG="$RG" CLI_LOCATION="$LOCATION" CLI_SUBSCRIPTION="$SUBSCRIPTION"
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  RG="${CLI_RG:-${RESOURCE_GROUP:-}}"
  LOCATION="${CLI_LOCATION:-${LOCATION:-}}"
  SUBSCRIPTION="${CLI_SUBSCRIPTION:-${AZURE_SUBSCRIPTION:-}}"
fi
LOCATION="${LOCATION:-centralindia}"
[[ -n "$RG" ]] || { echo "No resource group: pass -g or set RESOURCE_GROUP in Deployment/environments/$ENV.env" >&2; exit 1; }

command -v az >/dev/null 2>&1 || { echo "The Azure CLI (az) is required. Use Azure Cloud Shell or install it." >&2; exit 1; }
if [[ -n "$SUBSCRIPTION" ]]; then az account set --subscription "$SUBSCRIPTION"; fi
if ! ACCOUNT="$(az account show --query name -o tsv 2>/dev/null)"; then
  echo "Not signed in to Azure. Run 'az login' (Cloud Shell is signed in already)." >&2
  exit 1
fi
echo "Subscription: $ACCOUNT"

param_value() {  # value of a parameter in the parameters file (empty if missing)
  python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))["parameters"].get(sys.argv[2],{}).get("value",""); print(str(v).lower() if isinstance(v,bool) else v)' "$PARAMS" "$1"
}
extra_value() {  # value given with --param name=value (empty if not given)
  local p
  for p in "${EXTRA_PARAMS[@]+"${EXTRA_PARAMS[@]}"}"; do
    if [[ "${p%%=*}" == "$1" ]]; then echo "${p#*=}"; fi
  done
}

# Object ID of the signed-in identity without Microsoft Graph: decode "oid" from the ARM access token.
oid_from_token() {
  az account get-access-token --query accessToken -o tsv 2>/dev/null | python3 -c '
import base64, json, sys
part = sys.stdin.read().strip().split(".")[1]
part += "=" * (-len(part) % 4)
print(json.loads(base64.urlsafe_b64decode(part)).get("oid", ""))' 2>/dev/null || true
}

DEPLOYMENT="docintel-$ENV"
if [[ $SKIP_INFRA -eq 0 ]]; then
  if [[ "$(az group exists -n "$RG")" == "true" ]]; then
    echo "==> Using existing resource group $RG ($(az group show -n "$RG" --query location -o tsv))"
  else
    echo "==> Creating resource group $RG ($LOCATION)"
    az group create -n "$RG" -l "$LOCATION" -o none
  fi

  NAMESPACES=(Microsoft.CognitiveServices Microsoft.Web Microsoft.KeyVault Microsoft.Storage Microsoft.Insights
              Microsoft.OperationalInsights)
  PRIVATE="$(extra_value privateNetworking)"
  PRIVATE="${PRIVATE:-$(param_value privateNetworking)}"
  if [[ "$PRIVATE" == "true" ]]; then NAMESPACES+=(Microsoft.Network); fi
  for ns in "${NAMESPACES[@]}"; do
    state="$(az provider show -n "$ns" --query registrationState -o tsv 2>/dev/null || echo unknown)"
    if [[ "$state" != "Registered" ]]; then
      echo "==> Resource provider $ns is '$state': registering it"
      if ! az provider register -n "$ns" --wait -o none; then
        echo "WARNING: could not register $ns. Ask a subscription Owner or Contributor to run:" >&2
        echo "         az provider register -n $ns --wait" >&2
      fi
    fi
  done

  DEPLOYER_ID="$(oid_from_token)"
  if [[ "$(az account show --query user.type -o tsv 2>/dev/null)" == "servicePrincipal" ]]; then
    DEPLOYER_TYPE="ServicePrincipal"
  else
    DEPLOYER_TYPE="User"
  fi
  if [[ -n "$DEPLOYER_ID" ]]; then
    echo "Deploying identity: $DEPLOYER_ID ($DEPLOYER_TYPE)"
  else
    echo "Note: could not read the deploying identity from the token; skipping its data-access role assignments."
  fi

  PLAN_ARGS=()
  if [[ -n "$EXISTING_PLAN_NAME" ]]; then
    PLAN_RG="${EXISTING_PLAN_RESOURCE_GROUP:-$RG}"
    echo "==> Looking up the shared App Service plan $EXISTING_PLAN_NAME in $PLAN_RG"
    if ! PLAN_ID="$(az appservice plan show -g "$PLAN_RG" -n "$EXISTING_PLAN_NAME" --query id -o tsv 2>/dev/null)" || [[ -z "$PLAN_ID" ]]; then
      echo "ERROR: App Service plan '$EXISTING_PLAN_NAME' was not found in resource group '$PLAN_RG'." >&2
      echo "       Check EXISTING_PLAN_NAME and EXISTING_PLAN_RESOURCE_GROUP in Deployment/environments/$ENV.env," >&2
      echo "       or clear EXISTING_PLAN_NAME to create a new plan. Nothing was deployed." >&2
      exit 1
    fi
    PLAN_LOCATION="$(az appservice plan show -g "$PLAN_RG" -n "$EXISTING_PLAN_NAME" --query location -o tsv | tr -d ' ' | tr '[:upper:]' '[:lower:]')"
    WANT_LOCATION="$(extra_value location)"
    WANT_LOCATION="${WANT_LOCATION:-$(param_value location)}"
    if [[ -n "$WANT_LOCATION" && "$PLAN_LOCATION" != "$WANT_LOCATION" ]]; then
      echo "ERROR: the shared plan is in '$PLAN_LOCATION' but the web app would go to '$WANT_LOCATION'." >&2
      echo "       A web app must be in the same region as its plan. Nothing was deployed." >&2
      exit 1
    fi
    echo "    using $EXISTING_PLAN_NAME (not modified)"
    PLAN_ARGS=(existingAppServicePlanId="$PLAN_ID")
  fi

  echo "==> Deploying infrastructure ($DEPLOYMENT) with $(basename "$PARAMS")"
  az deployment group create -g "$RG" -n "$DEPLOYMENT" \
    --template-file "$ROOT/Deployment/ARM/azuredeploy.json" \
    --parameters @"$PARAMS" \
    --parameters deployerPrincipalId="$DEPLOYER_ID" deployerPrincipalType="$DEPLOYER_TYPE" \
    ${PLAN_ARGS[@]+"${PLAN_ARGS[@]}"} \
    ${EXTRA_PARAMS[@]+--parameters "${EXTRA_PARAMS[@]}"} \
    -o none
fi

if [[ $SKIP_CODE -eq 0 ]]; then
  # Always after the infrastructure step: an infrastructure deployment resets the app settings, including
  # WEBSITE_RUN_FROM_PACKAGE, so the code has to be pointed at again.
  "$SCRIPTS/deploy_code_arm.sh" -g "$RG" -e "$ENV"
elif [[ $SKIP_INFRA -eq 0 ]]; then
  echo "WARNING: --skip-code: the infrastructure deployment reset the web app settings, so the app has no code" >&2
  echo "         until you run: Deployment/scripts/deploy.sh -e $ENV --skip-infra" >&2
fi

WEB_URL="$(az deployment group show -g "$RG" -n "$DEPLOYMENT" --query properties.outputs.webAppUrl.value -o tsv 2>/dev/null || true)"
echo
echo "Done. Web app: ${WEB_URL:-(see the deployment outputs)}"
AUTH_MODE="$(extra_value authMode)"
AUTH_MODE="${AUTH_MODE:-$(param_value authMode)}"
if [[ "${AUTH_MODE:-password}" == "password" ]]; then
  if [[ -n "$(extra_value demoPassword)" ]]; then
    echo "Sign in with the demo password you set, and choose Admin or User."
  else
    echo "Sign in with the demo password, and choose Admin or User. If no password was set yet, the sign-in page"
    echo "says 'not configured': set it once with  Deployment/scripts/deploy.sh -e $ENV --param demoPassword='<password>'"
  fi
fi
