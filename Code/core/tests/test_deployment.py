"""Static checks that the ARM template, parameter files, portal form, scripts and code agree."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARM = ROOT / "Deployment" / "ARM"
TEMPLATE = json.loads((ARM / "azuredeploy.json").read_text())
PARAM_FILES = sorted((ARM / "parameters").glob("*.parameters.json"))
APP_SETTINGS = {s["name"]: s["value"] for r in TEMPLATE["resources"] if r["type"] == "Microsoft.Web/sites"
                for s in r["properties"]["siteConfig"]["appSettings"]}

# Settings the code reads that the template deliberately does not set (they have safe defaults, or are for
# developer machines only). Anything else the code reads must be an app setting.
OPTIONAL_SETTINGS = {
    "STORAGE_BACKEND", "ANALYZE_BACKEND", "LOCAL_DATA_DIR", "AZURE_STORAGE_CONNECTION_STRING", "DOCINTEL_KEY",
    "MOCK_ANALYZE_DELAY", "WORKER_THREADS", "ANALYZE_MAX_ATTEMPTS", "ANALYZE_RETRY_BASE_SECONDS", "AZURE_CLIENT_ID",
    "DOCINTEL_CONFIG_DIR", "DOCINTEL_DATA_DIR", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS",
    "WEBSITE_HOSTNAME", "DJANGO_SSL_REDIRECT", "CONTENT_SECURITY_POLICY", "LOG_LEVEL", "MAX_FILES_PER_UPLOAD",
}


def code_settings() -> set[str]:
    names = set()
    for path in (ROOT / "Code/core/docintel/config.py", ROOT / "Code/webapp/config/settings.py"):
        names |= set(re.findall(r"""\b_?env(?:_int|_float|_bool|_list)?\(\s*["']([A-Z0-9_]+)["']""", path.read_text()))
    return names


@pytest.mark.parametrize("path", PARAM_FILES, ids=lambda p: p.name)
def test_parameter_files_match_template(path):
    values = json.loads(path.read_text())["parameters"]
    for name, item in values.items():
        assert name in TEMPLATE["parameters"], f"{name} is not a template parameter"
        spec = TEMPLATE["parameters"][name]
        if "allowedValues" in spec:
            assert item["value"] in spec["allowedValues"], f"{name}={item['value']} not in {spec['allowedValues']}"
        if "minValue" in spec:
            assert item["value"] >= spec["minValue"], name
        if "maxValue" in spec:
            assert item["value"] <= spec["maxValue"], name
        kind = {"string": str, "securestring": str, "int": int, "bool": bool, "object": dict}[spec["type"]]
        assert isinstance(item["value"], kind), f"{name} should be {spec['type']}"


def test_ui_definition_outputs_are_parameters():
    ui = json.loads((ARM / "createUiDefinition.json").read_text())
    for name in ui["parameters"]["outputs"]:
        assert name in TEMPLATE["parameters"], name


def test_ui_definition_dropdowns_offer_allowed_values():
    ui = json.loads((ARM / "createUiDefinition.json").read_text())
    elements = list(ui["parameters"]["basics"]) + [e for s in ui["parameters"]["steps"] for e in s["elements"]]
    for e in elements:
        if e["type"] == "Microsoft.Common.DropDown" and e["name"] in TEMPLATE["parameters"]:
            allowed = TEMPLATE["parameters"][e["name"]].get("allowedValues")
            values = [v["value"] for v in e["constraints"]["allowedValues"]]
            if allowed:
                assert set(values) <= set(allowed), e["name"]
            assert e["defaultValue"] in [v["label"] for v in e["constraints"]["allowedValues"]], e["name"]


def test_every_setting_the_code_reads_is_set_by_the_template():
    missing = sorted(code_settings() - set(APP_SETTINGS) - OPTIONAL_SETTINGS)
    assert not missing, f"read by the code but not set in azuredeploy.json: {missing}"
    for name in ("DOCINTEL_MODE", "DJANGO_SECRET_KEY", "AUTH_MODE", "DEMO_PASSWORD", "AZURE_STORAGE_ACCOUNT_URL",
                 "CONTAINER_UPLOADS", "CONTAINER_RESULTS", "CONTAINER_CONFIG", "DOCINTEL_ENDPOINT",
                 "DOCINTEL_API_VERSION", "MAX_UPLOAD_MB", "MAX_PAGES", "DAILY_PAGE_LIMIT", "REVIEW_THRESHOLD",
                 "RETENTION_DAYS", "DISPLAY_TIME_ZONE", "APPLICATIONINSIGHTS_CONNECTION_STRING",
                 "SCM_DO_BUILD_DURING_DEPLOYMENT", "ENVIRONMENT_NAME"):
        assert name in APP_SETTINGS, name
    assert APP_SETTINGS["DOCINTEL_MODE"] == "azure"
    assert APP_SETTINGS["DOCINTEL_API_VERSION"] == "2024-11-30"
    assert APP_SETTINGS["SCM_DO_BUILD_DURING_DEPLOYMENT"] == "false"
    for secret in ("DJANGO_SECRET_KEY", "DEMO_PASSWORD"):
        assert APP_SETTINGS[secret].startswith("[format('@Microsoft.KeyVault("), secret
    assert not any("key" in n.lower() and "KeyVault" not in str(v) and n != "DJANGO_SECRET_KEY"
                   for n, v in APP_SETTINGS.items() if n.endswith("_KEY")), "no service keys in app settings"


def test_template_settings_match_code_defaults():
    from docintel.config import Settings

    containers = TEMPLATE["variables"]["containers"]
    for name in (Settings.container_uploads, Settings.container_results, Settings.container_config, "code-packages"):
        assert name in containers


def test_outputs_and_resources():
    assert {"webAppName", "webAppUrl", "storageAccountName", "keyVaultName", "docIntelEndpoint"} <= set(TEMPLATE["outputs"])
    types = {r["type"] for r in TEMPLATE["resources"]}
    for t in ("Microsoft.KeyVault/vaults", "Microsoft.Storage/storageAccounts", "Microsoft.Storage/storageAccounts/managementPolicies",
              "Microsoft.OperationalInsights/workspaces", "Microsoft.Insights/components", "Microsoft.CognitiveServices/accounts",
              "Microsoft.Web/serverfarms", "Microsoft.Web/sites", "Microsoft.Authorization/roleAssignments",
              "Microsoft.Network/privateEndpoints", "Microsoft.Network/privateDnsZones"):
        assert t in types, t
    forbidden = {"Microsoft.Network/virtualNetworkGateways", "Microsoft.Network/vpnGateways", "Microsoft.ApiManagement/service",
                 "Microsoft.Network/connections", "Microsoft.Network/localNetworkGateways"}
    assert not types & forbidden
    sites = [r for r in TEMPLATE["resources"] if r["type"] == "Microsoft.Web/sites"]
    assert len(sites) == 1 and "functionapp" not in sites[0]["kind"]


def test_web_app_hardening_and_shared_plan():
    site = next(r for r in TEMPLATE["resources"] if r["type"] == "Microsoft.Web/sites")
    props, cfg = site["properties"], site["properties"]["siteConfig"]
    assert props["httpsOnly"] is True and cfg["ftpsState"] == "Disabled" and cfg["minTlsVersion"] == "1.2"
    assert cfg["linuxFxVersion"] == "PYTHON|3.12" and site["identity"]["type"] == "SystemAssigned"
    assert "--workers 1 --threads 4" in cfg["appCommandLine"]
    assert props["serverFarmId"] == "[variables('planId')]"
    plan = next(r for r in TEMPLATE["resources"] if r["type"] == "Microsoft.Web/serverfarms")
    assert plan["condition"] == "[variables('createPlan')]"  # created only without an existing plan, never modified
    assert TEMPLATE["variables"]["createPlan"] == "[empty(parameters('existingAppServicePlanId'))]"


def test_lifecycle_policy_deletes_uploads_and_results():
    policy = next(r for r in TEMPLATE["resources"] if r["type"].endswith("managementPolicies"))
    rule = policy["properties"]["policy"]["rules"][0]["definition"]
    assert rule["filters"]["prefixMatch"] == ["uploads/", "results/"]
    assert rule["actions"]["baseBlob"]["delete"]["daysAfterCreationGreaterThan"] == "[parameters('retentionDays')]"


def test_role_assignments():
    roles = TEMPLATE["variables"]["roles"]
    assigned = [r for r in TEMPLATE["resources"] if r["type"] == "Microsoft.Authorization/roleAssignments"]
    web = {r["name"].split("variables('roles').")[1].rstrip(")]") for r in assigned if "'web'" in r["name"]}
    assert web == {"blobContributor", "cognitiveUser", "kvSecretsUser"}
    deployer = [r for r in assigned if "'deployer'" in r["name"]]
    assert len(deployer) == 2 and all(r["condition"] == "[not(empty(parameters('deployerPrincipalId')))]" for r in deployer)
    assert roles["cognitiveUser"] == "a97b65f3-24c7-4388-baec-2e87135dc908"


def test_demo_password_secret_only_when_given():
    secret = next(r for r in TEMPLATE["resources"] if r["type"] == "Microsoft.KeyVault/vaults/secrets" and "demo-password" in r["name"])
    assert secret["condition"] == "[not(empty(parameters('demoPassword')))]"
    assert TEMPLATE["parameters"]["demoPassword"]["type"] == "securestring"
    assert TEMPLATE["parameters"]["demoPassword"]["defaultValue"] == ""


def test_environment_choices():
    load = lambda n: {k: v["value"] for k, v in json.loads((ARM / "parameters" / f"{n}.parameters.json").read_text())["parameters"].items()}
    demo, dev, prod = load("demo"), load("dev"), load("prod")
    assert demo["docIntelSku"] == "S0" and demo["docIntelLocation"] == "centralindia" and demo["retentionDays"] == 7
    assert demo["privateNetworking"] is False and demo["authMode"] == "password" and demo["existingAppServicePlanId"] == ""
    assert demo["logAnalyticsRetentionDays"] == 30 and demo["logAnalyticsDailyQuotaGb"] == 1
    assert demo["tags"] == {"owner": "TTNS", "project": "document-intelligence", "purpose": "demo"}
    assert dev["retentionDays"] == 30 and dev["webAppSku"] == "B1"
    assert prod["privateNetworking"] is True and prod["allowSharedKeyAccess"] is False and prod["retentionDays"] == 90
    assert prod["webAppSku"] in ("P0v3", "S1")
    env = (ROOT / "Deployment/environments/demo.env").read_text()
    assert 'EXISTING_PLAN_NAME="ccai-demo-gqausd-web-plan"' in env and 'RESOURCE_GROUP="Vaibhav.Chaudhary"' in env


def tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for name in out:
        p = ROOT / name
        if p.suffix.lower() in {".png", ".pdf", ".jpg", ".xlsx", ".pfb", ".ttf", ".gz"} or not p.is_file():
            continue
        if "/vendor/" in f"/{name}" or name.endswith("test_deployment.py"):  # vendored code; this file's own patterns
            continue
        yield name, p.read_text(errors="ignore")


def test_no_secrets_or_subscription_ids_in_repository():
    known_roles = set(TEMPLATE["variables"]["roles"].values())
    for name, text in tracked_text_files():
        assert not re.search(r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-", text), f"subscription ID in {name}"
        for guid in re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", text):
            assert guid in known_roles, f"unexpected GUID {guid} in {name}"
        assert not re.search(r"AccountKey=(?!Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==)",
                             text), f"storage key in {name}"
        assert not re.search(r"[A-Za-z0-9._%+-]+@(?!example\.|.*\.example\b)[A-Za-z0-9-]+\.[a-z]{2,}", text) or \
            name.endswith((".mjs", ".js")), f"e-mail address in {name}"
