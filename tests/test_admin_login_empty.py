
"""Regression tests: the Admin Login page must ALWAYS open with empty
Email and Password fields.

Root cause these tests lock in: browser password managers (Chrome/Edge
built-in) key saved credentials to the site origin, ignore
autocomplete="off", and silently inject the last-saved
username+password pair into any page that ships a native
<input type="password"> at load time. The fix renders the password
field as a masked plain-text input (no password input exists at load)
and clears every restored/autofilled value that the user did not type.
"""
import re
import unittest

from tests._testdb import app, db, _fresh_db

EMAIL_FIELD_RE = re.compile(r'name="(f1_[^"]+)"')
PASSWORD_FIELD_RE = re.compile(r'name="(f2_[^"]+)"')
PASSWORD_INPUT_RE = re.compile(r'<input\b[^>]*type="password"', re.IGNORECASE)
STYLE_OR_SCRIPT_RE = re.compile(
    r"<style\b.*?</style\s*>|<script\b.*?</script\s*>",
    re.IGNORECASE | re.DOTALL,
)


def _dom_html(html):
    """Return markup with <style>/<script> blocks removed, mirroring what a
    browser actually parses into the DOM (their contents are never elements)."""
    return STYLE_OR_SCRIPT_RE.sub("", html)


class AdminLoginEmptyFieldsTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        _fresh_db()

    def tearDown(self):
        # Release the SQLAlchemy session/connection so the SQLite test DB
        # is never locked between tests (mirrors tests/test_app.py).
        db.session.remove()
        try:
            self.app_context.pop()
        except Exception:
            pass

    # -- the form must open empty -----------------------------------------

    def test_login_page_fields_render_hard_empty(self):
        resp = self.client.get("/admin/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        # Both credential fields render with hard-empty values — nothing
        # (session, query string, template) can prefill them.
        self.assertIn('value=""', html)
        # No application credential is ever rendered on the page.
        self.assertNotIn("Admin@123", html)
        self.assertNotIn("admin@myvoice.local", html)

    def test_login_page_ships_no_native_password_input(self):
        """THE actual root cause of credential autofill: a native
        <input type="password"> present at page load is the trigger
        Chrome/Edge password managers use to inject saved credentials."""
        resp = self.client.get("/admin/login")
        html = resp.get_data(as_text=True)
        self.assertIsNone(
            PASSWORD_INPUT_RE.search(_dom_html(html)),
            "Admin Login must not ship a native <input type=\"password\"> at page load",
        )
        # The masked placeholder input must be armed instead.
        self.assertIn('data-pwd-armed="true"', html)
        # And the visual masking CSS must be delivered with the page.
        self.assertIn("-webkit-text-security", html)

    def test_login_fields_use_nonce_names_and_autocomplete_off(self):
        resp = self.client.get("/admin/login")
        html = resp.get_data(as_text=True)
        self.assertIn('autocomplete="off"', html)
        self.assertIsNotNone(EMAIL_FIELD_RE.search(html))
        self.assertIsNotNone(PASSWORD_FIELD_RE.search(html))

    def test_every_render_path_sends_no_store_headers(self):
        # GET path
        resp = self.client.get("/admin/login")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache)
        self.assertIn("no-cache", cache)
        # Failed-POST render path must also be uncacheable.
        resp = self.client.post(
            "/admin/login",
            data={"admin_email": "", "admin_password": ""},
        )
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache)

    # -- the login itself must keep working --------------------------------

    def _extract_nonce_fields(self, html):
        return (
            EMAIL_FIELD_RE.search(html).group(1),
            PASSWORD_FIELD_RE.search(html).group(1),
        )

    def test_successful_login_with_nonce_fields_still_works(self):
        page = self.client.get("/admin/login")
        email_field, password_field = self._extract_nonce_fields(
            page.get_data(as_text=True)
        )
        resp = self.client.post(
            "/admin/login",
            data={
                email_field: "owner@test.example",
                password_field: "TestPass123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/dashboard", resp.headers.get("Location", ""))

    def test_failed_login_rerenders_empty_form_without_echoing_values(self):
        page = self.client.get("/admin/login")
        email_field, password_field = self._extract_nonce_fields(
            page.get_data(as_text=True)
        )
        resp = self.client.post(
            "/admin/login",
            data={email_field: "owner@test.example", password_field: "wrong-pass"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        # Submitted credentials must never be echoed back into the form.
        self.assertIn('value=""', html)
        self.assertNotIn("owner@test.example\">", html)
        self.assertIsNone(PASSWORD_INPUT_RE.search(_dom_html(html)))

    def test_legacy_field_names_still_accepted(self):
        # Backward-compatible fallback for older forms/scripts.
        resp = self.client.post(
            "/admin/login",
            data={
                "admin_email": "owner@test.example",
                "admin_password": "TestPass123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/dashboard", resp.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
