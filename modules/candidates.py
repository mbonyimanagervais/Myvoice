from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify
)

from modules.database import (
    db,
    Candidate,
    Position,
    Election,
    Student,
    AuditLog
)

from modules.auth import admin_required
from modules.security import (
    log_audit,
    log_security_event,
    org_scoped_get,
    current_organization_id
)

import os
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime



candidates = Blueprint(
    "candidates",
    __name__
)



UPLOAD_FOLDER = "uploads/candidates"

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg"
}



def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )



def save_candidate_photo(file_storage):
    if not file_storage or not allowed_file(file_storage.filename):
        return None

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = secure_filename(file_storage.filename)
    stem, ext = os.path.splitext(filename)
    unique_name = f"{stem}-{uuid.uuid4().hex}{ext.lower()}"
    file_storage.save(os.path.join(UPLOAD_FOLDER, unique_name))
    return unique_name


def _scoped_candidate(candidate_id):
    """Fetch a candidate ONLY if it belongs to the administrator's organization.
    Cross-organization access attempts are blocked and logged as violations."""
    candidate = Candidate.query.get(candidate_id)
    if candidate is None:
        return None

    if candidate.organization_id != current_organization_id():
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Blocked cross-organization access attempt to candidate #%s "
                "by admin %s" % (candidate_id, session.get("admin_id"))
            ),
        )
        return None

    return candidate


def validate_candidate_payload(election_id, position_id, student_id, biography, manifesto, slogan, status, exclude_candidate_id=None):
    if not election_id:
        return "Election is required"

    if not position_id:
        return "Position is required"

    if not student_id:
        return "Student is required"

    # Organization isolation: every referenced record MUST belong to the
    # administrator's own organization. Ids are never trusted from the client.
    org_id = current_organization_id()

    election = Election.query.filter_by(
        id=election_id,
        organization_id=org_id
    ).first()
    if election is None:
        return "Election not found"

    position = Position.query.filter_by(
        id=position_id,
        organization_id=org_id
    ).first()
    if position is None:
        return "Position not found"

    student = Student.query.filter_by(
        id=student_id,
        organization_id=org_id
    ).first()
    if student is None:
        return "Student not found"

    if student.status != "Active":
        return "Student account is not active"

    if position.election_id != int(election_id):
        return "Position does not belong to the selected election"

    duplicate_query = Candidate.query.filter_by(election_id=election_id, student_id=student_id)
    if exclude_candidate_id:
        duplicate_query = duplicate_query.filter(Candidate.id != exclude_candidate_id)
    if duplicate_query.first():
        return "This student is already a candidate for this election"

    if biography and len(biography.strip()) > 500:
        return "Biography must be 500 characters or fewer"

    if manifesto and len(manifesto.strip()) > 2000:
        return "Manifesto must be 2000 characters or fewer"

    if slogan and len(slogan.strip()) > 100:
        return "Slogan must be 100 characters or fewer"

    if status not in {"Draft", "Published", "Disabled", "Archived"}:
        return "Invalid status"

    return None


@candidates.route("/admin/candidates")
@admin_required
def candidates_page():
    # Organization isolation: every list below is scoped to the admin's org.
    org_id = current_organization_id()
    all_candidates = Candidate.query.filter_by(
        organization_id=org_id
    ).order_by(Candidate.display_order.asc(), Candidate.id.desc()).all()
    elections = Election.query.filter_by(
        organization_id=org_id
    ).order_by(Election.title.asc()).all()
    positions = Position.query.filter_by(
        organization_id=org_id
    ).order_by(Position.name.asc()).all()
    students = Student.query.filter_by(
        organization_id=org_id
    ).order_by(Student.full_name.asc()).all()

    return render_template(
        "candidates.html",
        candidates=all_candidates,
        elections=elections,
        positions=positions,
        students=students,
    )


@candidates.route("/admin/candidates/add", methods=["POST"])
@admin_required
def add_candidate():
    election_id = request.form.get("election_id", type=int)
    position_id = request.form.get("position_id", type=int)
    student_id = request.form.get("student_id", type=int)
    biography = request.form.get("biography", "")
    manifesto = request.form.get("manifesto", "")
    slogan = request.form.get("slogan", "")
    display_order = request.form.get("display_order", 0, type=int)
    status = request.form.get("status", "Draft")
    photo = request.files.get("photo")

    validation_error = validate_candidate_payload(
        election_id,
        position_id,
        student_id,
        biography,
        manifesto,
        slogan,
        status,
    )
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("candidates.candidates_page"))

    student = Student.query.filter_by(
        id=student_id,
        organization_id=current_organization_id()
    ).first()
    filename = save_candidate_photo(photo) if photo else None

    candidate = Candidate(
        election_id=election_id,
        position_id=position_id,
        student_id=student_id,
        organization_id=current_organization_id(),
        name=student.full_name if student else "Candidate",
        full_name=student.full_name if student else None,
        photo=filename,
        biography=biography.strip() or None,
        manifesto=manifesto.strip() or None,
        slogan=slogan.strip() or None,
        display_order=display_order or 0,
        status=status,
        created_by=str(session.get("admin_id")),
        updated_by=str(session.get("admin_id")),
    )

    db.session.add(candidate)
    db.session.add(AuditLog(user=str(session.get("admin_id")), action=f"Added candidate {candidate.full_name or candidate.name}"))
    db.session.commit()

    flash("Candidate added successfully", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/update/<int:id>", methods=["POST"])
@admin_required
def update_candidate(id):
    candidate = org_scoped_get(Candidate, id)

    candidate.biography = request.form.get("biography", "").strip() or None
    candidate.manifesto = request.form.get("manifesto", "").strip() or None
    candidate.slogan = request.form.get("slogan", "").strip() or None
    candidate.display_order = request.form.get("display_order", 0, type=int) or 0
    candidate.status = request.form.get("status", candidate.status)
    candidate.position_id = request.form.get("position_id", type=int) or candidate.position_id
    candidate.election_id = request.form.get("election_id", type=int) or candidate.election_id

    # Always sync candidate name from their linked student so the voter sees the real name (not "Candidate")
    student = Student.query.filter_by(
        id=candidate.student_id,
        organization_id=current_organization_id()
    ).first()
    if student:
        candidate.name = student.full_name
        candidate.full_name = student.full_name

    photo = request.files.get("photo")
    if photo and photo.filename:
        filename = save_candidate_photo(photo)
        if filename:
            candidate.photo = filename

    validation_error = validate_candidate_payload(
        candidate.election_id,
        candidate.position_id,
        candidate.student_id,
        candidate.biography,
        candidate.manifesto,
        candidate.slogan,
        candidate.status,
    )
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("candidates.candidates_page"))

    candidate.updated_by = str(session.get("admin_id"))
    db.session.add(AuditLog(user=str(session.get("admin_id")), action=f"Updated candidate {candidate.full_name or candidate.name}"))
    db.session.commit()

    flash("Candidate updated", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/delete/<int:id>")
@admin_required
def delete_candidate(id):
    candidate = org_scoped_get(Candidate, id)
    name = candidate.full_name or candidate.name

    db.session.delete(candidate)
    db.session.add(AuditLog(user=str(session.get("admin_id")), action=f"Deleted candidate {name}"))
    db.session.commit()

    flash("Candidate deleted", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/api/candidates/<int:position_id>")
def get_candidates(position_id):
    from modules.security import log_security_event

    # Public voting-time endpoint: only expose candidates belonging to the
    # authenticated voter's/admin's own organization.
    org_id = session.get("organization_id") or session.get("voter_org_id")
    if org_id is None:
        return {"candidates": []}

    position = Position.query.filter_by(
        id=position_id,
        organization_id=org_id
    ).first()

    if position is None:
        if Position.query.get(position_id) is not None:
            log_security_event(
                action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
                description=(
                    "Blocked cross-organization candidates API access for "
                    "position #%s" % position_id
                ),
            )
        return {"candidates": []}

    data = Candidate.query.filter_by(
        position_id=position.id,
        organization_id=org_id
    ).all()
    return {
        "candidates": [
            {
                "id": candidate.id,
                "name": candidate.full_name or candidate.name,
                "photo": candidate.photo,
            }
            for candidate in data
        ]
    }


# =====================================
# API ENDPOINTS FOR PROFESSIONAL UI
# =====================================

@candidates.route("/api/candidates/search-students")
@admin_required
def search_students():
    """Search students for candidate registration"""
    query = request.args.get("q", "").strip()
    election_id = request.args.get("election_id", type=int)
    
    if not query:
        return jsonify({"students": []})
    
    students_query = Student.query.filter(
        Student.status == "Active",
        Student.organization_id == current_organization_id()
    ).filter(
        (Student.full_name.contains(query)) |
        (Student.student_id.contains(query)) |
        (Student.username.contains(query)) |
        (Student.class_name.contains(query)) |
        (Student.department.contains(query))
    )
    
    # Filter out students already registered for this election
    # (only when the election belongs to this organization).
    election = None
    if election_id:
        election = Election.query.filter_by(
            id=election_id,
            organization_id=current_organization_id()
        ).first()

    registered_ids = [c.student_id for c in Candidate.query.filter_by(election_id=election.id).all()] if election else []
    students_query = students_query.filter(~Student.id.in_(registered_ids))
    
    students = students_query.limit(20).all()
    
    return jsonify({
        "students": [
            {
                "id": s.id,
                "full_name": s.full_name,
                "student_id": s.student_id,
                "class_name": s.class_name,
                "department": s.department,
                "status": s.status
            }
            for s in students
        ]
    })


@candidates.route("/api/candidates/student/<int:student_id>")
@admin_required
def get_student_profile(student_id):
    """Get student profile for candidate registration"""
    student = org_scoped_get(Student, student_id)
    
    return jsonify({
        "id": student.id,
        "full_name": student.full_name,
        "student_id": student.student_id,
        "class_name": student.class_name,
        "department": student.department,
        "status": student.status
    })


@candidates.route("/api/candidates/positions/<int:election_id>")
@admin_required
def get_positions_by_election(election_id):
    """Get positions for a specific election"""
    election = Election.query.filter_by(
        id=election_id,
        organization_id=current_organization_id()
    ).first()
    positions = Position.query.filter_by(
        election_id=election.id
    ).order_by(Position.display_order.asc()).all() if election else []
    
    return jsonify({
        "positions": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "maximum_winners": p.maximum_winners
            }
            for p in positions
        ]
    })


@candidates.route("/api/candidates/validate", methods=["POST"])
@admin_required
def validate_candidate_api():
    """Validate candidate before registration"""
    data = request.get_json()
    election_id = data.get("election_id")
    position_id = data.get("position_id")
    student_id = data.get("student_id")
    
    error = validate_candidate_payload(
        election_id, position_id, student_id,
        data.get("biography", ""),
        data.get("manifesto", ""),
        data.get("slogan", ""),
        data.get("status", "Draft")
    )
    
    if error:
        return jsonify({"valid": False, "error": error})
    
    return jsonify({"valid": True})


@candidates.route("/admin/candidates/delete-all", methods=["POST"])
@admin_required
def delete_all_candidates():
    """Delete all candidates (requires confirmation)"""
    try:
        org_id = current_organization_id()
        count = Candidate.query.filter_by(organization_id=org_id).count()
        Candidate.query.filter_by(organization_id=org_id).delete(
            synchronize_session=False
        )
        
        log_audit(
            session.get("admin_id"),
            "Deleted all candidates",
            f"Removed {count} candidates from organization"
        )
        db.session.commit()
        
        flash(f"Successfully deleted {count} candidates", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting candidates: {str(e)}", "danger")
    
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/archive-all", methods=["POST"])
@admin_required
def archive_all_candidates():
    """Archive all candidates"""
    try:
        candidates = Candidate.query.filter_by(
            status="Published",
            organization_id=current_organization_id()
        ).all()
        count = 0
        
        for candidate in candidates:
            candidate.status = "Archived"
            candidate.updated_by = str(session.get("admin_id"))
            db.session.add(candidate)
            count += 1
        
        log_audit(
            session.get("admin_id"),
            "Archived all candidates",
            f"Archived {count} candidates"
        )
        db.session.commit()
        
        flash(f"Successfully archived {count} candidates", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error archiving candidates: {str(e)}", "danger")
    
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/publish/<int:id>")
@admin_required
def publish_candidate(id):
    """Publish a candidate"""
    candidate = org_scoped_get(Candidate, id)
    candidate.status = "Published"
    candidate.updated_by = str(session.get("admin_id"))
    db.session.add(candidate)
    
    log_audit(
        session.get("admin_id"),
        f"Published candidate: {candidate.full_name or candidate.name}"
    )
    db.session.commit()
    
    flash("Candidate published successfully", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/disable/<int:id>")
@admin_required
def disable_candidate(id):
    """Disable a candidate"""
    candidate = org_scoped_get(Candidate, id)
    candidate.status = "Disabled"
    candidate.updated_by = str(session.get("admin_id"))
    db.session.add(candidate)
    
    log_audit(
        session.get("admin_id"),
        f"Disabled candidate: {candidate.full_name or candidate.name}"
    )
    db.session.commit()
    
    flash("Candidate disabled", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/archive/<int:id>")
@admin_required
def archive_candidate(id):
    """Archive a candidate"""
    candidate = org_scoped_get(Candidate, id)
    candidate.status = "Archived"
    candidate.updated_by = str(session.get("admin_id"))
    db.session.add(candidate)
    
    log_audit(
        session.get("admin_id"),
        f"Archived candidate: {candidate.full_name or candidate.name}"
    )
    db.session.commit()
    
    flash("Candidate archived", "success")
    return redirect(url_for("candidates.candidates_page"))


@candidates.route("/admin/candidates/statistics")
@admin_required
def candidate_statistics():
    """Get candidate statistics (scoped to the administrator's organization)"""
    org_id = current_organization_id()
    total = Candidate.query.filter_by(organization_id=org_id).count()
    published = Candidate.query.filter_by(organization_id=org_id, status="Published").count()
    draft = Candidate.query.filter_by(organization_id=org_id, status="Draft").count()
    disabled = Candidate.query.filter_by(organization_id=org_id, status="Disabled").count()
    archived = Candidate.query.filter_by(organization_id=org_id, status="Archived").count()
    
    # Elections with candidates (inside this organization)
    elections_with_candidates = (
        db.session.query(Election.id)
        .join(Candidate, Candidate.election_id == Election.id)
        .filter(Election.organization_id == org_id)
        .distinct()
        .count()
    )
    
    return jsonify({
        "total": total,
        "published": published,
        "draft": draft,
        "disabled": disabled,
        "archived": archived,
        "elections_with_candidates": elections_with_candidates
    })
