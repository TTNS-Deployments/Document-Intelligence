import os
import shutil
import tempfile

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from docintel.config import reset_settings_cache
from docintel.factory import get_job_runner


@override_settings(AUTH_MODE="password", DEMO_PASSWORD="s3cret-demo")
class WebTestCase(SimpleTestCase):
    """Local mode against a fresh data folder per test, mock analyzer without delay, demo password set."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = {k: os.environ.get(k) for k in ("LOCAL_DATA_DIR", "MOCK_ANALYZE_DELAY",
                                                    "ANALYZE_RETRY_BASE_SECONDS", "DAILY_PAGE_LIMIT")}
        os.environ.update(LOCAL_DATA_DIR=self.tmp, MOCK_ANALYZE_DELAY="0", ANALYZE_RETRY_BASE_SECONDS="0")
        os.environ.pop("DAILY_PAGE_LIMIT", None)
        reset_settings_cache()
        cache.clear()

    def tearDown(self):
        get_job_runner().wait_idle(10)
        reset_settings_cache()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sign_in(self, role="User", client=None):
        client = client or self.client
        response = client.post("/auth/login", {"role": role, "password": "s3cret-demo"})
        self.assertEqual(response.status_code, 302)
        return client

    def wait(self):
        self.assertTrue(get_job_runner().wait_idle(20))

    def sample_bytes(self, sample_id="inv-01-gst-software", variant="pdf"):
        from docintel import samples

        return samples.sample_path(samples.get_sample(sample_id), variant).read_bytes()

    def upload(self, *files, model="prebuilt-invoice", fields=("VendorName", "InvoiceId", "PurchaseOrder",
                                                                "InvoiceTotal", "Items")):
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = {"model": model, "fields": list(fields),
                "files": [SimpleUploadedFile(name, content) for name, content in files]}
        return self.client.post("/api/documents", data)

    def analysed(self, role="User"):
        """Sign in, upload sample 1 and wait until it is analysed. Returns the document ID."""
        self.sign_in(role)
        response = self.upload(("inv-01-gst-software.pdf", self.sample_bytes()))
        self.assertEqual(response.status_code, 200, response.content)
        self.wait()
        return response.json()["accepted"][0]["id"]
