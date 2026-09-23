"""Tests for flexible student data import (CSV, Excel, JSON) and UPSERT behavior."""
import unittest
import json
import csv
import io
from datetime import datetime

from tests._testdb import app, db, _fresh_db
from modules.database import Student, Admin, Organization, SystemSetting
from modules.security import generate_password_hash as legacy_generate_password_hash
from werkzeug.security import generate_password_hash, check_password_hash


class StudentImportTests(unittest.TestCase):
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

    def test_csv_import_with_only_required_fields(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["student_id", "name"])
        writer.writerow(["S001", "Alice"])
        writer.writerow(["S002", "Bob"])
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "students.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 2)
            ids = {s.student_id for s in students}
            self.assertSetEqual(ids, {"S001", "S002"})
            alice = Student.query.filter_by(student_id="S001").first()
            self.assertEqual(alice.full_name, "Alice")
            self.assertEqual(alice.class_name, "")
            self.assertEqual(alice.department, "")

    def test_pipe_delimited_import_uses_default_student_password_for_voter_login(self):
        with app.app_context():
            org, admin = self._get_seed()
            settings = SystemSetting.query.filter_by(organization_id=org.id).first()
            settings.default_student_password = "DefaultStudentPwd"
            db.session.commit()
        self._login_admin(admin)

        csv_data = io.StringIO()
        csv_data.write("FULL NAME|STUDENT ID|CLASS\n")
        csv_data.write("John Doe|ST001|L5CSA\n")
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "students.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            student = Student.query.filter_by(student_id="ST001").first()
            self.assertIsNotNone(student)
            self.assertEqual(student.full_name, "John Doe")
            self.assertEqual(student.class_name, "L5CSA")
            self.assertTrue(check_password_hash(student.password, "DefaultStudentPwd"))

        login_response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "ST001",
                "voter_password": "DefaultStudentPwd",
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertIn("/voter/dashboard", login_response.headers.get("Location", ""))

    def test_csv_import_with_optional_fields(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["student_id", "name", "class_name", "department", "email", "status"])
        writer.writerow(["S003", "Charlie", "Form 2", "Science", "c@example.com", "Active"])
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "students.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            charlie = Student.query.filter_by(student_id="S003").first()
            self.assertIsNotNone(charlie)
            self.assertEqual(charlie.full_name, "Charlie")
            self.assertEqual(charlie.class_name, "Form 2")
            self.assertEqual(charlie.department, "Science")
            self.assertEqual(charlie.email, "c@example.com")
            self.assertEqual(charlie.status, "Active")

    def test_json_import_via_textarea(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "J001", "name": "Diana"},
            {"student_id": "J002", "name": "Eve", "class_name": "Form 3"},
        ])

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 2)
            diana = Student.query.filter_by(student_id="J001").first()
            self.assertEqual(diana.full_name, "Diana")
            self.assertEqual(diana.class_name, "")
            eve = Student.query.filter_by(student_id="J002").first()
            self.assertEqual(eve.class_name, "Form 3")

    def test_json_array_request_imports_without_form_wrapper(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.post(
            "/admin/students",
            json=[
                {"student_id": "API001", "name": "Direct JSON Student"},
            ],
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            student = Student.query.filter_by(student_id="API001").first()
            self.assertIsNotNone(student)
            self.assertEqual(student.full_name, "Direct JSON Student")
            self.assertEqual(student.class_name, "")

    def test_json_import_via_file_upload(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "F001", "name": "Frank", "department": "Arts"},
        ])
        file_obj = io.BytesIO(payload.encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (file_obj, "students.json")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            frank = Student.query.filter_by(student_id="F001").first()
            self.assertIsNotNone(frank)
            self.assertEqual(frank.full_name, "Frank")
            self.assertEqual(frank.department, "Arts")

    def test_upsert_updates_existing_student(self):
        with app.app_context():
            org, admin = self._get_seed()
            existing = Student(
                organization_id=org.id,
                student_id="U001",
                username="U001",
                full_name="Old Name",
                class_name="Old Class",
                department="Old Dept",
                password=Admin.query.first().password,
                status="Active",
                vote_status="Not Voted",
            )
            db.session.add(existing)
            db.session.commit()

        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "U001", "name": "New Name", "class_name": "New Class"},
        ])

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.filter_by(student_id="U001").all()
            self.assertEqual(len(students), 1)
            updated = students[0]
            self.assertEqual(updated.full_name, "New Name")
            self.assertEqual(updated.class_name, "New Class")
            self.assertEqual(updated.department, "Old Dept")

    def test_voter_login_accepts_legacy_student_hashes(self):
        with app.app_context():
            org, _ = self._get_seed()
            student = Student(
                organization_id=org.id,
                student_id="V001",
                username="V001",
                full_name="Legacy Student",
                class_name="Form 5",
                department="Science",
                password=legacy_generate_password_hash("StudentPass123"),
                status="Active",
                vote_status="Not Voted",
            )
            db.session.add(student)
            db.session.commit()

        response = self.client.post(
            "/voter/login",
            data={"voter_student_id": "V001", "voter_password": "StudentPass123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/voter/dashboard", response.headers.get("Location", ""))

    def test_settings_default_password_updates_existing_students(self):
        with app.app_context():
            org, admin = self._get_seed()
            # Student has the OLD default password ("12345") — this is what
            # get_default_password() returns when no default is configured.
            existing = Student(
                organization_id=org.id,
                student_id="S999",
                username="S999",
                full_name="Existing Student",
                class_name="Form 4",
                department="Science",
                password=generate_password_hash("12345"),
                status="Active",
                vote_status="Not Voted",
            )
            db.session.add(existing)
            db.session.commit()

        self._login_admin(admin)

        response = self.client.post(
            "/admin/settings",
            data={
                "system_name": "MyVoice",
                "school_name": "Test Organization",
                "election_year": "2026",
                "default_student_password": "NewStudentPass",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with app.app_context():
            student = Student.query.filter_by(student_id="S999").first()
            self.assertIsNotNone(student)
            self.assertTrue(check_password_hash(student.password, "NewStudentPass"))
            self.assertFalse(check_password_hash(student.password, "12345"))

    def test_missing_required_fields_are_skipped(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "M001", "name": "Valid"},
            {"name": "No ID"},
            {"student_id": "M002"},
            {},
        ])

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 1)
            self.assertEqual(students[0].student_id, "M001")

    def test_invalid_json_returns_error(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": "not valid json"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 0)

    def test_invalid_file_type_returns_error(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        file_obj = io.BytesIO(b"dummy content")
        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (file_obj, "students.txt")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 0)

    def test_csv_flexible_column_names(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["Student ID", "Full Name", "Class"])
        writer.writerow(["C001", "Grace", "Form 4"])
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "students.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            grace = Student.query.filter_by(student_id="C001").first()
            self.assertIsNotNone(grace)
            self.assertEqual(grace.full_name, "Grace")
            self.assertEqual(grace.class_name, "Form 4")

    def test_csv_with_title_row_and_decorated_headers_is_imported(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["Student Roster"])
        writer.writerow(["Student ID", "Student Name", "Optional Class"])
        writer.writerow(["T001", "Title Row Student", ""])
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "roster.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            student = Student.query.filter_by(student_id="T001").first()
            self.assertIsNotNone(student)
            self.assertEqual(student.full_name, "Title Row Student")

    def test_csv_with_names_header_and_blank_rows_does_not_report_invalid_rows(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["ID", "Names", "Gender", "Phone", "Address"])
        writer.writerow(["N001", "Names Header Student", "", "", ""])
        writer.writerow(["", "", "", "", ""])
        csv_bytes = io.BytesIO(csv_data.getvalue().encode("utf-8"))

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "excel_file": (csv_bytes, "names.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Skipped 1 invalid rows", response.data)

        with app.app_context():
            student = Student.query.filter_by(student_id="N001").first()
            self.assertIsNotNone(student)
            self.assertEqual(student.full_name, "Names Header Student")

    def test_empty_json_data_returns_error(self):
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": ""},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            students = Student.query.all()
            self.assertEqual(len(students), 0)

    def test_upsert_preserves_vote_status(self):
        with app.app_context():
            org, admin = self._get_seed()
            existing = Student(
                organization_id=org.id,
                student_id="V001",
                username="V001",
                full_name="Voter One",
                class_name="",
                department="",
                password=Admin.query.first().password,
                status="Active",
                vote_status="Voted",
                voted_at=datetime.utcnow(),
            )
            db.session.add(existing)
            db.session.commit()

        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "V001", "name": "Updated Voter One"},
        ])

        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            voter = Student.query.filter_by(student_id="V001").first()
            self.assertEqual(voter.full_name, "Updated Voter One")
            self.assertEqual(voter.vote_status, "Voted")


class StudentVoterLoginIntegrationTests(unittest.TestCase):
    """End-to-end tests verifying that students imported via the admin
    Student Management page can authenticate through the Voter Login."""

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

    def test_imported_student_can_login_via_voter_login(self):
        """Full flow: admin imports student → voter logs in with ID + password."""
        with app.app_context():
            org, admin = self._get_seed()
            # Set a default student password in settings
            settings = SystemSetting.query.filter_by(organization_id=org.id).first()
            settings.default_student_password = "StudentPwd123!"
            db.session.commit()

        self._login_admin(admin)

        # Import a student via JSON
        payload = json.dumps([
            {"student_id": "IMP01", "name": "Imported Student", "class_name": "Form 1"},
        ])
        response = self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        # Voter logs in with student_id and the default password
        response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "IMP01",
                "voter_password": "StudentPwd123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/voter/dashboard", response.headers.get("Location", ""))

    def test_imported_student_can_login_with_explicit_password(self):
        """Student added via the add form should use the entered password."""
        with app.app_context():
            _, admin = self._get_seed()
        self._login_admin(admin)

        response = self.client.post(
            "/admin/students",
            data={
                "action": "add",
                "student_id": "ADD01",
                "full_name": "Manual Student",
                "class_name": "Form 2",
                "password": "ManualPwd456!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "ADD01",
                "voter_password": "ManualPwd456!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/voter/dashboard", response.headers.get("Location", ""))

    def test_imported_student_login_rejects_wrong_password(self):
        with app.app_context():
            org, admin = self._get_seed()
            settings = SystemSetting.query.filter_by(organization_id=org.id).first()
            settings.default_student_password = "CorrectPwd"
            db.session.commit()

        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "WRONG01", "name": "Wrong Pwd Student"},
        ])
        self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )

        response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "WRONG01",
                "voter_password": "WrongPassword",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Invalid student ID or password", response.data) or self.assertIn(b"Invalid", response.data)

    def test_voter_login_trims_whitespace_from_student_id(self):
        with app.app_context():
            org, admin = self._get_seed()
            settings = SystemSetting.query.filter_by(organization_id=org.id).first()
            settings.default_student_password = "Pwd789"
            db.session.commit()

        self._login_admin(admin)

        payload = json.dumps([
            {"student_id": "WS01", "name": "Whitespace Student"},
        ])
        self.client.post(
            "/admin/students",
            data={"action": "upload_excel", "json_data": payload},
            follow_redirects=False,
        )

        response = self.client.post(
            "/voter/login",
            data={
                "voter_student_id": "  WS01  ",
                "voter_password": "Pwd789",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/voter/dashboard", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
