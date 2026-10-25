"""Deployment scripts against a fake `az` (qa/fakes/az): happy paths, ordering and failure paths.

The scripts run from a temporary copy of Deployment/ whose package.sh is replaced by a stub, so no packaging or
network access happens here (package.sh itself is tested by building the real package in CI and in
test_package_builds below when PACKAGE_TEST=1).
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_AZ = ROOT / "qa" / "fakes" / "az"
SCRIPTS = ["deploy.sh", "deploy_code_arm.sh", "package.sh"]


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(ROOT / "Deployment", tmp_path / "Deployment")
    stub = tmp_path / "Deployment" / "scripts" / "package.sh"
    stub.write_text('#!/usr/bin/env bash\nset -e\nROOT="$(cd "$(dirname "$0")/../.." && pwd)"\n'
                    'mkdir -p "$ROOT/build" && echo zip > "$ROOT/build/webapp.zip"\necho "stub package $*"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy(FAKE_AZ, bindir / "az")
    (bindir / "az").chmod(0o755)
    return tmp_path


def run(repo, script, *args, **env):
    log = repo / "az.log"
    environment = {**os.environ, "PATH": f"{repo / 'bin'}:{os.environ['PATH']}", "FAKE_AZ_LOG": str(log), **env}
    proc = subprocess.run(["bash", str(repo / "Deployment" / "scripts" / script), *args], capture_output=True,
                          text=True, env=environment, timeout=60)
    invocations = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return proc, invocations


def find(invocations, *prefix):
    return [c for c in invocations if c[:len(prefix)] == list(prefix)]


def index(invocations, *prefix):
    return next(i for i, c in enumerate(invocations) if c[:len(prefix)] == list(prefix))


def test_demo_deploys_infra_then_code(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", "--param", "demoPassword=Demo-Pass-1")
    assert proc.returncode == 0, proc.stderr
    create = find(invocations, "deployment", "group", "create")[0]
    assert create[create.index("-g") + 1] == "Vaibhav.Chaudhary" and create[create.index("-n") + 1] == "docintel-demo"
    joined = " ".join(create)
    assert "@" + str(repo / "Deployment/ARM/parameters/demo.parameters.json") in joined
    assert "deployerPrincipalId=deployer-object-id" in joined and "deployerPrincipalType=User" in joined
    assert ("existingAppServicePlanId=/subscriptions/test-sub/resourceGroups/Vaibhav.Chaudhary/providers/"
            "Microsoft.Web/serverfarms/ccai-demo-gqausd-web-plan") in joined
    assert "demoPassword=Demo-Pass-1" in joined
    # the shared plan is looked up, never changed
    assert find(invocations, "appservice", "plan", "show")
    assert not [c for c in invocations if c[:2] == ["appservice", "plan"] and c[2] != "show"]
    # existing resource group reused
    assert not find(invocations, "group", "create")
    # code after infrastructure, through the management API only
    assert index(invocations, "deployment", "group", "create") < index(invocations, "storage", "account", "keys", "list")
    settings = " ".join(find(invocations, "webapp", "config", "appsettings", "set")[0])
    assert "WEBSITE_RUN_FROM_PACKAGE=https://docintdemoabc123st.blob.core.windows.net/code-packages/webapp-" in settings
    assert "SCM_DO_BUILD_DURING_DEPLOYMENT=false" in settings and "PYTHONPATH=/home/site/wwwroot/.packages" in settings
    startup = find(invocations, "webapp", "config", "set")[0]
    assert startup[startup.index("--startup-file") + 1] == (
        "python -m gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 1 --threads 4 config.wsgi")
    sas = find(invocations, "storage", "blob", "generate-sas")[0]
    assert sas[sas.index("--permissions") + 1] == "r" and "--https-only" in sas
    assert find(invocations, "webapp", "restart")
    # nothing that needs Graph, Kudu or data-plane tokens
    forbidden = [c for c in invocations if c[0] in ("ad", "keyvault") or c[:2] == ["webapp", "deploy"]
                 or "--auth-mode" in c or c[:3] == ["functionapp", "deployment", "source"]]
    assert not forbidden
    assert "https://docint-demo-abc123-web.azurewebsites.net" in proc.stdout
    assert "Sign in with the demo password you set" in proc.stdout


def test_missing_plan_stops_before_deploying(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_NO_PLAN="1")
    assert proc.returncode == 1
    assert "App Service plan 'ccai-demo-gqausd-web-plan' was not found" in proc.stderr
    assert not find(invocations, "deployment", "group", "create")


def test_plan_in_another_region_stops(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_PLAN_LOCATION="South India")
    assert proc.returncode == 1 and "same region" in proc.stderr
    assert not find(invocations, "deployment", "group", "create")


def test_unregistered_provider_is_registered(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_UNREGISTERED="Microsoft.CognitiveServices")
    assert proc.returncode == 0, proc.stderr
    reg = find(invocations, "provider", "register")
    assert reg == [["provider", "register", "-n", "Microsoft.CognitiveServices", "--wait", "-o", "none"]]
    checked = {c[3] for c in find(invocations, "provider", "show")}
    assert checked == {"Microsoft.CognitiveServices", "Microsoft.Web", "Microsoft.KeyVault", "Microsoft.Storage",
                       "Microsoft.Insights", "Microsoft.OperationalInsights"}


def test_registration_failure_warns_clearly(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_UNREGISTERED="Microsoft.Web", FAKE_AZ_REGISTER_FAILS="1")
    assert "az provider register -n Microsoft.Web --wait" in proc.stderr
    assert find(invocations, "deployment", "group", "create")  # the deployment itself reports what is missing


def test_private_networking_checks_network_provider(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "prod", "-g", "rg-docint-prod")
    assert proc.returncode == 0, proc.stderr
    assert "Microsoft.Network" in {c[3] for c in find(invocations, "provider", "show")}
    assert not find(invocations, "appservice", "plan", "show")  # prod creates its own plan
    assert "existingAppServicePlanId" not in " ".join(find(invocations, "deployment", "group", "create")[0])


def test_new_resource_group_is_created_when_missing(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "dev", "-g", "rg-docint-dev", "-l", "southindia", FAKE_AZ_GROUP_EXISTS="false")
    assert proc.returncode == 0, proc.stderr
    assert find(invocations, "group", "create") == [["group", "create", "-n", "rg-docint-dev", "-l", "southindia", "-o", "none"]]
    assert "set it once with" in proc.stdout  # no password passed: hint how to set it


def test_not_logged_in(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_NOT_LOGGED_IN="1")
    assert proc.returncode == 1 and "az login" in proc.stderr
    assert not find(invocations, "deployment", "group", "create")


def test_failed_infra_deployment_stops(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", FAKE_AZ_DEPLOY_FAILS="1")
    assert proc.returncode != 0
    assert not find(invocations, "storage", "account", "keys", "list")


def test_skip_infra_and_skip_code(repo):
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", "--skip-infra")
    assert proc.returncode == 0, proc.stderr
    assert not find(invocations, "deployment", "group", "create") and find(invocations, "webapp", "restart")
    proc, invocations = run(repo, "deploy.sh", "-e", "demo", "--skip-code")
    assert proc.returncode == 0
    assert "the app has no code" in proc.stderr
    assert len(find(invocations, "webapp", "restart")) == 1  # the log holds both runs: only the first restarted the app


def test_seed_is_accepted(repo):
    proc, _ = run(repo, "deploy.sh", "-e", "demo", "--skip-infra", "--seed")
    assert proc.returncode == 0 and "sample invoices are part of the web app package" in proc.stdout


def test_code_step_without_shared_keys_explains_prod(repo):
    proc, invocations = run(repo, "deploy_code_arm.sh", "-g", "rg", "-e", "prod", FAKE_AZ_NO_KEY="1")
    assert proc.returncode == 1
    assert "allowSharedKeyAccess" in proc.stderr and "inside the network" in proc.stderr
    assert not find(invocations, "webapp", "config", "appsettings", "set")


def test_code_step_needs_the_infrastructure(repo):
    proc, _ = run(repo, "deploy_code_arm.sh", "-g", "rg", "-e", "demo", FAKE_AZ_NO_DEPLOYMENT="1")
    assert proc.returncode == 1 and "Deploy the infrastructure first" in proc.stderr


def test_code_step_reads_a_named_deployment(repo):
    proc, invocations = run(repo, "deploy_code_arm.sh", "-g", "rg", "-e", "demo", "--deployment", "Microsoft.Template-2026")
    assert proc.returncode == 0, proc.stderr
    shows = find(invocations, "deployment", "group", "show")
    assert shows and all(c[c.index("-n") + 1] == "Microsoft.Template-2026" for c in shows)


def test_old_packages_are_removed(repo):
    names = ",".join(f"webapp-2026101{i}000000.zip" for i in range(5))
    proc, invocations = run(repo, "deploy_code_arm.sh", "-g", "rg", "-e", "demo", FAKE_AZ_PACKAGES=names)
    assert proc.returncode == 0, proc.stderr
    deleted = sorted(c[c.index("-n") + 1] for c in find(invocations, "storage", "blob", "delete"))
    assert deleted == ["webapp-20261010000000.zip", "webapp-20261011000000.zip"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_and_bad_options(repo, script):
    proc = subprocess.run(["bash", str(ROOT / "Deployment/scripts" / script), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0 and "Deployment/scripts/" in proc.stdout
    proc = subprocess.run(["bash", str(ROOT / "Deployment/scripts" / script), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 1 and "Unknown option" in proc.stderr


def test_usage_errors(repo):
    proc, _ = run(repo, "deploy.sh")
    assert proc.returncode == 1 and "Usage" in proc.stderr
    proc, _ = run(repo, "deploy.sh", "-e", "staging")
    assert proc.returncode == 1 and "Parameters file not found" in proc.stderr
    proc, _ = run(repo, "deploy.sh", "-e", "demo", "--param", "noequals")
    assert proc.returncode == 1
    proc, _ = run(repo, "deploy_code_arm.sh", "-e", "demo")
    assert proc.returncode == 1 and "Usage" in proc.stderr


@pytest.mark.parametrize("script", SCRIPTS)
def test_bash_syntax_and_shellcheck(script):
    path = ROOT / "Deployment/scripts" / script
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed")
    proc = subprocess.run(["shellcheck", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


@pytest.mark.skipif(os.environ.get("PACKAGE_TEST") != "1", reason="set PACKAGE_TEST=1 to build the real package")
def test_package_builds(tmp_path):
    import zipfile

    import sys

    proc = subprocess.run(["bash", str(ROOT / "Deployment/scripts/package.sh")], capture_output=True, text=True,
                          timeout=600, env={**os.environ, "PYTHON": sys.executable})
    assert proc.returncode == 0, proc.stderr
    names = zipfile.ZipFile(ROOT / "build/webapp.zip").namelist()
    for must in ("manage.py", "docintel/jobs.py", "Config/fields.yaml", "staticfiles/staticfiles.json",
                 "Data/sample_invoices/inv-01-gst-software.json"):
        assert must in names
