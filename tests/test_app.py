"""Updated smoke / integration tests for the multi-tenant architecture.

Key changes from the stale suite:
- Every entity carries organization_id (org context is required).
- Admin login is email-based; session carries organization_id.
- Password reset uses single-use, hashed tokens (not username/recovery_code).
- Cross-org access is blocked with 404.
- Each test gets a fresh temp DB to avoid state leakage.
"""
import unittest
import uuid
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from tests._testdb import app, db, _fresh_db, _seed_secondary_org
from modules.database import (
    Organization,
    Admin,
    Student,
    Election,
    Position,
    Candidate,
    Vote,
    PasswordResetToken,
)
from modules.auth import _issue_reset_token, _validate_reset_token
from sqlalchemy import inspect


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True
        self.app_context = app.app_context()
        self.app_context.push()
        _fresh_db()

    def tearDown(self):
        db.session.remove()
        try:
            self.app_context.pop()
        except Exception:
            pass

    # -- helpers ----------------------------------------------------------

    def _login_admin(self, admin):
        with self.client.session_transaction() as sess:
            sess["admin_id"] = admin.id
            sess["organization_id"] = admin.organization_id
            sess["admin_name"] = admin.full_name
            sess["admin_role"] = admin.role or "owner"
            sess["is_owner"] = bool(admin.is_owner)
            sess["email"] = admin.email

    def _get_seed(self):
        with app.app_context():
            org = Organization.query.filter_by(
                organization_name="Test Organization"
            ).first()
            admin = Admin.query.filter_by(email="owner@test.example").first()
            return org, admin

    # -- tests ------------------------------------------------------------

    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_election_management_page_shows_results_without_archive_action(self):
        with app.app_context():
            org, admin = self._get_seed()
            election = Election(
                title="Test Election",
                status="Draft",
                election_year="2026",
                organization_id=org.id,
            )
            db.session.add(election)
            db.session.commit()

        self._login_admin(admin)

        response = self.client.get("/admin/elections")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"View Results", response.data)
        self.assertNotIn(b"archive.create_archive", response.data)

    def test_admin_dashboard_has_election_management_link(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/admin/elections", response.data)

    def test_admin_dashboard_has_results_management_link(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/admin/results", response.data)

    def test_new_election_defaults_to_active_instead_of_draft(self):
        with app.app_context():
            org, admin = self._get_seed()

        self._login_admin(admin)

        response = self.client.post("/admin/elections/add", data={
            "title": "Auto Active Election",
            "description": "Created for regression testing",
            "election_year": "2026",
            "visibility": "Visible",
            "max_votes_per_position": "1",
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)

        with app.app_context():
            election = Election.query.filter_by(
                title="Auto Active Election"
            ).order_by(Election.id.desc()).first()
            self.assertIsNotNone(election)
            self.assertEqual(election.status, "Active")
