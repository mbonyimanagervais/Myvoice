from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from modules.database import db, Student, AuditLog, SystemSetting
from modules.security import (
    admin_required,
    is_admin,
    current_organization_id,
    org_scoped_get
)
from werkzeug.security import generate_password_hash
import json
import csv
import pandas as pd
import os
import math
import re

students_bp = Blueprint("students", __name__, url_prefix="/admin")


def get_default_password():
    org_id = current_organization_id()
    settings = None
    if org_id:
        settings = SystemSetting.query.filter_by(organization_id=org_id).first()
    if settings is None:
        settings = SystemSetting.query.first()
    if settings and settings.default_student_password:
        return settings.default_student_password
    return "12345"


def _import_value(record, *keys):
    """Return the first non-empty import value without leaking NaN strings."""
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        return str(value).strip()
    return ""


def _canonical_key(value):
    value = str(value).replace("\ufeff", "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _read_tabular_records(filepath, filename):
    """Read CSV/Excel files even when a title row precedes the headers."""
    if filename.endswith(".csv"):
        with open(filepath, "r", encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(8192)
            stream.seek(0)
            rows = list(csv.reader(stream, delimiter=","))

        def sniff_delimiter(text):
            candidates = [",", ";", "\t", "|"]
            for delim in candidates:
                if delim in text:
                    sample_rows = [row for row in csv.reader(text.splitlines(), delimiter=delim) if row and any(cell.strip() for cell in row)]
                    if sample_rows:
                        header = sample_rows[0]
                        if len(header) > 1 and any(cell.strip() for cell in header):
                            score = 0
                            for row in sample_rows[:5]:
                                if len(row) > 1:
                                    score += 1
                            if score:
                                return delim
            return ","

        delimiter = sniff_delimiter(sample)
        with open(filepath, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream, delimiter=delimiter))

        def has_core_headers(columns):
            headers = {_canonical_key(column) for column in columns}
            return bool(headers & {"student_id", "studentid", "id", "student_no", "roll_no", "registration_no"}) and bool(
                headers & {"name", "names", "full_name", "student_name", "student_names"}
            )

        for header_index, headers in enumerate(rows[:20]):
            if has_core_headers(headers):
                normalized_headers = [_canonical_key(header) for header in headers]
                return [
                    dict(zip(normalized_headers, row))
                    for row in rows[header_index + 1:]
                    if row and len(row) >= len(normalized_headers)
                ]
        return []

    dataframe = pd.read_excel(filepath)

    def has_core_headers(columns):
        headers = {_canonical_key(column) for column in columns}
        return bool(headers & {"student_id", "studentid", "id", "student_no", "roll_no", "registration_no"}) and bool(
            headers & {"name", "names", "full_name", "student_name", "student_names"}
        )

    if not has_core_headers(dataframe.columns):
        raw = pd.read_excel(filepath, header=None)
        for header_index in range(min(len(raw), 20)):
            if has_core_headers(raw.iloc[header_index].tolist()):
                dataframe = raw.iloc[header_index + 1:].copy()
                dataframe.columns = raw.iloc[header_index].tolist()
                break
    dataframe.columns = [_canonical_key(column) for column in dataframe.columns]
    return dataframe.to_dict(orient="records")


def _normalize_student_record(record):
    if not isinstance(record, dict):
        return None

    normalized = {
        _canonical_key(key): value
        for key, value in record.items()
    }
    student_id = _import_value(
        normalized, "student_id", "studentid", "id", "student_no", "roll_no", "registration_no"
    )
    full_name = _import_value(
        normalized, "name", "names", "full_name", "student_name", "student_names"
    )
    if not student_id or not full_name:
        return None

    optional = {}
    for field, aliases in {
        "class_name": ("class_name", "class", "classname"),
        "department": ("department", "dept"),
        "username": ("username",),
        "email": ("email",),
        "status": ("status",),
    }.items():
        if any(alias in normalized for alias in aliases):
            optional[field] = _import_value(normalized, *aliases)

    if optional.get("status") not in (None, "", "Active", "Disabled"):
        optional["status"] = "Active"
    return {"student_id": student_id, "full_name": full_name, **optional}


def get_student_query():
    org_id = current_organization_id()
    query = Student.query
    if org_id:
        query = query.filter(Student.organization_id == org_id)
    search = request.args.get("search", "").strip()
    class_filter = request.args.get("class_filter", "")
    department_filter = request.args.get("department_filter", "")
    status_filter = request.args.get("status_filter", "")
    vote_filter = request.args.get("vote_filter", "")

    if search:
        query = query.filter(
            (Student.full_name.contains(search)) |
            (Student.student_id.contains(search)) |
            (Student.username.contains(search))
        )

    if class_filter:
        query = query.filter(Student.class_name == class_filter)

    if department_filter:
        query = query.filter(Student.department == department_filter)

    if status_filter:
        query = query.filter(Student.status == status_filter)

    if vote_filter:
        query = query.filter(Student.vote_status == vote_filter)

    return query.order_by(Student.id.desc())


def student_statistics():
    org_id = current_organization_id()
    base = Student.query
    if org_id:
        base = base.filter(Student.organization_id == org_id)
    total_students = base.count()
    active_students = base.filter_by(status="Active").count()
    disabled_students = base.filter_by(status="Disabled").count()
    voted_students = base.filter_by(vote_status="Voted").count()
    not_voted_students = base.filter_by(vote_status="Not Voted").count()
    participation_rate = round((voted_students / total_students) * 100, 2) if total_students else 0

    return {
        "total_students": total_students,
        "active_students": active_students,
        "disabled_students": disabled_students,
        "voted_students": voted_students,
        "not_voted_students": not_voted_students,
        "participation_rate": participation_rate,
    }


@students_bp.route("/students", methods=["GET", "POST"])
def manage_students():
    if not is_admin():
        return redirect(url_for("auth.admin_login"))

    default_pwd = get_default_password()

    if request.method == "POST":
        payload = request.get_json(silent=True)
        action = request.form.get("action") or ("upload_excel" if isinstance(payload, list) else "")

        if action == "add":
            student_id = request.form.get("student_id", "").strip()
            username = request.form.get("username", "").strip() or student_id
            full_name = request.form.get("full_name", "").strip()
            class_name = request.form.get("class_name", "").strip()
            department = request.form.get("department", "").strip()
            password = request.form.get("password", "").strip() or default_pwd

            if not student_id or not full_name:
                flash("Student ID and Full Name are required", "danger")
                return redirect(url_for("students.manage_students"))

            student_id = student_id.strip()
            username = username.strip() or student_id
            full_name = full_name.strip()
            class_name = class_name.strip()
            department = department.strip()

            org_id = current_organization_id()

            if Student.query.filter_by(
                organization_id=org_id, student_id=student_id
            ).first():
                flash("Student ID already exists in this organization", "danger")
                return redirect(url_for("students.manage_students"))

            if Student.query.filter_by(
                organization_id=org_id, username=username
            ).first():
                flash("Username already exists in this organization", "danger")
                return redirect(url_for("students.manage_students"))

            new_student = Student(
                organization_id=org_id,
                student_id=student_id,
                username=username,
                full_name=full_name,
                class_name=class_name,
                department=department,
                password=generate_password_hash(password),
                status="Active",
                vote_status="Not Voted"
            )
            db.session.add(new_student)

            log = AuditLog(user=str(session.get("admin_id")), action=f"Added student: {student_id}")
            db.session.add(log)
            db.session.commit()

            flash("Student added successfully", "success")

        elif action == "update":
            student_id = request.form.get("student_id", "").strip()
            username = request.form.get("username", "").strip()
            full_name = request.form.get("full_name", "").strip()
            class_name = request.form.get("class_name", "").strip()
            department = request.form.get("department", "").strip()
            org_id = current_organization_id()
            student = org_scoped_get(Student, request.form.get("student_id_to_update"))

            if not student_id or not full_name:
                flash("Student ID and Full Name are required", "danger")
                return redirect(url_for("students.manage_students"))

            student_id = student_id.strip()
            username = username.strip() or student_id
            full_name = full_name.strip()
            class_name = class_name.strip()
            department = department.strip()

            if Student.query.filter(Student.id != student.id).filter_by(
                organization_id=org_id, student_id=student_id
            ).first():
                flash("Student ID already exists in this organization", "danger")
                return redirect(url_for("students.manage_students"))

            if Student.query.filter(Student.id != student.id).filter_by(
                organization_id=org_id, username=username
            ).first():
                flash("Username already exists in this organization", "danger")
                return redirect(url_for("students.manage_students"))

            student.student_id = student_id
            student.username = username
            student.full_name = full_name
            student.class_name = class_name
            student.department = department
            db.session.add(student)

            log = AuditLog(user=str(session.get("admin_id")), action=f"Updated student: {student_id}")
            db.session.add(log)
            db.session.commit()
            flash("Student updated successfully", "success")

        elif action == "upload_excel":
            file = request.files.get("excel_file")
            json_text = request.form.get("json_data", "").strip()
            records = []
            filepath = None

            try:
                if isinstance(payload, list):
                    records = payload
                elif json_text:
                    records = json.loads(json_text)
                    if not isinstance(records, list):
                        flash("JSON data must be an array of student records", "danger")
                        return redirect(url_for("students.manage_students"))
                elif file and file.filename:
                    filename = file.filename.lower()
                    if filename.endswith(".json"):
                        records = json.loads(file.read().decode("utf-8"))
                        if not isinstance(records, list):
                            flash("JSON file must contain an array of student records", "danger")
                            return redirect(url_for("students.manage_students"))
                    elif filename.endswith((".xlsx", ".xls", ".csv")):
                        filepath = os.path.join("backups", file.filename)
                        file.save(filepath)
                        records = _read_tabular_records(filepath, filename)
                    else:
                        flash("Invalid file format. Please upload .xlsx, .xls, .csv, or .json files", "danger")
                        return redirect(url_for("students.manage_students"))
                else:
                    flash("No file or JSON data provided", "danger")
                    return redirect(url_for("students.manage_students"))

                imported = 0
                updated = 0
                failed = 0
                duplicates = 0

                for record in records:
                    if not isinstance(record, dict):
                        failed += 1
                        continue

                    # Spreadsheet exports often include empty rows at the end.
                    # They are not invalid student records and should not be
                    # reported as skipped rows.
                    if not any(_import_value(record, str(key)) for key in record):
                        continue

                    normalized = _normalize_student_record(record)
                    if normalized is None:
                        failed += 1
                        continue

                    s_id = normalized["student_id"]
                    name = normalized["full_name"]
                    has_cls = "class_name" in normalized
                    has_dept = "department" in normalized
                    has_username = "username" in normalized
                    has_email = "email" in normalized
                    has_status = "status" in normalized
                    cls = normalized.get("class_name", "")
                    department = normalized.get("department", "")
                    username = normalized.get("username", "")
                    email = normalized.get("email", "") or None
                    raw_status = normalized.get("status", "") or "Active"

                    org_id = current_organization_id()
                    existing = Student.query.filter_by(
                        organization_id=org_id, student_id=s_id
                    ).first()

                    if existing:
                        is_same_record = (
                            existing.full_name == name and
                            (existing.class_name or "") == (cls or "") and
                            (existing.department or "") == (department or "") and
                            (existing.username or "") == (username or "") and
                            (existing.email or "") == (email or "") and
                            (existing.status or "Active") == (raw_status or "Active")
                        )
                        if is_same_record:
                            duplicates += 1
                            continue

                        existing.full_name = name
                        if has_cls:
                            existing.class_name = cls or ""
                        if has_dept:
                            existing.department = department or ""
                        username_conflict = Student.query.filter(
                            Student.organization_id == org_id,
                            Student.username == username,
                            Student.id != existing.id,
                        ).first() if has_username and username else None
                        if has_username and username and not username_conflict:
                            existing.username = username
                        if has_email:
                            existing.email = email
                        if has_status and raw_status:
                            existing.status = raw_status
                        db.session.add(existing)
                        updated += 1
                    else:
                        requested_username = username or s_id
                        username_in_use = Student.query.filter_by(
                            organization_id=org_id,
                            username=requested_username,
                        ).first()
                        student = Student(
                            organization_id=org_id,
                            student_id=s_id,
                            username=None if username_in_use else requested_username,
                            full_name=name,
                            class_name=cls or "",
                            department=department or "",
                            email=email,
                            password=generate_password_hash(default_pwd),
                            status=raw_status or "Active",
                            vote_status="Not Voted",
                        )
                        db.session.add(student)
                        imported += 1

                db.session.commit()

                log = AuditLog(
                    user=str(session.get("admin_id")),
                    action=(
                        f"Imported {imported} students, updated {updated}, "
                        f"failed {failed}, duplicates {duplicates} via bulk upload"
                    ),
                )
                db.session.add(log)
                db.session.commit()

                parts = []
                if imported > 0:
                    parts.append(f"Imported {imported}")
                if updated > 0:
                    parts.append(f"Updated {updated}")
                if failed > 0:
                    parts.append(f"Failed {failed}")
                if duplicates > 0:
                    parts.append(f"Duplicates {duplicates}")
                summary = ", ".join(parts) if parts else "No changes made"
                flash(summary, "success" if imported or updated else "warning")

            except Exception as e:
                db.session.rollback()
                flash(f"Error processing import: {str(e)}", "danger")

        return redirect(url_for("students.manage_students"))

    students = get_student_query().all()
    classes = [row[0] for row in db.session.query(Student.class_name).filter(Student.class_name.isnot(None)).distinct().all()]
    departments = [row[0] for row in db.session.query(Student.department).filter(Student.department.isnot(None)).distinct().all()]
    stats = student_statistics()
    return render_template("students.html", students=students, stats=stats, classes=classes, departments=departments)


@students_bp.route("/students/delete/<int:id>")
def delete_student(id):
    if not is_admin():
        return redirect(url_for("auth.admin_login"))

    student = org_scoped_get(Student, id)
    db.session.delete(student)

    log = AuditLog(user=str(session.get("admin_id")), action=f"Deleted student ID: {student.student_id}")
    db.session.add(log)
    db.session.commit()

    flash("Student deleted successfully", "success")
    return redirect(url_for("students.manage_students"))


# =====================================
# TOGGLE STUDENT STATUS
# =====================================

@students_bp.route("/students/toggle-status/<int:id>", methods=["GET", "POST"])
def toggle_student_status(id):
    if not is_admin():
        return redirect(url_for("auth.admin_login"))

    student = org_scoped_get(Student, id)
    current_status = (student.status or "Active").strip()
    new_status = "Disabled" if current_status == "Active" else "Active"
    student.status = new_status
    db.session.add(student)

    log = AuditLog(user=str(session.get("admin_id")), action=f"Changed student status: {student.student_id} -> {new_status}")
    db.session.add(log)
    db.session.commit()

    flash(f"Student account {new_status.lower()} successfully", "success")
    return redirect(url_for("students.manage_students"))


@students_bp.route("/students/reset-password/<int:id>")
def reset_student_password(id):
    if not is_admin():
        return redirect(url_for("auth.admin_login"))

    student = org_scoped_get(Student, id)
    default_pwd = get_default_password()
    student.password = generate_password_hash(default_pwd)
    db.session.add(student)

    log = AuditLog(user=str(session.get("admin_id")), action=f"Reset password for student: {student.student_id}")
    db.session.add(log)
    db.session.commit()

    flash("Student password reset successfully", "success")
    return redirect(url_for("students.manage_students"))


@students_bp.route("/students/edit/<int:id>", methods=["GET"])
def edit_student(id):
    if not is_admin():
        return redirect(url_for("auth.admin_login"))

    student = org_scoped_get(Student, id)
    students = get_student_query().all()
    return render_template("students.html", students=students, edit_student=student, stats=student_statistics())