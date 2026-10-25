"""Fixtures for the UI tests: a live web app in local mode (mock Document Intelligence, folder storage) on a free
port with an empty data folder, and a headless Chromium page that records console errors."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "qa-demo-password"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    port = _free_port()
    data = tempfile.mkdtemp(prefix="docintel-qa-")
    env = {**os.environ, "DOCINTEL_MODE": "local", "LOCAL_DATA_DIR": data, "AUTH_MODE": "password",
           "DEMO_PASSWORD": PASSWORD, "MOCK_ANALYZE_DELAY": "0.6", "ANALYZE_RETRY_BASE_SECONDS": "0",
           "DJANGO_DEBUG": "false", "ENVIRONMENT_NAME": "qa", "RETENTION_DAYS": "7"}
    proc = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
                            cwd=ROOT / "Code/webapp", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("the web app did not start")
    yield url
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, server, request):
    # The app's CSP forbids eval and inline scripts; Playwright's wait_for_function and the axe-core injection need
    # them, so test contexts bypass the CSP. test_U25 runs the main flow with the CSP enforced.
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True, base_url=server,
                                  bypass_csp=True)
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server)
    pg = context.new_page()
    pg.console_errors = []
    pg.on("console", lambda m: pg.console_errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.console_errors.append(str(e)))
    pg.set_default_timeout(15000)
    yield pg
    errors = [e for e in pg.console_errors if "status of 4" not in e]  # expected 4xx responses are tested explicitly
    context.close()
    if not getattr(request.node, "allow_console_errors", False):
        assert not errors, f"console errors: {errors}"


def sign_in(page, role="User", password=PASSWORD):
    page.goto("/auth/login")
    page.check(f"input[name=role][value={role}]")
    page.fill("#password", password)
    page.click("button[type=submit]")
    if password == PASSWORD:
        page.wait_for_url("**/")
    return page


def sample_path(sample_id, variant="pdf"):
    ext = "pdf" if variant == "pdf" else "png"
    return str(ROOT / "Data/sample_invoices" / f"{sample_id}.{ext}")
