from django.test import Client, override_settings

from .base import WebTestCase


class DemoPasswordTests(WebTestCase):
    def test_wrong_password_gives_403_then_429_after_five(self):
        for _ in range(5):
            response = self.client.post("/auth/login", {"role": "Admin", "password": "nope"})
            self.assertEqual(response.status_code, 403)
        response = self.client.post("/auth/login", {"role": "Admin", "password": "s3cret-demo"})
        self.assertEqual(response.status_code, 429)  # locked even with the right password
        self.assertContains(response, "15 minutes", status_code=429)

    def test_lockout_is_per_client_address(self):
        for _ in range(5):
            self.client.post("/auth/login", {"role": "User", "password": "x"}, HTTP_X_FORWARDED_FOR="203.0.113.7:4431")
        locked = self.client.post("/auth/login", {"role": "User", "password": "s3cret-demo"},
                                  HTTP_X_FORWARDED_FOR="203.0.113.7:5000")
        self.assertEqual(locked.status_code, 429)
        other = Client().post("/auth/login", {"role": "User", "password": "s3cret-demo"},
                              HTTP_X_FORWARDED_FOR="198.51.100.2")
        self.assertEqual(other.status_code, 302)

    def test_right_password_signs_in_with_chosen_role(self):
        for role in ("Admin", "User"):
            client = Client()
            response = client.post("/auth/login", {"role": role, "password": "s3cret-demo"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.session["user"]["role"], role)
            page = client.get("/")
            self.assertContains(page, f'role-{role.lower()}')

    def test_role_must_be_admin_or_user(self):
        response = self.client.post("/auth/login", {"role": "Superuser", "password": "s3cret-demo"})
        self.assertEqual(response.status_code, 400)

    @override_settings(DEMO_PASSWORD="")
    def test_empty_configured_password_refuses_sign_in(self):
        self.assertContains(self.client.get("/auth/login"), "not configured")
        response = self.client.post("/auth/login", {"role": "Admin", "password": ""})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("user", self.client.session)
        self.assertEqual(self.client.get("/").status_code, 302)

    @override_settings(AUTH_MODE="dev")
    def test_dev_mode_needs_no_password(self):
        response = self.client.post("/auth/login", {"role": "User"})
        self.assertEqual(response.status_code, 302)

    def test_unauthenticated_requests_are_redirected_or_401(self):
        response = self.client.get("/history")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/auth/login?next=/history"))
        self.assertEqual(self.client.get("/api/catalog").status_code, 401)
        self.assertEqual(self.client.get("/partials/batch", HTTP_HX_REQUEST="true").status_code, 401)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_sign_out(self):
        self.sign_in()
        response = self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_open_redirect_is_blocked(self):
        response = self.client.post("/auth/login", {"role": "User", "password": "s3cret-demo",
                                                    "next": "https://evil.example/"})
        self.assertEqual(response["Location"], "/")

    def test_session_with_unknown_role_is_not_a_user(self):
        from accounts.roles import User

        self.assertIsNone(User.from_session({"id": "x", "role": "Owner"}))
        self.assertIsNone(User.from_session({"role": "Admin"}))
        self.assertIsNone(User.from_session("Admin"))
        self.assertEqual(User.from_session({"id": "x", "role": "Admin"}).role, "Admin")

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/auth/login", {"role": "User", "password": "s3cret-demo"}).status_code, 403)
        client.get("/auth/login")  # sets the CSRF cookie, as a browser would
        token = client.cookies["csrftoken"].value
        response = client.post("/auth/login", {"role": "User", "password": "s3cret-demo"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.post("/api/documents", {}).status_code, 403)  # no token
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post("/api/documents", {}, HTTP_X_CSRFTOKEN=token).status_code, 400)  # no files
