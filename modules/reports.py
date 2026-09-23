from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    Response,
    session
)

from modules.database import (
    db,
    Vote,
    Candidate,
    Position,
    Election,
    Student,
    AuditLog,
    SystemSetting,
    ElectionCategory,
    ResultsVisibility,
)

from modules.auth import admin_required
from modules.settings import get_settings
from modules.security import (
    org_scoped_get,
    current_organization_id
)

import csv
import io
import json
from datetime import datetime

try:
    import openpyxl
except ImportError:  # pragma: no cover - optional dependency
    openpyxl = None



reports = Blueprint(
    "reports",
    __name__
)


def calculate_percentages(votes, total_valid_votes):
    if not total_valid_votes:
        return 0.0
    return round((votes / total_valid_votes) * 100, 1)


def get_results_by_position(election_id=None, position_id=None):
    # Organization isolation: only THIS organization's elections can ever be
    # aggregated here. Every nested position/candidate/vote derives its
    # ownership from these elections.
    org_id = session.get("organization_id")
    election_filter = Election.query

    if org_id is not None:
        election_filter = election_filter.filter(
            Election.organization_id == org_id
        )

    if election_id:
        election_filter = election_filter.filter(Election.id == election_id)

    elections = election_filter.order_by(Election.id.desc()).all()
    payload = []

    for election in elections:
        positions = Position.query.filter_by(election_id=election.id)
        if position_id:
            positions = positions.filter(Position.id == position_id)
        positions = positions.order_by(Position.display_order.asc(), Position.id.asc()).all()

        for position in positions:
            candidates = Candidate.query.filter_by(position_id=position.id).order_by(Candidate.display_order.asc(), Candidate.id.asc()).all()
            candidate_results = []
            total_valid_votes = 0

            for candidate in candidates:
                votes = Vote.query.filter_by(candidate_id=candidate.id, election_id=election.id).count()
                total_valid_votes += votes
                candidate_results.append({
                    "candidate_id": candidate.id,
                    "candidate_name": (candidate.full_name or candidate.name or "Pending Candidate").strip() or "Pending Candidate",
                    "candidate_photo": candidate.photo,
                    "votes": votes,
                    "percentage": 0.0,
                })

            for item in candidate_results:
                item["percentage"] = calculate_percentages(item["votes"], total_valid_votes)

            candidate_results.sort(key=lambda item: (-item["votes"], item["candidate_name"]))
            for rank, item in enumerate(candidate_results, start=1):
                item["rank"] = rank

            winner = candidate_results[0] if candidate_results else None
            payload.append({
                "election_id": election.id,
                "election_title": election.title,
                "election_status": election.status,
                "position_id": position.id,
                "position_name": position.name,
                "candidates": candidate_results,
                "winner": winner,
                "total_votes": total_valid_votes,
            })

    return payload


def deduplicate_students(students):
    seen_keys = set()
    unique_students = []
    for student in students:
        key = (student.student_id or "").strip() or (student.username or "").strip() or (student.full_name or "").strip() or str(student.id)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_students.append(student)
    return unique_students


def get_unique_active_students():
    return deduplicate_students(
        Student.query.filter(
            Student.status == "Active",
            Student.organization_id == current_organization_id()
        )
        .order_by(Student.full_name.asc(), Student.class_name.asc())
        .all()
    )


def calculate_participation(election_id=None):
    org_id = current_organization_id()
    election_filter = Election.query

    if org_id is not None:
        election_filter = election_filter.filter(
            Election.organization_id == org_id
        )

    if election_id:
        election_filter = election_filter.filter(Election.id == election_id)

    elections = election_filter.all()
    participation = []

    for election in elections:
        base_time = election.created_at or datetime.utcnow()
        eligible_query = Student.query.filter(
            Student.status == "Active",
            Student.organization_id == org_id,
            Student.created_at >= base_time,
        )

        if not eligible_query.first():
            eligible_query = Student.query.filter(
                Student.status == "Active",
                Student.organization_id == org_id
            )

        eligible_students = deduplicate_students(
            eligible_query.order_by(Student.full_name.asc(), Student.class_name.asc()).all()
        )
        eligible_count = len(eligible_students)
        voted_students = (
            db.session.query(Vote.student_id)
            .filter(Vote.election_id == election.id)
            .distinct()
            .count()
        )

        if voted_students > eligible_count:
            eligible_count = voted_students

        not_voted_students = max(eligible_count - voted_students, 0)
        participation_rate = round((voted_students / eligible_count * 100), 1) if eligible_count else 0.0

        participation.append({
            "election_id": election.id,
            "election_title": election.title,
            "registered_students": eligible_count,
            "students_voted": voted_students,
            "students_remaining": not_voted_students,
            "participation_rate": participation_rate,
        })

    return participation


def determine_winners(election_id=None):
    results = get_results_by_position(election_id=election_id)
    winners = []
    for item in results:
        winner = item["winner"]
        winners.append({
            "election_id": item["election_id"],
            "election_title": item["election_title"],
            "position_id": item["position_id"],
            "position_name": item["position_name"],
            "winner": winner,
            "candidate_name": winner["candidate_name"] if winner else "No winner",
            "votes": winner["votes"] if winner else 0,
            "runner_up": item["candidates"][1] if len(item["candidates"]) > 1 else None,
            "third": item["candidates"][2] if len(item["candidates"]) > 2 else None,
        })
    return winners


# =====================================
# ELECTION CATEGORY HELPERS
# =====================================

DEFAULT_CATEGORIES = ["Presidential", "Parliamentary", "Local Council"]


def get_category(category_id):
    """Fetch a category by id, scoped to the current organization."""
    org_id = current_organization_id()
    return ElectionCategory.query.filter_by(
        id=category_id,
        organization_id=org_id,
    ).first()


def get_categories_for_election(election_id):
    """Return all categories defined for a specific election, org-scoped."""
    org_id = current_organization_id()
    return ElectionCategory.query.filter_by(
        election_id=election_id,
        organization_id=org_id,
    ).order_by(ElectionCategory.display_order.asc(), ElectionCategory.id.asc()).all()


def ensure_default_categories(election_id):
    """Create default categories for an election if it has none.

    Also ensures corresponding ResultsVisibility rows exist for each category.
    """
    org_id = current_organization_id()
    election = org_scoped_get(Election, election_id)

    existing = ElectionCategory.query.filter_by(
        election_id=election.id,
        organization_id=org_id,
    ).first()

    if existing:
        return get_categories_for_election(election.id)

    categories = []
    for order, name in enumerate(DEFAULT_CATEGORIES):
        cat = ElectionCategory(
            organization_id=org_id,
            election_id=election.id,
            name=name,
            description=f"{name} race category",
            display_order=order,
            status="Active",
        )
        db.session.add(cat)
        db.session.flush()
        vis = ResultsVisibility(
            category_id=cat.id,
            organization_id=org_id,
            election_id=election.id,
            is_published=False,
            broadcasted_at=None,
        )
        db.session.add(vis)
        categories.append(cat)

    db.session.commit()
    return categories


def get_or_create_category(election_id, category_name):
    """Return an existing category by name for the given election, or create it."""
    org_id = current_organization_id()
    cat = ElectionCategory.query.filter_by(
        election_id=election_id,
        organization_id=org_id,
        name=category_name,
    ).first()

    if cat:
        return cat

    cat = ElectionCategory(
        organization_id=org_id,
        election_id=election_id,
        name=category_name,
        status="Active",
    )
    db.session.add(cat)
    db.session.flush()

    vis = ResultsVisibility(
        category_id=cat.id,
        organization_id=org_id,
        election_id=election_id,
        is_published=False,
    )
    db.session.add(vis)
    db.session.commit()
    return cat


def get_results_by_category(election_id):
    """Return results grouped by category for a given election.

    Each category contains its positions, candidates, vote counts, and winner.
    Categories with no positions are still included (empty results list).
    """
    org_id = current_organization_id()
    election = Election.query.filter_by(
        id=election_id,
        organization_id=org_id,
    ).first()

    if not election:
        return []

    categories = get_categories_for_election(election.id)
    if not categories:
        categories = ensure_default_categories(election.id)

    # Legacy databases may have positions created before categories existed.
    # Attach those positions to the first category so their existing votes are
    # still included in the official voter-facing results.
    uncategorized_positions = Position.query.filter_by(
        election_id=election.id,
        category_id=None,
    ).all()
    if uncategorized_positions and categories:
        for position in uncategorized_positions:
            position.category_id = categories[0].id
        db.session.commit()

    payload = []
    for cat in categories:
        positions = Position.query.filter_by(
            election_id=election.id,
            category_id=cat.id,
        ).order_by(Position.display_order.asc(), Position.id.asc()).all()

        category_results = []
        total_votes = 0

        for position in positions:
            candidates = Candidate.query.filter_by(
                position_id=position.id,
            ).order_by(Candidate.display_order.asc(), Candidate.id.asc()).all()

            candidate_results = []
            position_votes = 0

            for candidate in candidates:
                votes = Vote.query.filter_by(
                    candidate_id=candidate.id,
                    election_id=election.id,
                ).count()
                position_votes += votes
                total_votes += votes
                candidate_results.append({
                    "candidate_id": candidate.id,
                    "candidate_name": (candidate.full_name or candidate.name or "Pending Candidate").strip() or "Pending Candidate",
                    "candidate_photo": candidate.photo,
                    "votes": votes,
                    "percentage": 0.0,
                })

            for item in candidate_results:
                item["percentage"] = calculate_percentages(item["votes"], position_votes if position_votes else 1)

            candidate_results.sort(key=lambda item: (-item["votes"], item["candidate_name"]))
            for rank, item in enumerate(candidate_results, start=1):
                item["rank"] = rank

            winner = candidate_results[0] if candidate_results else None
            category_results.append({
                "election_id": election.id,
                "election_title": election.title,
                "position_id": position.id,
                "position_name": position.name,
                "candidates": candidate_results,
                "winner": winner,
                "total_votes": position_votes,
            })

        vis = ResultsVisibility.query.filter_by(
            category_id=cat.id,
            organization_id=org_id,
        ).first()

        is_published = vis.is_published if vis else False

        payload.append({
            "category_id": cat.id,
            "category_name": cat.name,
            "description": cat.description,
            "positions": category_results,
            "winner": category_results[0]["winner"] if category_results and category_results[0]["winner"] else None,
            "total_votes": total_votes,
            "is_published": is_published,
            "broadcasted_at": vis.broadcasted_at if vis else None,
        })

    return payload


def is_category_published(category_id):
    """Check whether a category's results are currently published to voters."""
    org_id = current_organization_id()
    vis = ResultsVisibility.query.filter_by(
        category_id=category_id,
        organization_id=org_id,
    ).first()
    return vis is not None and vis.is_published


def publish_category_results(category_id):
    """Publish results for a single category, making them visible to all voters."""
    org_id = current_organization_id()
    cat = get_category(category_id)
    if not cat:
        return False

    vis = ResultsVisibility.query.filter_by(
        category_id=category_id,
        organization_id=org_id,
        election_id=cat.election_id,
    ).first()

    if not vis:
        vis = ResultsVisibility(
            category_id=category_id,
            organization_id=org_id,
            election_id=cat.election_id,
            is_published=True,
            broadcasted_at=datetime.utcnow(),
        )
        db.session.add(vis)
    else:
        vis.is_published = True
        vis.broadcasted_at = datetime.utcnow()
        db.session.add(vis)

    db.session.add(AuditLog(
        organization_id=org_id,
        user=str(session.get("admin_id")),
        action=f"Published results for category: {cat.name}"
    ))
    db.session.commit()
    return True


def unpublish_category_results(category_id):
    """Hide results for a single category, revoking voter access."""
    org_id = current_organization_id()
    cat = get_category(category_id)
    if not cat:
        return False

    vis = ResultsVisibility.query.filter_by(
        category_id=category_id,
        organization_id=org_id,
    ).first()

    if vis:
        vis.is_published = False
        vis.broadcasted_at = None
        db.session.add(vis)

    db.session.add(AuditLog(
        organization_id=org_id,
        user=str(session.get("admin_id")),
        action=f"Hidden results for category: {cat.name}"
    ))
    db.session.commit()
    return True


def generate_dashboard_statistics(election_id=None):
    org_id = current_organization_id()

    # A requested election is only honored when it belongs to this
    # organization; foreign or unknown ids fall back to the org-wide view.
    if election_id:
        owns_election = Election.query.filter_by(
            id=election_id,
            organization_id=org_id
        ).first() is not None

        if not owns_election:
            election_id = None

    results = get_results_by_position(election_id=election_id)
    participation = calculate_participation(election_id=election_id)
    winners = determine_winners(election_id=election_id)
    total_votes = sum(item["total_votes"] for item in results)

    if election_id:
        total_candidates = Candidate.query.filter_by(
            organization_id=org_id,
            election_id=election_id
        ).count()
        total_positions = Position.query.filter_by(
            organization_id=org_id,
            election_id=election_id
        ).count()
        total_elections = 1 if Election.query.filter_by(
            id=election_id,
            organization_id=org_id
        ).first() else 0
    else:
        total_candidates = Candidate.query.filter_by(
            organization_id=org_id
        ).count()
        total_positions = Position.query.filter_by(
            organization_id=org_id
        ).count()
        total_elections = Election.query.filter_by(
            organization_id=org_id
        ).count()

    return {
        "total_votes": total_votes,
        "total_candidates": total_candidates,
        "total_positions": total_positions,
        "total_elections": total_elections,
        "participation": participation[0] if participation else {
            "registered_students": 0,
            "students_voted": 0,
            "students_remaining": 0,
            "participation_rate": 0.0,
        },
        "winners": winners,
        "results": results,
    }


def purge_test_data():
    deleted_students = 0
    deleted_votes = 0
    org_id = current_organization_id()

    test_students = Student.query.filter(
        Student.organization_id == org_id,
        Student.full_name.ilike('%test%') |
        Student.username.ilike('%test%') |
        Student.student_id.ilike('%test%') |
        Student.full_name.ilike('%demo%')
    ).all()

    for student in test_students:
        Vote.query.filter(Vote.student_id == student.id).delete(synchronize_session=False)
        db.session.delete(student)
        deleted_students += 1

    test_votes = Vote.query.filter(
        Vote.organization_id == org_id,
        Vote.student_id.is_(None)
    ).all()
    for vote in test_votes:
        db.session.delete(vote)
        deleted_votes += 1

    db.session.add(AuditLog(
        organization_id=org_id,
        user=str(session.get("admin_id")),
        action="Purged test students and test votes"
    ))
    db.session.commit()
    return deleted_students + deleted_votes


def reset_all_votes():
    """Danger-zone reset: clears ALL voting data but ONLY for the current
    administrator's organization. Other organizations are never touched."""
    org_id = current_organization_id()

    deleted_votes = Vote.query.filter_by(organization_id=org_id).delete(
        synchronize_session=False
    )
    Candidate.query.filter_by(organization_id=org_id).delete(synchronize_session=False)
    Position.query.filter_by(organization_id=org_id).delete(synchronize_session=False)
    Student.query.filter_by(organization_id=org_id).delete(synchronize_session=False)
    Election.query.filter_by(organization_id=org_id).delete(synchronize_session=False)

    db.session.add(AuditLog(
        organization_id=org_id,
        user=str(session.get("admin_id")),
        action="Reset all voting records and election data"
    ))
    db.session.commit()
    return deleted_votes


def build_reports_context(election_id=None):
    stats = generate_dashboard_statistics(election_id=election_id)

    org_id = current_organization_id()
    elections = Election.query.filter_by(
        organization_id=org_id
    ).order_by(Election.id.desc()).all()
    active_elections = Election.query.filter(
        Election.organization_id == org_id,
        Election.status.in_(["Active", "Open", "Live", "Running"])
    ).count()
    upcoming_elections = Election.query.filter(
        Election.organization_id == org_id,
        Election.status.in_(["Draft", "Upcoming", "Scheduled"])
    ).count()
    completed_elections = Election.query.filter(
        Election.organization_id == org_id,
        Election.status.in_(["Closed", "Completed"])
    ).count()

    unique_students = get_unique_active_students()
    active_students = len(unique_students)
    aggregate_voted = db.session.query(Vote.student_id).filter(
        Vote.organization_id == org_id
    ).distinct().count()
    aggregate_not_voted = max(active_students - aggregate_voted, 0)
    aggregate_participation = round((aggregate_voted / active_students * 100), 1) if active_students else 0.0

    kpi_cards = [
        {"label": "Total Elections", "value": stats["total_elections"], "detail": "Registered election cycles", "icon": "◉", "trend": "+0%"},
        {"label": "Active Election", "value": active_elections, "detail": "Live operations", "icon": "●", "trend": "+1"},
        {"label": "Upcoming Elections", "value": upcoming_elections, "detail": "Scheduled soon", "icon": "△", "trend": "+0"},
        {"label": "Completed Elections", "value": completed_elections, "detail": "Closed and finalized", "icon": "✓", "trend": "+2"},
        {"label": "Registered Students", "value": active_students, "detail": "Eligible voters", "icon": "◌", "trend": "+3"},
        {"label": "Students Voted", "value": aggregate_voted, "detail": "Participation recorded", "icon": "◎", "trend": "+5%"},
        {"label": "Participation Rate", "value": f"{aggregate_participation:.1f}%", "detail": "Current turnout", "icon": "◍", "trend": "+4%"},
    ]

    top_candidates = []
    for entry in stats["results"]:
        for candidate in entry.get("candidates", [])[:3]:
            top_candidates.append({
                "position": entry.get("position_name", "Position"),
                "name": candidate.get("candidate_name", "Pending Candidate"),
                "votes": candidate.get("votes", 0),
                "percentage": candidate.get("percentage", 0.0),
            })

    position_summary = []
    for entry in stats["results"]:
        winner_name = entry.get("winner", {}).get("candidate_name") if entry.get("winner") else "Pending Candidate"
        position_summary.append({
            "position": entry.get("position_name", "Position"),
            "winner": winner_name,
            "votes": entry.get("total_votes", 0),
        })

    department_breakdown = []
    department_counts = {}
    for student in unique_students:
        department = student.department or "Unspecified"
        department_counts[department] = department_counts.get(department, 0) + 1
    for name, count in sorted(department_counts.items()):
        department_breakdown.append({"name": name, "count": count})

    class_breakdown = []
    class_counts = {}
    for student in unique_students:
        class_name = student.class_name or "Unspecified"
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
    for name, count in sorted(class_counts.items()):
        class_breakdown.append({"name": name, "count": count})

    student_tracking = []
    for student in unique_students:
        has_voted = Vote.query.filter(Vote.student_id == student.id).first() is not None
        student_tracking.append({
            "student_id": student.student_id,
            "full_name": student.full_name or "Unnamed Student",
            "class_name": student.class_name or "-",
            "department": student.department or "-",
            "vote_status": "Voted" if has_voted else "Not Voted",
        })

    return {
        "stats": stats,
        "elections": elections,
        "selected_election_id": election_id,
        "kpi_cards": kpi_cards,
        "participation": {
            "registered_students": active_students,
            "students_voted": aggregate_voted,
            "students_remaining": aggregate_not_voted,
            "participation_rate": aggregate_participation,
        },
        "top_candidates": top_candidates[:6],
        "positions": position_summary[:6],
        "department_breakdown": department_breakdown,
        "class_breakdown": class_breakdown,
        "student_tracking": student_tracking,
        "filters": [
            "Election",
            "Academic Year",
            "Candidate",
            "Position",
            "Department",
            "Class",
            "Gender",
            "Winner",
            "Vote Status",
            "Date Range",
        ],
        "total_votes": stats["total_votes"],
        "total_candidates": stats["total_candidates"],
        "total_elections": stats["total_elections"],
        "winners": stats["winners"],
    }


def publish_results(election_id):
    election = org_scoped_get(Election, election_id)
    election.visibility = "Visible"
    election.show_live_results = True
    db.session.add(election)
    db.session.add(AuditLog(
        organization_id=current_organization_id(),
        user=str(session.get("admin_id")),
        action=f"Published results for {election.title}"
    ))
    db.session.commit()
    return True


def unpublish_results(election_id):
    election = org_scoped_get(Election, election_id)
    election.visibility = "Hidden"
    election.show_live_results = False
    db.session.add(election)
    db.session.add(AuditLog(
        organization_id=current_organization_id(),
        user=str(session.get("admin_id")),
        action=f"Hidden results for {election.title}"
    ))
    db.session.commit()
    return True


# ======================================
# RESULTS PAGE
# ======================================

@reports.route("/admin/results")
@admin_required
def results_page():
    election_id = request.args.get("election_id", type=int)
    org_id = current_organization_id()
    elections = Election.query.filter_by(
        organization_id=org_id
    ).order_by(Election.id.desc()).all()

    if election_id is None and elections:
        election_id = elections[0].id

    if election_id:
        election = Election.query.filter_by(
            id=election_id,
            organization_id=org_id,
        ).first()
        if election:
            categories = get_categories_for_election(election.id)
            if not categories:
                categories = ensure_default_categories(election.id)
        else:
            categories = []
    else:
        categories = []

    stats = generate_dashboard_statistics(election_id=election_id)
    category_results = get_results_by_category(election_id) if election_id else []
    selected_category_id = request.args.get("category_id", type=int)
    selected_category = next(
        (
            category
            for category in category_results
            if category["category_id"] == selected_category_id
        ),
        None,
    )
    if selected_category is None and category_results:
        selected_category = category_results[0]
    selected_position_id = request.args.get("position_id", type=int)
    selected_position = None
    if selected_category:
        selected_position = next(
            (
                position
                for position in selected_category["positions"]
                if position["position_id"] == selected_position_id
            ),
            None,
        )
        if selected_position is None and selected_category["positions"]:
            selected_position = selected_category["positions"][0]
    settings = get_settings()

    return render_template(
        "admin_results_dashboard.html",
        stats=stats,
        elections=elections,
        selected_election_id=election_id,
        results=stats["results"],
        categories=categories,
        category_results=category_results,
        selected_category=selected_category,
        selected_position=selected_position,
        allow_voter_results=bool(settings and settings.allow_voter_results),
    )


# ======================================
# REPORT DASHBOARD
# ======================================

@reports.route("/admin/reports")
@admin_required
def reports_page():
    context = build_reports_context()
    return render_template(
        "reports.html",
        **context,
    )


# ======================================
# WINNER CALCULATION
# ======================================

@reports.route("/admin/results/winner/<int:position_id>")
@admin_required
def get_winner(position_id):
    position = org_scoped_get(Position, position_id)
    results = get_results_by_position(position_id=position.id)
    if not results:
        return {"winner": "No winner", "votes": 0}
    winner = results[0]["winner"]
    return {
        "winner": winner["candidate_name"] if winner else "No winner",
        "votes": winner["votes"] if winner else 0,
    }


# ======================================
# EXPORT RESULTS CSV
# ======================================

@reports.route("/admin/reports/export")
@admin_required
def export_results():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Election", "Position", "Candidate", "Votes", "Percentage"])

    # Export only THIS organization's results.
    org_id = current_organization_id()
    elections = Election.query.filter_by(
        organization_id=org_id
    ).order_by(Election.id.desc()).all()
    for election in elections:
        positions = Position.query.filter_by(election_id=election.id).all()
        for position in positions:
            candidates = Candidate.query.filter_by(position_id=position.id).all()
            total_valid_votes = sum(Vote.query.filter_by(candidate_id=candidate.id, election_id=election.id).count() for candidate in candidates)
            for candidate in candidates:
                votes = Vote.query.filter_by(candidate_id=candidate.id, election_id=election.id).count()
                percentage = calculate_percentages(votes, total_valid_votes)
                writer.writerow([election.title, position.name, (candidate.full_name or candidate.name or "Pending Candidate").strip() or "Pending Candidate", votes, percentage])

    log = AuditLog(
        organization_id=org_id,
        user=str(session.get("admin_id")) or "ADMIN",
        action="Exported election results"
    )
    db.session.add(log)
    db.session.commit()

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=myvoice_results.csv"
    return response


def export_participation_excel(kind="voted"):
    if openpyxl is None:
        flash("Excel export requires openpyxl library", "danger")
        return None

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Participation Report"

    ws["A1"] = "Student Name"
    ws["B1"] = "Student ID"
    ws["C1"] = "Class"
    ws["D1"] = "Department"
    ws["E1"] = "Election"
    ws["F1"] = "Status"

    if kind == "not_voted":
        students = Student.query.filter(
            Student.status == "Active",
            Student.organization_id == current_organization_id()
        ).all()
        rows = []
        for student in students:
            has_vote = db.session.query(Vote.id).filter(
                Vote.student_id == student.id,
                Vote.organization_id == current_organization_id()
            ).first() is not None
            if not has_vote:
                rows.append({
                    "name": student.full_name or student.student_id,
                    "student_id": student.student_id,
                    "class_name": student.class_name or "-",
                    "department": student.department or "-",
                    "election": "All Elections",
                    "status": "Not Voted",
                })
    else:
        voted_student_ids = db.session.query(Vote.student_id).filter(
            Vote.organization_id == current_organization_id()
        ).distinct().all()
        voted_ids = {student_id for (student_id,) in voted_student_ids if student_id is not None}
        rows = []
        for student in Student.query.filter(
            Student.status == "Active",
            Student.organization_id == current_organization_id()
        ).all():
            if student.id in voted_ids:
                rows.append({
                    "name": student.full_name or student.student_id,
                    "student_id": student.student_id,
                    "class_name": student.class_name or "-",
                    "department": student.department or "-",
                    "election": "All Elections",
                    "status": "Voted",
                })

    for index, row in enumerate(rows, start=2):
        ws[f"A{index}"] = row["name"]
        ws[f"B{index}"] = row["student_id"]
        ws[f"C{index}"] = row["class_name"]
        ws[f"D{index}"] = row["department"]
        ws[f"E{index}"] = row["election"]
        ws[f"F{index}"] = row["status"]

    return wb


@reports.route("/admin/results/publish/<int:election_id>", methods=["POST"])
@reports.route("/admin/reports/publish/<int:election_id>", methods=["POST"])
@admin_required
def publish_results_route(election_id):
    publish_results(election_id)
    flash("Results published", "success")
    return redirect(url_for("reports.results_page", election_id=election_id))


@reports.route("/admin/results/unpublish/<int:election_id>", methods=["POST"])
@reports.route("/admin/reports/unpublish/<int:election_id>", methods=["POST"])
@admin_required
def unpublish_results_route(election_id):
    unpublish_results(election_id)
    flash("Results hidden", "success")
    return redirect(url_for("reports.results_page", election_id=election_id))


# ======================================
# CATEGORY-LEVEL PUBLISH / UNPUBLISH
# ======================================

@reports.route("/admin/results/publish-category/<int:category_id>", methods=["POST"])
@admin_required
def publish_category_route(category_id):
    cat = get_category(category_id)
    if not cat:
        flash("Category not found", "danger")
        return redirect(url_for("reports.results_page", election_id=request.form.get("election_id", type=int)))
    publish_category_results(category_id)
    flash(f"Results published for category: {cat.name}", "success")
    return redirect(url_for("reports.results_page", election_id=cat.election_id))


@reports.route("/admin/results/unpublish-category/<int:category_id>", methods=["POST"])
@admin_required
def unpublish_category_route(category_id):
    cat = get_category(category_id)
    if not cat:
        flash("Category not found", "danger")
        return redirect(url_for("reports.results_page", election_id=request.form.get("election_id", type=int)))
    unpublish_category_results(category_id)
    flash(f"Results hidden for category: {cat.name}", "success")
    return redirect(url_for("reports.results_page", election_id=cat.election_id))


@reports.route("/admin/results/categories/<int:election_id>")
@admin_required
def election_categories_route(election_id):
    election = org_scoped_get(Election, election_id)
    categories = get_categories_for_election(election.id)
    if not categories:
        categories = ensure_default_categories(election.id)

    result = []
    for cat in categories:
        vis = ResultsVisibility.query.filter_by(
            category_id=cat.id,
            organization_id=current_organization_id(),
        ).first()
        result.append({
            "id": cat.id,
            "name": cat.name,
            "description": cat.description,
            "display_order": cat.display_order,
            "is_published": vis.is_published if vis else False,
            "broadcasted_at": vis.broadcasted_at.isoformat() if vis and vis.broadcasted_at else None,
        })

    return json.jsonify({"categories": result})


@reports.route("/admin/reports/export/voted-excel")
@admin_required
def export_voted_students_excel():
    wb = export_participation_excel("voted")
    if wb is None:
        return redirect(url_for("reports.reports_page"))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response.headers["Content-Disposition"] = "attachment; filename=myvoice_voted_students.xlsx"
    return response


@reports.route("/admin/reports/reset-votes", methods=["POST"])
@admin_required
def reset_votes_route():
    deleted_votes = reset_all_votes()
    flash(f"Vote records cleared successfully ({deleted_votes} ballots removed)", "success")
    return redirect(url_for("reports.reports_page"))


@reports.route("/admin/reports/export/not-voted-excel")
@admin_required
def export_not_voted_students_excel():
    wb = export_participation_excel("not_voted")
    if wb is None:
        return redirect(url_for("reports.reports_page"))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response.headers["Content-Disposition"] = "attachment; filename=myvoice_not_voted_students.xlsx"
    return response

