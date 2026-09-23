"""Regression tests for the independent, empty voter login surface."""
import re
import unittest

from tests._testdb import app, db, _fresh_db


class VoterLoginEmptyFieldsTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        _fresh_db()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_fresh_page_has_only_empty_voter_fields(self):
        response = self.client.get("/voter/login")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('name="voter_student_id"', html)
        self.assertIn('name="voter_password"', html)
        self.assertIn('id="voter-student-id"', html)
        self.assertIn('id="voter-password"', html)
        self.assertIn('value=""', html)
        self.assertNotIn("adminLoginForm", html)
        self.assertNotIn("admin_email", html)
        self.assertNotIn("admin_password", html)
        self.assertNotIn('autocomplete="username"', html)
        self.assertNotIn('autocomplete="current-password"', html)
        self.assertIn('data-pwd-armed="true"', html)

        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", cache_control)

    def test_voter_login_uses_only_voter_session_keys(self):
        response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "",
                "voter_password": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn("admin_id", session)
            self.assertNotIn("admin_name", session)
            self.assertNotIn("email", session)

    def test_voter_page_does_not_expose_admin_credentials(self):
        response = self.client.get("/voter/login")
        html = response.get_data(as_text=True)
        self.assertIsNone(re.search(r"Admin@123|admin@myvoice\.local", html))


if __name__ == "__main__":
    unittest.main()
