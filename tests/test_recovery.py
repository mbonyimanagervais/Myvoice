import re
import unittest
import uuid
from unittest import mock

from werkzeug.security import generate_password_hash

from app import app
from modules.database import db, Admin, SystemSetting, AuditLog, RecoveryRequest
from modules.auth import RECOVERY_ALLOWED_ATTEMPTS

CREDENTIAL_RE = re.compile(
    r"MYV-REC-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}"
)


def _extract_credential(text):
    match = CREDENTIAL_RE.search(text or "")
    return match.group(0) if match else None


class DeveloperRecoveryTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True

    def setUp(self):
        with app.app_context():
            db.create_all()
        self.client = app.test_client()
        self.emails = []

        def fake_send(subject, body, to_email=None):
            self.emails.append({"subject": subject, "body": body, "to": to_email})
            return True

        # The routes import send_security_email into their own module namespace,
        # so we must patch those module references to capture deliveries.
        self._patchers = [
            mock.patch(
                "modules.settings_routes.send_security_email",
                side_effect=fake_send,
            ),
            mock.patch("modules.auth.send_security_email", side_effect=fake_send),
        ]
        for patcher in self._patchers:
            patcher.start()

        with app.app_context():
            settings = SystemSetting.query.first()
            if settings is None:
                settings = SystemSetting()
                db.session.add(settings)
                db.session.commit()
            # Reset recovery state so each test starts clean and order-independent.
            settings.developer_recovery_hash = None
            settings.developer_security_email = None
            settings.recovery_generated_at = None
            settings.recovery_last_at = None
            settings.recovery_events_count = 0
            settings.recovery_failed_attempts = 0
            settings.recovery_locked_until = None
            settings.recovery_lockout_count = 0
            db.session.commit()
            self.settings_id = settings.id

    def tearDown(self):
        for patcher in self._patchers:
            patcher.stop()

        with app.app_context():
            settings = SystemSetting.query.get(self.settings_id)
            if settings is not None:
                settings.developer_recovery_hash = None
                settings.developer_security_email = None
                settings.recovery_generated_at = None
                settings.recovery_last_at = None
                settings.recovery_events_count = 0
                settings.recovery_failed_attempts = 0
                settings.recovery_locked_until = None
                settings.recovery_lockout_count = 0
                db.session.commit()
            temp = Admin.query.filter(
                Admin.full_name.like("RecoveryTester%")
            ).all()
            temp_ids = [a.id for a in temp]
            if temp_ids:
                RecoveryRequest.query.filter(
                    RecoveryRequest.admin_id.in_(temp_ids)
                ).delete(synchronize_session=False)
            Admin.query.filter(
                Admin.full_name.like("RecoveryTester%")
            ).delete(synchronize_session=False)
            db.session.commit()

    def _create_temp_admin(self):
        suffix = uuid.uuid4().hex[:8]
        name = "RecoveryTester" + suffix
        with app.app_context():
            admin = Admin(
                full_name=name,
                password=generate_password_hash("OldPass123!"),
            )
            db.session.add(admin)
            db.session.commit()
            return admin.id, name

    def _init_recovery_as(self, admin_id):
        with self.client.session_transaction() as sess:
            sess["admin_id"] = admin_id
        self.client.post("/admin/settings/recovery/init", follow_redirects=False)
        with self.client.session_transaction() as sess:
            sess.clear()

    def _captured_credential(self):
        for msg in self.emails:
            cred = _extract_credential(msg["body"])
            if cred:
                return cred
        return None

    def test_credential_never_stored_as_plaintext(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)

        cred = self._captured_credential()
        self.assertIsNotNone(cred)

        with app.app_context():
            settings = SystemSetting.query.get(self.settings_id)
            self.assertIsNotNone(settings.developer_recovery_hash)
            self.assertNotIn("MYV-REC-", settings.developer_recovery_hash)
            self.assertNotIn(cred, settings.developer_recovery_hash)
            self.assertIn(":", settings.developer_recovery_hash)

    def test_credential_not_rendered_in_settings_page(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)

        with self.client.session_transaction() as sess:
            sess["admin_id"] = admin_id

        resp = self.client.get("/admin/settings")
        html = resp.get_data(as_text=True)
        self.assertNotIn("MYV-REC-", html)
        cred = self._captured_credential()
        self.assertIsNotNone(cred)
        self.assertNotIn(cred, html)
    def test_full_recovery_flow_and_session_revocation(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)
        cred = self._captured_credential()
        self.assertIsNotNone(cred)

        # Simulate a previously logged-in admin session that must be revoked.
        with self.client.session_transaction() as sess:
            sess["admin_id"] = admin_id

        resp = self.client.post(
            "/admin/recovery",
            data={"username": name, "recovery_credential": cred},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/reset-password", resp.headers.get("Location", ""))

        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("recovery_authorized"))
            self.assertEqual(sess.get("recovery_admin_id"), admin_id)

        page = self.client.get("/admin/reset-password")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Recovery Authorized", page.data)

        resp2 = self.client.post(
            "/admin/reset-password",
            data={"new_password": "NewStrongPass1!", "confirm_password": "NewStrongPass1!"},
            follow_redirects=False,
        )
        self.assertEqual(resp2.status_code, 302)
        self.assertIn("/admin/login", resp2.headers.get("Location", ""))

        # Old session must be revoked -> dashboard redirects to login.
        dash = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(dash.status_code, 302)
        self.assertIn("/admin/login", dash.headers.get("Location", ""))

        # The new password must be required for the next login.
        login = self.client.post(
            "/admin/login",
            data={"username": name, "password": "NewStrongPass1!"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("/admin/dashboard", login.headers.get("Location", ""))

        with app.app_context():
            settings = SystemSetting.query.get(self.settings_id)
            self.assertIsNotNone(settings.recovery_last_at)

            actions = [
                a.action
                for a in AuditLog.query.order_by(AuditLog.id.desc()).all()
            ]
            for expected in [
                "ADMIN_RECOVERY_APPROVED",
                "ADMIN_PASSWORD_RESET",
                "ADMIN_SESSIONS_REVOKED",
            ]:
                self.assertIn(expected, actions)

            # The credential must never appear in audit log content.
            descriptions = [
                (a.description or "") + (a.action or "")
                for a in AuditLog.query.all()
            ]
            self.assertFalse(any("MYV-REC-" in d for d in descriptions))

    def test_wrong_credential_generic_error_no_leak(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)

        resp = self.client.post(
            "/admin/recovery",
            data={"username": name, "recovery_credential": "MYV-REC-WRON-WRON-WRON-WRON"},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        self.assertIn("Recovery could not be verified", html)
        self.assertNotIn("account does not exist", html.lower())
        self.assertNotIn("username is invalid", html.lower())

    def test_reset_password_requires_recovery_authorization(self):
        resp = self.client.get("/admin/reset-password", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/forgot-password", resp.headers.get("Location", ""))

    def test_lockout_after_repeated_failures(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)

        for _ in range(RECOVERY_ALLOWED_ATTEMPTS):
            self.client.post(
                "/admin/recovery",
                data={"username": name, "recovery_credential": "WRONG"},
                follow_redirects=False,
            )

        with app.app_context():
            settings = SystemSetting.query.get(self.settings_id)
            self.assertEqual(settings.recovery_failed_attempts, 0)
            self.assertIsNotNone(settings.recovery_locked_until)

        # Even the correct credential is rejected while locked.
        cred = self._captured_credential()
        resp = self.client.post(
            "/admin/recovery",
            data={"username": name, "recovery_credential": cred},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        self.assertIn("temporarily locked", html)

    def test_submit_request_notifies_developer_and_status_pending(self):
        admin_id, name = self._create_temp_admin()

        resp = self.client.post(
            "/admin/forgot-password",
            data={"username": name},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/recovery", resp.headers.get("Location", ""))

        with app.app_context():
            req = RecoveryRequest.query.filter_by(admin_id=admin_id).order_by(
                RecoveryRequest.id.desc()
            ).first()
            self.assertIsNotNone(req)
            self.assertEqual(req.status, "PENDING")
            request_id = req.request_id

            actions = [
                a.action
                for a in AuditLog.query.order_by(AuditLog.id.desc()).all()
            ]
            self.assertIn("ADMIN_RECOVERY_REQUEST_CREATED", actions)
            self.assertIn("DEVELOPER_RECOVERY_NOTIFICATION_SENT", actions)

        notified = [m for m in self.emails if "Recovery Request" in m["subject"]]
        self.assertEqual(len(notified), 1)
        self.assertIn("PENDING DEVELOPER REVIEW", notified[0]["body"])
        self.assertIn(request_id, notified[0]["body"])
        self.assertIn(name, notified[0]["body"])
        # No secrets in the notification (no credentials, no password).
        self.assertNotIn("OldPass123!", notified[0]["body"])
        self.assertIsNone(_extract_credential(notified[0]["body"]))

    def test_submit_request_no_duplicate_notification(self):
        admin_id, name = self._create_temp_admin()

        self.client.post("/admin/forgot-password", data={"username": name})
        self.client.post("/admin/forgot-password", data={"username": name})

        notified = [m for m in self.emails if "Recovery Request" in m["subject"]]
        self.assertEqual(len(notified), 1)

        with app.app_context():
            reqs = RecoveryRequest.query.filter_by(admin_id=admin_id).all()
            self.assertEqual(len(reqs), 1)
            self.assertEqual(reqs[0].status, "PENDING")

    def test_email_failure_is_safe_and_logged(self):
        admin_id, name = self._create_temp_admin()

        with mock.patch("modules.auth.send_security_email", return_value=False):
            resp = self.client.post(
                "/admin/forgot-password",
                data={"username": name},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)

        with app.app_context():
            req = RecoveryRequest.query.filter_by(admin_id=admin_id).order_by(
                RecoveryRequest.id.desc()
            ).first()
            self.assertIsNotNone(req)
            self.assertEqual(req.status, "PENDING")
            actions = [
                a.action
                for a in AuditLog.query.order_by(AuditLog.id.desc()).all()
            ]
            self.assertIn("DEVELOPER_RECOVERY_NOTIFICATION_FAILED", actions)

        # A failed email must NOT be reported as delivered.
        self.assertEqual(self.emails, [])

        # The admin-facing page stays generic; SMTP/config details are never shown.
        page = self.client.get("/admin/recovery", follow_redirects=True)
        html = page.get_data(as_text=True).lower()
        self.assertNotIn("smtp", html)
        self.assertNotIn("myvoice_smtp", html)

    def test_full_originated_flow_marks_request_completed(self):
        admin_id, name = self._create_temp_admin()
        self._init_recovery_as(admin_id)
        cred = self._captured_credential()
        self.assertIsNotNone(cred)

        self.client.post("/admin/forgot-password", data={"username": name})

        with app.app_context():
            req = RecoveryRequest.query.filter_by(admin_id=admin_id).order_by(
                RecoveryRequest.id.desc()
            ).first()
            self.assertIsNotNone(req)
            self.assertEqual(req.status, "PENDING")
            request_id = req.request_id

        # Developer provides the credential after verification -> APPROVED.
        resp = self.client.post(
            "/admin/recovery",
            data={"recovery_credential": cred},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/reset-password", resp.headers.get("Location", ""))

        # Administrator creates a new password -> COMPLETED.
        self.client.post(
            "/admin/reset-password",
            data={"new_password": "BrandNewPass9!", "confirm_password": "BrandNewPass9!"},
            follow_redirects=False,
        )

        with app.app_context():
            req = RecoveryRequest.query.filter_by(request_id=request_id).first()
            self.assertEqual(req.status, "COMPLETED")
            self.assertIsNotNone(req.approved_at)
            self.assertIsNotNone(req.used_at)
            actions = [
                a.action
                for a in AuditLog.query.order_by(AuditLog.id.desc()).all()
            ]
            self.assertIn("ADMIN_RECOVERY_APPROVED", actions)
            self.assertIn("ADMIN_RECOVERY_COMPLETED", actions)


if __name__ == "__main__":
    unittest.main()
