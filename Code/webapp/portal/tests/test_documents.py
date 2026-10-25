import csv
import io
import json

from django.test import Client
from openpyxl import load_workbook

from docintel import results

from .base import WebTestCase


class ResultTests(WebTestCase):
    def test_result_json_and_review_page(self):
        doc = self.analysed()
        body = self.client.get(f"/api/documents/{doc}").json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["view"]["api_version"], "2024-11-30")
        names = [f["name"] for f in body["view"]["fields"]]
        self.assertEqual(names, ["InvoiceId", "PurchaseOrder", "VendorName", "InvoiceTotal"])
        page = self.client.get(f"/documents/{doc}")
        self.assertContains(page, "prebuilt-invoice")
        self.assertContains(page, "API 2024-11-30")
        self.assertContains(page, "of 5</strong> fields need review")  # PurchaseOrder is a low-confidence field
        self.assertContains(page, "chip-review")
        self.assertContains(page, "Line items")

    def test_original_file_streams(self):
        doc = self.analysed()
        response = self.client.get(f"/api/documents/{doc}/file")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(b"".join(response.streaming_content), self.sample_bytes())

    def test_not_found_field_is_shown(self):
        doc = self.analysed()
        response = self.client.post(f"/documents/{doc}/selection", {"fields": ["VendorName", "ShippingAddress"]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not found")
        self.assertContains(response, 'hx-swap-oob="true"')  # the summary strip is updated too
        self.assertEqual(results.get(doc)["selection"], ["VendorName", "ShippingAddress"])
        self.assertEqual(self.client.post(f"/documents/{doc}/selection", {"fields": ["Bogus"]}).status_code, 400)

    def test_edit_keeps_model_value_and_marks_reviewed(self):
        doc = self.analysed()
        r = self.client.post(f"/documents/{doc}/edit", {"path": "PurchaseOrder", "value": "PO-MRV-7782"})
        self.assertContains(r, "PO-MRV-7782")
        self.assertContains(r, "Model value: PO-MRV-7781")
        record = results.get(doc)
        self.assertEqual(record["edits"]["PurchaseOrder"]["value"], "PO-MRV-7782")
        self.assertEqual(record["edits"]["PurchaseOrder"]["by"], "User")
        self.assertIn("PurchaseOrder", record["reviewed"])
        r = self.client.post(f"/documents/{doc}/edit", {"path": "Items[1].Amount", "value": "61000"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f"/documents/{doc}/edit", {"path": "PurchaseOrder", "revert": "1"})
        self.assertNotIn("PurchaseOrder", results.get(doc)["edits"])
        for bad in ({"path": "Items", "value": "x"}, {"path": "../x", "value": "x"}, {"path": "InvoiceId", "value": "x" * 2001}):
            self.assertEqual(self.client.post(f"/documents/{doc}/edit", bad).status_code, 400)

    def test_mark_reviewed_and_all(self):
        doc = self.analysed()
        r = self.client.post(f"/documents/{doc}/reviewed", {"path": "PurchaseOrder", "reviewed": "1"})
        self.assertContains(r, "Reviewed")
        r = self.client.post(f"/documents/{doc}/reviewed", {"all": "1"})
        self.assertContains(r, "No fields need review")
        self.assertEqual(results.summary(doc)["review_count"], 0)

    def test_exports_download_and_open(self):
        doc = self.analysed()
        self.client.post(f"/documents/{doc}/edit", {"path": "InvoiceId", "value": "ASS/2026-27/0143"})
        r = self.client.get(f"/api/documents/{doc}/export.json")
        self.assertIn("attachment", r["Content-Disposition"])
        data = json.loads(r.content)
        self.assertEqual(data["fields"]["InvoiceId"]["value"], "ASS/2026-27/0143")
        self.assertTrue(data["fields"]["InvoiceId"]["edited"])
        r = self.client.get(f"/api/documents/{doc}/export.csv")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][rows[0].index("Invoice number")], "ASS/2026-27/0143")
        r = self.client.get(f"/api/documents/{doc}/export.xlsx")
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ["Documents", "Line items", "Details"])
        self.assertEqual(wb["Line items"].max_row, 4)  # header + 3 lines

    def test_bulk_export(self):
        self.sign_in()
        ids = []
        for sid in ("inv-02-us-logistics", "inv-06-au-consulting"):
            ids.append(self.upload((f"{sid}.pdf", self.sample_bytes(sid))).json()["accepted"][0]["id"])
        self.wait()
        r = self.client.get("/api/export.xlsx?ids=" + ",".join(ids))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(load_workbook(io.BytesIO(r.content))["Documents"].max_row, 3)
        self.assertEqual(self.client.get("/api/export.csv?ids=").status_code, 400)
        self.assertEqual(self.client.get("/api/export.csv?ids=0123456789abcdef").status_code, 409)

    def test_history_lists_and_filters(self):
        doc = self.analysed()
        page = self.client.get("/history")
        self.assertContains(page, "inv-01-gst-software.pdf")
        self.assertContains(page, "after 7 days")  # retention note
        partial = self.client.get("/history?q=nomatch", HTTP_HX_REQUEST="true")
        self.assertContains(partial, "No documents match")
        self.assertNotContains(partial, "<html")
        self.assertContains(self.client.get("/history?status=done&review=1&mine=1"), doc)
        self.assertNotContains(self.client.get("/history?model=prebuilt-receipt"), doc)

    def test_owner_and_admin_can_delete_others_cannot(self):
        doc = self.analysed("User")
        other = Client()
        self.sign_in("User", client=other)
        r = other.post(f"/api/documents/{doc}/delete")
        self.assertEqual(r.status_code, 403)
        admin = Client()
        self.sign_in("Admin", client=admin)
        self.assertEqual(admin.post(f"/api/documents/{doc}/delete").status_code, 200)
        self.assertEqual(self.client.get(f"/api/documents/{doc}").status_code, 404)
        doc = self.analysed("User")
        self.assertEqual(self.client.post(f"/api/documents/{doc}/delete").status_code, 200)  # own document
        self.assertEqual(self.client.get(f"/api/documents/{doc}/file").status_code, 404)

    def test_failed_document_and_retry(self):
        self.sign_in()
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, "DOCINTEL-MOCK-FAIL")
        c.save()
        doc = self.upload(("broken.pdf", buf.getvalue())).json()["accepted"][0]["id"]
        self.wait()
        page = self.client.get(f"/partials/review/{doc}")
        self.assertContains(page, "could not be analysed")
        self.assertContains(page, "data-retry")
        r = self.client.post(f"/api/documents/{doc}/retry")
        self.assertEqual(r.status_code, 200)
        self.wait()
        self.assertEqual(results.get(doc)["status"], "failed")
        doc2 = self.analysed()
        self.assertEqual(self.client.post(f"/api/documents/{doc2}/retry").status_code, 409)

    def test_pending_review_polls(self):
        from docintel import jobs

        self.sign_in()
        record = jobs.submit_file("x.pdf", self.sample_bytes(), model_id="prebuilt-invoice", fields=["VendorName"],
                                  owner="o", owner_role="User", start=False)
        page = self.client.get(f"/partials/review/{record['id']}")
        self.assertContains(page, 'hx-trigger="every 1500ms"')
        self.assertContains(page, "Queued")


class SettingsPageTests(WebTestCase):
    def test_admin_changes_settings_and_presets(self):
        self.sign_in("Admin")
        r = self.client.post("/settings", {"review_threshold": "0.95", "daily_page_limit": "50", "max_pages": "5"},
                             follow=True)
        self.assertContains(r, "Settings saved")
        self.assertContains(r, 'value="0.95"')
        r = self.client.post("/settings", {"review_threshold": "3", "daily_page_limit": "50", "max_pages": "5"},
                             follow=True)
        self.assertContains(r, "between")
        r = self.client.post("/api/presets/prebuilt-invoice", {"name": "Quick check", "fields": ["VendorName", "AmountDue"]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("quick-check", [p["id"] for p in r.json()["presets"]])
        catalog = self.client.get("/api/catalog").json()
        invoice = next(m for m in catalog["models"] if m["id"] == "prebuilt-invoice")
        self.assertIn("Quick check", [p["name"] for p in invoice["presets"]])
        r = self.client.post("/api/presets/prebuilt-invoice/quick-check/delete")
        self.assertNotIn("quick-check", [p["id"] for p in r.json()["presets"]])
        self.assertEqual(self.client.post("/api/presets/prebuilt-invoice", {"name": "", "fields": ["X"]}).status_code, 400)


class StaticFilesTests(WebTestCase):
    def test_collectstatic_with_production_storage(self):
        """Packaging runs collectstatic with the hashed manifest storage: it must succeed."""
        import shutil
        import tempfile

        from django.core.management import call_command
        from django.test import override_settings

        tmp = tempfile.mkdtemp()
        try:
            with override_settings(STATIC_ROOT=tmp, STORAGES={"staticfiles": {
                    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}):
                call_command("collectstatic", interactive=False, verbosity=0)
                from django.contrib.staticfiles.storage import staticfiles_storage

                for name in ("css/app.css", "js/app.js", "js/review.js", "vendor/htmx-2.0.10.min.js",
                             "vendor/pdfjs-5.4.624/pdf.min.mjs"):
                    self.assertRegex(staticfiles_storage.url(name), r"\.[0-9a-f]{12}\.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
