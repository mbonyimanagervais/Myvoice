from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from datetime import datetime

from modules.database import (
    db,
    Election,
    Position,
    Candidate,
    Student,
    Vote,
    AuditLog,
    Notification
)

from modules.auth import admin_required
from modules.security import (
    current_organization_id,
    org_scoped_get
)



elections = Blueprint(
    "elections",
    __name__
)



def validate_election(election):
    issues = []
    org_id = current_organization_id()
    base = Position.query
    if org_id:
        base = base.filter(Position.organization_id == org_id)

    positions = base.filter_by(election_id=election.id).all()
    position_names = [position.name.strip().lower() for position in positions if position.name and position.name.strip()]
    if len(position_names) != len(set(position_names)):
        issues.append('Duplicate positions found')

    candidates = Candidate.query.join(Position).filter(
        Position.election_id == election.id
    )
    if org_id:
        candidates = candidates.filter(Candidate.organization_id == org_id)
    candidates = candidates.all()
    if candidates:
        for candidate in candidates:
            if candidate.position_id is None:
                issues.append('Candidate without a position found')
                break
            if candidate.position and not candidate.position.election_id == election.id:
                issues.append('Candidate assigned to another election position')
                break
            if candidate.name is None or not candidate.name.strip():
                issues.append('Candidate name is missing')
                break
    else:
        issues.append('No candidates added')

    if not positions:
        issues.append('No positions configured')

    if not election.title or not election.title.strip():
        issues.append('Election title is required')

    if election.start_date and election.end_date and election.start_date >= election.end_date:
        issues.append('Election schedule is invalid')

    org_id = current_organization_id()
    student_base = Student.query
    if org_id:
        student_base = student_base.filter(Student.organization_id == org_id)
    if not student_base.count():
        issues.append('No eligible voters found')

    active_base = Election.query.filter(
        Election.id != election.id, Election.status == 'Active'
    )
    if org_id:
        active_base = active_base.filter(Election.organization_id == org_id)
    active_election = active_base.first()
    if active_election:
        issues.append('Another election is already active')

    return issues


def get_election_stats():
    org_id = current_organization_id()
    base = Election.query
    if org_id:
        base = base.filter(Election.organization_id == org_id)

    total_elections = base.count()
    draft_elections = base.filter(Election.status == 'Draft').count()
    ready_elections = base.filter(Election.status == 'Ready').count()
    active_elections = base.filter(Election.status == 'Active').count()
    closed_elections = base.filter(Election.status == 'Closed').count()
    archived_elections = base.filter(Election.status == 'Archived').count()

    cand_base = Candidate.query
    pos_base = Position.query
    vote_base = Vote.query
    student_base = Student.query
    if org_id:
        cand_base = cand_base.filter(Candidate.organization_id == org_id)
        pos_base = pos_base.filter(Position.organization_id == org_id)
        vote_base = vote_base.filter(Vote.organization_id == org_id)
        student_base = student_base.filter(Student.organization_id == org_id)

    total_candidates = cand_base.count()
    total_positions = pos_base.count()
    total_votes = vote_base.count()
    total_students = student_base.count()
    turnout = round((total_votes / total_students * 100), 1) if total_students else 0.0

    return {
        'total_elections': total_elections,
        'draft_elections': draft_elections,
        'ready_elections': ready_elections,
        'active_elections': active_elections,
        'closed_elections': closed_elections,
        'archived_elections': archived_elections,
        'total_candidates': total_candidates,
        'total_positions': total_positions,
        'total_votes': total_votes,
        'turnout_percentage': turnout,
    }


# ======================================
# VIEW ALL ELECTIONS
# ======================================

@elections.route(
    "/admin/elections"
)
@admin_required
def elections_page():

    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status_filter", "").strip()
    year_filter = request.args.get("year_filter", "").strip()

    query = Election.query
    org_id = current_organization_id()
    if org_id:
        query = query.filter(Election.organization_id == org_id)

    if search:
        query = query.filter(Election.title.contains(search))

    if status_filter:
        query = query.filter(Election.status == status_filter)

    if year_filter:
        query = query.filter(Election.election_year == year_filter)

    all_elections = query.order_by(Election.id.desc()).all()

    stats = get_election_stats()
    years_query = Election.query.filter(Election.election_year.isnot(None))
    if org_id:
        years_query = years_query.filter(Election.organization_id == org_id)
    years = [election.election_year for election in years_query.all() if election.election_year]
    statuses = ["Draft", "Ready", "Active", "Closed", "Archived"]

    return render_template(
        "elections.html",
        elections=all_elections,
        stats=stats,
        years=sorted(set(years)),
        statuses=statuses,
        search=search,
        status_filter=status_filter,
        year_filter=year_filter
    )



# ======================================
# CREATE ELECTION
# ======================================

@elections.route(
    "/admin/elections/add",
    methods=[
        "POST"
    ]
)
@admin_required
def add_election():


    title = request.form.get(
        "title"
    )


    description = request.form.get(
        "description"
    )


    election_year = request.form.get(
        "election_year"
    )



    election = Election(

        organization_id=current_organization_id(),

        title=title,

        description=description,

        election_year=election_year,

        status="Active",

        instructions=request.form.get("instructions"),

        welcome_message=request.form.get("welcome_message"),

        help_information=request.form.get("help_information"),

        visibility=request.form.get("visibility", "Visible"),

        allow_student_login_before_election=request.form.get("allow_student_login_before_election") == "on",

        show_live_results=request.form.get("show_live_results") == "on",

        auto_close=request.form.get("auto_close") == "on",

        auto_archive=request.form.get("auto_archive") == "on",

        enable_candidate_photos=request.form.get("enable_candidate_photos") == "on",

        enable_candidate_manifestos=request.form.get("enable_candidate_manifestos") == "on",

        allow_blank_votes=request.form.get("allow_blank_votes") == "on",

        enable_vote_confirmation=request.form.get("enable_vote_confirmation") == "on",

        enable_vote_receipts=request.form.get("enable_vote_receipts") == "on",

        require_final_confirmation=request.form.get("require_final_confirmation") == "on",

        theme_color=request.form.get("theme_color", "#2563eb"),

        timezone=request.form.get("timezone", "UTC"),

        default_language=request.form.get("default_language", "en")

    )

    try:
        election.max_votes_per_position = int(request.form.get("max_votes_per_position") or 1)
    except ValueError:
        election.max_votes_per_position = 1


    db.session.add(
        election
    )



    log = AuditLog(

        user="ADMIN",

        action=f"Created election {title}"

    )


    db.session.add(
        log
    )



    db.session.commit()



    flash(
        "Election created successfully",
        "success"
    )


    return redirect(
        url_for(
            "elections.elections_page"
        )
    )



# ======================================
# UPDATE ELECTION
# ======================================

@elections.route(
    "/admin/elections/update/<int:id>",
    methods=[
        "POST"
    ]
)
@admin_required
def update_election(id):


    election = org_scoped_get(
        Election,
        id
    )



    election.title = request.form.get(
        "title"
    )


    election.description = request.form.get(
        "description"
    )


    election.election_year = request.form.get(
        "election_year"
    )


    election.instructions = request.form.get(
        "instructions"
    )


    election.welcome_message = request.form.get(
        "welcome_message"
    )


    election.help_information = request.form.get(
        "help_information"
    )


    election.visibility = request.form.get(
        "visibility",
        election.visibility or "Visible"
    )


    election.allow_student_login_before_election = request.form.get(
        "allow_student_login_before_election"
    ) == "on"


    election.show_live_results = request.form.get(
        "show_live_results"
    ) == "on"


    election.auto_close = request.form.get(
        "auto_close"
    ) == "on"


    election.auto_archive = request.form.get(
        "auto_archive"
    ) == "on"


    election.enable_candidate_photos = request.form.get(
        "enable_candidate_photos"
    ) == "on"


    election.enable_candidate_manifestos = request.form.get(
        "enable_candidate_manifestos"
    ) == "on"


    election.allow_blank_votes = request.form.get(
        "allow_blank_votes"
    ) == "on"


    election.enable_vote_confirmation = request.form.get(
        "enable_vote_confirmation"
    ) == "on"


    election.enable_vote_receipts = request.form.get(
        "enable_vote_receipts"
    ) == "on"


    election.require_final_confirmation = request.form.get(
        "require_final_confirmation"
    ) == "on"


    election.theme_color = request.form.get(
        "theme_color",
        election.theme_color or "#2563eb"
    )


    election.timezone = request.form.get(
        "timezone",
        election.timezone or "UTC"
    )


    election.default_language = request.form.get(
        "default_language",
        election.default_language or "en"
    )


    try:
        election.max_votes_per_position = int(request.form.get("max_votes_per_position") or 1)
    except ValueError:
        election.max_votes_per_position = 1


    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")

    if start_date:
        election.start_date = datetime.fromisoformat(start_date)
    if end_date:
        election.end_date = datetime.fromisoformat(end_date)



    log = AuditLog(

        user="ADMIN",

        action=f"Updated election {election.title}"

    )


    db.session.add(
        log
    )


    db.session.commit()



    flash(
        "Election updated",
        "success"
    )



    return redirect(
        url_for(
            "elections.elections_page"
        )
    )



# ======================================
# CHANGE ELECTION STATUS
# ======================================

@elections.route(
    "/admin/elections/status/<int:id>"
)
@admin_required
def toggle_election_status(id):


    election = org_scoped_get(
        Election,
        id
    )



    if election.status == "Active":


        election.status = "Closed"
        flash("Election closed successfully", "success")


    elif election.status == "Draft":

        issues = validate_election(election)
        if issues:
            flash("Validation failed: " + "; ".join(issues), "danger")
            return redirect(url_for("elections.elections_page"))
        election.status = "Ready"
        flash("Election validated and moved to Ready", "success")


    elif election.status == "Ready":

        election.status = "Active"
        flash("Election opened successfully", "success")


    else:

        election.status = "Active"
        flash("Election reopened", "success")



    log = AuditLog(

        organization_id=current_organization_id(),

        user="ADMIN",

        action=f"Changed election status {election.title}"

    )


    notification = Notification(

        organization_id=current_organization_id(),

        message=f"Election {election.title} status updated to {election.status}"

    )
    db.session.add(notification)


    db.session.add(
        log
    )


    db.session.commit()



    return redirect(
        url_for(
            "elections.elections_page"
        )
    )



# ======================================
# DELETE ELECTION
# ======================================

@elections.route(
    "/admin/elections/delete/<int:id>"
)
@admin_required
def delete_election(id):


    election = org_scoped_get(
        Election,
        id
    )


    name = election.title



    db.session.delete(
        election
    )



    log = AuditLog(

        organization_id=current_organization_id(),

        user="ADMIN",

        action=f"Deleted election {name}"

    )


    db.session.add(
        log
    )



    db.session.commit()



    flash(
        "Election deleted",
        "success"
    )


    return redirect(
        url_for(
            "elections.elections_page"
        )
    )