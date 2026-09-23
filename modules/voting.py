from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort
)

from werkzeug.security import (
    check_password_hash
)

from modules.database import (
    db,
    Student,
    Candidate,
    Position,
    Election,
    Vote,
    AuditLog,
    SystemSetting
)

from modules.settings import get_settings

from modules.reports import get_results_by_position, get_results_by_category, calculate_participation, determine_winners

from modules.security import log_security_event

from datetime import datetime



voting = Blueprint(
    "voting",
    __name__
)



# ======================================
# VOTER SESSION HELPERS
# ======================================

def _current_voter():
    """Return the logged-in Student row for this session.

    The organization context ALWAYS comes from the voter's own record and
    from the session established at login - never from the frontend."""
    voter_id = session.get("voter_id")
    if not voter_id:
        return None
    student = Student.query.get(voter_id)
    if student is None:
        return None
    # Session must still point at the same organization as the voter.
    if session.get("voter_org_id") != student.organization_id:
        return None
    # Shared result/report queries use the authenticated organization context.
    # Keep it synchronized for voter sessions as well as admin sessions.
    session["organization_id"] = student.organization_id
    return student


def _election_for_voter_or_404(election_id, student):
    """Fetch an election and verify it belongs to the voter's organization."""
    election = Election.query.get(election_id)
    if election is None or election.organization_id != student.organization_id:
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Voter %s (%s) attempted to access election #%s outside "
                "organization #%s"
                % (
                    student.id,
                    student.student_id,
                    election_id,
                    student.organization_id,
                )
            ),
        )
        abort(404)
    return election


def _voter_results_enabled(student):
    settings = SystemSetting.query.filter_by(
        organization_id=student.organization_id
    ).first()
    return bool(settings and settings.allow_voter_results)


# ======================================
# VOTER LOGIN
# ======================================
# Voter authentication lives in modules/auth.py (auth.voter_login) with
# organization-aware lookup, rate limiting and audit logging. The duplicate
# org-blind login form previously kept here was removed so that
# /voter/login has exactly ONE owner across the whole application.


# ======================================
# VOTER DASHBOARD
# ======================================

@voting.route(
    "/voter/dashboard"
)
def voter_dashboard():

    if "voter_id" not in session:
        return redirect(
            url_for(
                "auth.voter_login"
            )
        )

    student = _current_voter()
    if student is None:
        session.clear()
        return redirect(url_for("auth.voter_login"))

    # A voter may ONLY ever see elections published by their OWN organization.
    available_elections = Election.query.filter_by(
        organization_id=student.organization_id
    ).order_by(Election.id.desc()).all()
    
    # Load candidates for each election
    for election in available_elections:
        if election.status not in ['Closed', 'Archived']:
            election.candidates = Candidate.query.filter_by(election_id=election.id).filter(Candidate.status == 'Published').all()
            for candidate in election.candidates:
                candidate.election = election
                if hasattr(candidate, 'position') and candidate.position:
                    candidate.position_name = candidate.position.name
                else:
                    candidate.position_name = 'Candidate'
                # Get the admin who approved this candidate
                admin_id = candidate.created_by
                from modules.database import Admin
                admin = Admin.query.get(admin_id) if admin_id else None
                candidate.admin_name = admin.full_name if admin else 'System Admin'
            election.candidates_list = election.candidates
        else:
            election.candidates = []
            election.candidates_list = []
    
    results_visibility_enabled = _voter_results_enabled(student)
    published_results = []
    if results_visibility_enabled:
        for election in available_elections:
            published_results.append({
                "election_id": election.id,
                "title": election.title,
            })

    return render_template(
        "voter_dashboard.html",
        elections=available_elections,
        published_results=published_results,
        results_visibility_enabled=results_visibility_enabled,
    )



# ======================================
# VOTING PAGE
# ======================================

@voting.route(
    "/voter/vote/<int:election_id>"
)
def vote_page(
    election_id
):

    if "voter_id" not in session:
        return redirect(url_for("auth.voter_login"))

    student = _current_voter()
    if student is None:
        session.clear()
        return redirect(url_for("auth.voter_login"))

    election = _election_for_voter_or_404(election_id, student)

    if election.status in ["Closed", "Archived"]:
        flash("This election is closed and no longer accepting votes.", "danger")
        return redirect(url_for("voting.voter_dashboard"))

    # Check if voter has already voted in this election
    already_voted = Vote.query.filter_by(
        student_id=student.id,
        election_id=election.id
    ).first() is not None

    # Get all positions and published candidates only
    positions = Position.query.filter_by(election_id=election.id).all()
    candidates = Candidate.query.filter_by(election_id=election.id, status="Published").all()

    # If no positions, show empty ballot (allow voting anyway)
    if not positions:
        flash("No positions configured yet, but you can still vote.", "info")

    session["vote_election_id"] = election.id
    session["vote_positions"] = [position.id for position in positions]
    session["vote_candidates"] = {candidate.id: candidate.position_id for candidate in candidates}

    # Get system settings for school info
    system_settings = get_settings()
    
    # Generate countdown time for election end
    countdown_time = None
    if election.end_date:
        countdown_time = election.end_date.isoformat()

    return render_template(
        "voter_ballot.html",
        election=election,
        positions=positions,
        candidates=candidates,
        student=student,
        current_position=0,
        progress=0,
        system_settings=system_settings,
        countdown_time=countdown_time,
        already_voted=already_voted
    )




# ======================================
# SUBMIT VOTE
# ======================================

@voting.route(
    "/voter/submit-vote",
    methods=[
        "POST"
    ]
)
def submit_vote():

    if "voter_id" not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {
                "success": False,
                "message": "Session expired. Please log in again."
            }, 401
        flash("Your session is invalid. Please log in again.", "danger")
        return redirect(url_for("auth.voter_login"))

    voter_id = session["voter_id"]
    election_id = request.form.get("election_id", type=int)
    student = Student.query.get(voter_id)

    if student is None or session.get("voter_org_id") != (
        student.organization_id
    ):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": False, "message": "Your session is invalid. Please log in again."}, 401
        flash("Your session is invalid. Please log in again.", "danger")
        return redirect(url_for("auth.voter_login"))

    # CRITICAL: a vote may only ever be recorded for an election owned by the
    # voter's own organization.
    election = Election.query.get(election_id)
    if election is None or election.organization_id != student.organization_id:
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Voter %s (%s) attempted to submit a ballot for election #%s "
                "outside organization #%s"
                % (
                    student.id,
                    student.student_id,
                    election_id,
                    student.organization_id,
                )
            ),
        )
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": False, "message": "This election is not available."}, 404
        abort(404)

    # `election` was already fetched and ownership-verified above.

    # Check if voter has already voted in this election
    existing_vote = Vote.query.filter_by(
        student_id=voter_id,
        election_id=election_id
    ).first()

    if existing_vote:
        # Log the duplicate voting attempt
        db.session.add(AuditLog(
            organization_id=student.organization_id,
            user=student.full_name,
            user_id=str(student.id),
            username=student.username or student.student_id,
            full_name=student.full_name,
            role="Student",
            action="Duplicate Vote Attempt",
            module="Voting",
            description=f"Voter attempted to cast a second vote in election '{election.title}' after already voting.",
            severity="Warning",
            status="Blocked"
        ))
        db.session.commit()

        msg = "⚠️ SECURITY ALERT: You have already cast your vote in this election. Duplicate voting is strictly prohibited and has been logged."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {
                "success": False,
                "duplicate_vote": True,
                "message": msg
            }, 403
        flash(msg, "danger")
        return redirect(url_for("voting.vote_page", election_id=election_id))

    positions = Position.query.filter_by(election_id=election_id).all()



    selected_ids = []

    for position in positions:
        candidate_id = request.form.get(f"candidate_id_{position.id}")
        if not candidate_id:
            msg = "Please make a selection for every position before submitting."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, "danger")
            return redirect(url_for("voting.vote_page", election_id=election_id))

        candidate = Candidate.query.get(candidate_id)
        if candidate is None or candidate.position_id != position.id:
            msg = "One of your selections is invalid."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, "danger")
            return redirect(url_for("voting.vote_page", election_id=election_id))
        selected_ids.append(int(candidate_id))

    try:
        for candidate_id in selected_ids:
            vote = Vote(
                organization_id=student.organization_id,
                student_id=voter_id,
                candidate_id=candidate_id,
                election_id=election_id,
                created_at=datetime.utcnow(),
            )
            db.session.add(vote)

        student.vote_status = "Voted"
        student.voted_at = datetime.utcnow()
        student.last_election = election_id

        db.session.add(AuditLog(
            organization_id=student.organization_id,
            user=student.full_name,
            user_id=str(student.id),
            username=student.username or student.student_id,
            full_name=student.full_name,
            role="Student",
            action="Ballot submitted",
            module="Voting",
            description=f"Ballot submitted in election '{election.title}'.",
            severity="Info",
            status="Success",
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": False, "message": "Your vote could not be processed. Please try again."}, 500
        flash("Your vote could not be processed. Please try again.", "danger")
        return redirect(url_for("voting.vote_page", election_id=election_id))

    session.pop("vote_election_id", None)
    session.pop("vote_positions", None)
    session.pop("vote_candidates", None)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {
            "success": True,
            "message": "Vote recorded successfully",
            "redirect": url_for('voting.voter_dashboard')
        }
    
    flash("Your vote was submitted successfully", "success")
    return redirect(url_for("voting.voter_dashboard"))



# ======================================
# VOTER LOGOUT
# ======================================

@voting.route("/voter/results/<int:election_id>")
def voter_results(election_id):
    if "voter_id" not in session:
        return redirect(url_for("auth.voter_login"))

    student = _current_voter()
    if student is None:
        session.clear()
        return redirect(url_for("auth.voter_login"))

    election = _election_for_voter_or_404(election_id, student)
    if not _voter_results_enabled(student):
        return render_template(
            "voter_results.html",
            election=election,
            results=[],
            category_results=[],
            participation=None,
            winners=[],
            selected_category=None,
            results_hidden=True,
            results_message="Results have not been broadcast yet.",
        )

    category_results = get_results_by_category(election.id)

    if not category_results:
        return render_template(
            "voter_results.html",
            election=election,
            results=[],
            category_results=[],
            participation=None,
            winners=[],
            selected_category=None,
            results_hidden=True,
            results_message="Results have not been broadcast yet.",
        )

    selected_category_id = request.args.get("category_id", type=int)
    selected_category = None
    if selected_category_id is not None:
        selected_category = next(
            (category for category in category_results if category["category_id"] == selected_category_id),
            None,
        )
    if selected_category is None:
        selected_category = category_results[0]

    participation = calculate_participation(election_id=election.id)
    winners = determine_winners(election_id=election.id)

    return render_template(
        "voter_results.html",
        election=election,
        results=get_results_by_position(election_id=election.id),
        category_results=category_results,
        participation=participation[0] if participation else None,
        winners=winners,
        selected_category=selected_category,
        results_hidden=False,
        results_message="",
    )


@voting.route(
    "/voter/logout"
)
def voter_logout():


    session.pop(
        "voter_id",
        None
    )


    session.pop(
        "voter_name",
        None
    )



    return redirect(
        url_for(
            "auth.voter_login"
        )
    )
    