"""Admin view of student participation derived from submitted ballots."""

import csv
import io

from flask import Blueprint, Response, render_template, request
from sqlalchemy import func

from modules.database import db, Student, Vote
from modules.security import admin_required, current_organization_id


participation = Blueprint("participation", __name__)


def _participation_query(organization_id, status_filter="all"):
    voted_students = (
        db.session.query(
            Vote.student_id.label("student_pk"),
            func.count(Vote.id).label("vote_count"),
        )
        .filter(Vote.organization_id == organization_id)
        .group_by(Vote.student_id)
        .subquery()
    )

    query = (
        db.session.query(
            Student.student_id,
            Student.full_name,
            Student.class_name,
            voted_students.c.vote_count,
        )
        .outerjoin(voted_students, voted_students.c.student_pk == Student.id)
        .filter(Student.organization_id == organization_id)
        .order_by(Student.student_id.asc(), Student.full_name.asc())
    )

    if status_filter == "voted":
        query = query.filter(voted_students.c.vote_count.isnot(None))
    elif status_filter == "not-voted":
        query = query.filter(voted_students.c.vote_count.is_(None))

    return query


@participation.route("/admin/participation")
@admin_required
def participation_page():
    """Show every imported student and whether they have cast a ballot."""
    organization_id = current_organization_id()
    status_filter = request.args.get("status", "all").lower()
    if status_filter not in {"all", "voted", "not-voted"}:
        status_filter = "all"

    rows = [
        {
            "student_id": student_id,
            "name": full_name,
            "class_name": class_name,
            "status": "Voted" if vote_count is not None else "Not Voted",
        }
        for student_id, full_name, class_name, vote_count in _participation_query(
            organization_id, status_filter
        ).all()
    ]

    all_count = (
        Student.query.filter_by(organization_id=organization_id).count()
    )
    voted_count = (
        db.session.query(func.count(func.distinct(Vote.student_id)))
        .filter(Vote.organization_id == organization_id)
        .scalar()
        or 0
    )

    return render_template(
        "participation.html",
        rows=rows,
        status_filter=status_filter,
        counts={
            "all": all_count,
            "voted": voted_count,
            "not_voted": max(all_count - voted_count, 0),
        },
    )


@participation.route("/admin/participation/export/<status>")
@admin_required
def export_participation_csv(status):
    """Download the organization-scoped voted or not-voted student list."""
    status_filter = status.lower()
    if status_filter not in {"voted", "not-voted"}:
        return Response("Not found", status=404, mimetype="text/plain")

    organization_id = current_organization_id()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Full Name", "Student ID", "Class"])

    for student_id, full_name, class_name, _ in _participation_query(
        organization_id, status_filter
    ).all():
        writer.writerow([full_name or "", student_id or "", class_name or ""])

    filename = "myvoice_voted_students.csv" if status_filter == "voted" else "myvoice_not_voted_students.csv"
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response