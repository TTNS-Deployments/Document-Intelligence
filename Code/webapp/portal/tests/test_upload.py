import io
import os

from docintel import results
from docintel.config import reset_settings_cache

from .base import WebTestCase


def pdf(pages=1):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


class UploadValidationTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def assertRejected(self, response, code):
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["accepted"], [])
        self.assertEqual(body["rejected"][0]["code"], code)
        self.assertEqual(results.list_summaries(), [])  # nothing stored
        return body["rejected"][0]["message"]

    def test_wrong_type(self):
        self.assertIn("only PDF, JPEG and PNG", self.assertRejected(self.upload(("notes.txt", b"hello")), "type"))
        self.assertRejected(self.upload(("archive.zip", b"PK\x03\x04")), "type")

    def test_wrong_magic_bytes(self):
        msg = self.assertRejected(self.upload(("invoice.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 100)), "content")
        self.assertIn("does not match", msg)
        self.assertRejected(self.upload(("photo.jpg", b"%PDF-1.4 fake")), "content")

    def test_too_large(self):
        os.environ["MAX_UPLOAD_MB"] = "1"
        reset_settings_cache()
        try:
            self.assertRejected(self.upload(("big.pdf", pdf() + b"0" * (1024 * 1024 + 10))), "size")
        finally:
            os.environ.pop("MAX_UPLOAD_MB")
            reset_settings_cache()

    def test_too_many_pages(self):
        self.assertIn("11 pages", self.assertRejected(self.upload(("long.pdf", pdf(11))), "pages"))

    def test_odd_names_are_sanitised(self):
        response = self.upload(("../../evil<script>.pdf", self.sample_bytes()))
        self.assertEqual(response.status_code, 200)
        name = response.json()["accepted"][0]["filename"]
        self.assertNotIn("/", name)
        self.assertNotIn("<", name)
        self.assertTrue(name.endswith(".pdf"))

    def test_batch_with_good_and_bad_files(self):
        response = self.upload(("a.pdf", self.sample_bytes("inv-02-us-logistics")), ("b.txt", b"x"),
                               ("c.png", self.sample_bytes("inv-03-uk-interiors", "png")))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["accepted"]), 2)
        self.assertEqual(len(body["rejected"]), 1)
        self.wait()
        batch = self.client.get("/partials/batch?ids=" + ",".join(d["id"] for d in body["accepted"]))
        self.assertContains(batch, "2 of 2 done")
        self.assertContains(batch, "Export all")
        self.assertNotContains(batch, "hx-trigger")  # polling stops when every job has finished

    def test_no_files_or_too_many(self):
        self.assertEqual(self.client.post("/api/documents", {"model": "prebuilt-invoice"}).status_code, 400)
        files = [(f"f{i}.pdf", pdf()) for i in range(11)]
        response = self.upload(*files)
        self.assertEqual(response.status_code, 400)

    def test_unavailable_model_and_unknown_fields(self):
        r = self.upload(("a.pdf", pdf()), model="prebuilt-businessCard", fields=["Emails"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not available", r.json()["error"])
        r = self.upload(("a.pdf", pdf()), fields=["NoSuchField"])
        self.assertEqual(r.status_code, 400)

    def test_daily_budget_refuses(self):
        os.environ["DAILY_PAGE_LIMIT"] = "2"
        reset_settings_cache()
        r = self.upload(("a.pdf", pdf(2)), ("b.pdf", pdf(1)))
        self.assertEqual(len(r.json()["accepted"]), 1)
        self.assertEqual(r.json()["rejected"][0]["code"], "budget")
        self.assertIn("daily page limit", r.json()["rejected"][0]["message"])

    def test_sample_runs(self):
        r = self.client.post("/api/samples/inv-04-eu-energy", {"fields": ["VendorName", "ServiceStartDate"]})
        self.assertEqual(r.status_code, 200)
        self.wait()
        doc = r.json()["accepted"][0]["id"]
        body = self.client.get(f"/api/documents/{doc}").json()
        self.assertEqual(body["status"], "done")
        self.assertEqual([f["name"] for f in body["view"]["fields"]], ["ServiceStartDate", "VendorName"])
        self.assertEqual(self.client.post("/api/samples/nope").status_code, 404)
