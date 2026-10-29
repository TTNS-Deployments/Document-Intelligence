"""Role protection for every route: each view declares a permission, Users cannot reach Admin pages or APIs."""

from django.urls import get_resolver

from .base import WebTestCase

ADMIN_ONLY = {"settings", "api_preset_save", "api_preset_delete"}
ADMIN_DELETE = {"api_batch_delete"}


def portal_patterns():
    resolver = get_resolver()
    for pattern in resolver.url_patterns:
        if getattr(pattern, "app_name", None) == "portal" or getattr(pattern, "namespace", None) == "portal":
            yield from pattern.url_patterns


class RouteProtectionTests(WebTestCase):
    def test_every_portal_route_declares_a_permission(self):
        names = set()
        for p in portal_patterns():
            names.add(p.name)
            permission = getattr(p.callback, "required_permission", None)
            self.assertIsNotNone(permission, f"{p.name} has no role check")
            expected = "manage_settings" if p.name in ADMIN_ONLY else "delete_any" if p.name in ADMIN_DELETE else "extract"
            self.assertEqual(permission, expected, p.name)
        self.assertGreaterEqual(len(names), 18)

    def test_user_cannot_reach_admin_pages_or_apis(self):
        self.sign_in("User")
        self.assertEqual(self.client.get("/settings").status_code, 403)
        self.assertEqual(self.client.post("/settings", {"review_threshold": "0.1"}).status_code, 403)
        response = self.client.post("/api/presets/prebuilt-invoice", {"name": "Mine", "fields": ["VendorName"]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "You do not have access to this.")
        self.assertEqual(self.client.post("/api/presets/prebuilt-invoice/ap-basics/delete").status_code, 403)
        self.assertNotContains(self.client.get("/"), 'href="/settings"')

    def test_admin_reaches_everything(self):
        self.sign_in("Admin")
        for url in ("/", "/batches", "/history", "/settings", "/api/catalog"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get("/"), 'href="/settings"')

    def test_security_headers(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client.get("/api/catalog")["Cache-Control"], "no-store")

    def test_pages_have_no_inline_scripts(self):
        """The CSP allows only scripts from /static, so templates must not contain inline code."""
        import re

        self.sign_in("Admin")
        doc = self.analysed("Admin")
        for url in ("/", "/batches", "/history", "/settings", f"/documents/{doc}", f"/partials/review/{doc}"):
            html = self.client.get(url).content.decode()
            for tag in re.findall(r"<script\b[^>]*>", html):
                self.assertTrue("src=" in tag or 'type="application/json"' in tag, f"{url}: {tag}")
            self.assertNotRegex(html, r"\son(click|load|change|submit)=", url)

    def test_unknown_document_is_404(self):
        self.sign_in()
        self.assertEqual(self.client.get("/documents/0123456789abcdef").status_code, 404)
        self.assertEqual(self.client.get("/api/documents/0123456789abcdef").status_code, 404)
        self.assertEqual(self.client.get("/documents/../../etc").status_code, 404)
