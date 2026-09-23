from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from modules.database import (
    db,
    Position,
    Election,
    Candidate,
    Vote,
    AuditLog
)

from modules.auth import admin_required
from modules.security import (
    validate_position_name,
    validate_display_order,
    validate_max_winners,
    validate_position_code,
    log_audit,
    current_organization_id
)

from datetime import datetime


positions = Blueprint(
    "positions",
    __name__
)


# ======================================
# ORGANIZATION SCOPING HELPERS
# ======================================

def _scoped_position(position_id):
    """Fetch a position ONLY if it belongs to the administrator's organization.
    Cross-organization access attempts are blocked and logged as violations."""
    from modules.security import current_organization_id, log_security_event

    position = Position.query.get(position_id)
    if position is None:
        return None

    if position.organization_id != current_organization_id():
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Blocked cross-organization access attempt to position #%s "
                "by admin %s" % (position_id, session.get("admin_id"))
            ),
        )
        return None

    return position


def _scoped_election(election_id):
    """Fetch an election ONLY within the administrator's own organization."""
    from modules.security import current_organization_id, log_security_event

    try:
        election_pk = int(election_id)
    except (TypeError, ValueError):
        return None

    election = Election.query.filter_by(
        id=election_pk,
        organization_id=current_organization_id()
    ).first()

    if election is None and Election.query.get(election_pk) is not None:
        # The election exists but belongs to ANOTHER organization.
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Blocked cross-organization reference to election #%s by "
                "admin %s" % (election_pk, session.get("admin_id"))
            ),
        )

    return election


def position_exists(election_id, name, exclude_id=None):
    query = Position.query.filter_by(election_id=election_id, name=name)
    if exclude_id:
        query = query.filter(Position.id != exclude_id)
    return query.first() is not None


def count_candidates(position_id):
    return Candidate.query.filter_by(position_id=position_id).count()


def count_votes(position_id):
    return Vote.query.join(Candidate).filter(Candidate.position_id == position_id).count()


def get_positions_by_election(election_id):
    return Position.query.filter_by(
        election_id=election_id,
        status="Active",
        organization_id=session.get("organization_id")
    ).order_by(Position.display_order.asc(), Position.name.asc()).all()


def get_all_positions():
    return Position.query.filter_by(
        organization_id=session.get("organization_id")
    ).order_by(Position.display_order.asc(), Position.name.asc()).all()


def get_position(position_id):
    return Position.query.get(position_id)


def create_position(
    election_id,
    name,
    position_code=None,
    description=None,
    display_order=0,
    maximum_winners=1,
    status="Active",
    created_by=None
):
    validation_error = validate_position_name(name)
    if validation_error:
        return None, validation_error

    validation_error = validate_display_order(display_order)
    if validation_error:
        return None, validation_error

    validation_error = validate_max_winners(maximum_winners)
    if validation_error:
        return None, validation_error

    validation_error = validate_position_code(position_code)
    if validation_error:
        return None, validation_error

    if not election_id:
        return None, "Election is required"

    # Organization isolation: the referenced election MUST belong to the
    # administrator's own organization before a position can be attached.
    election = _scoped_election(election_id)
    if election is None:
        return None, "Election not found"

    if position_exists(election.id, name):
        return None, "Position name already exists for this election"

    position = Position(
        name=name,
        election_id=election.id,
        organization_id=current_organization_id(),
        position_code=position_code or None,
        description=description or None,
        display_order=display_order,
        maximum_winners=maximum_winners,
        status=status,
        created_by=created_by or str(session.get("admin_id")),
        updated_by=created_by or str(session.get("admin_id")),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.session.add(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Created",
        f"Position '{name}' created for election '{election.title}'"
    )

    return position, None


def update_position(
    position_id,
    name,
    position_code=None,
    description=None,
    display_order=None,
    maximum_winners=None,
    status=None,
    updated_by=None
) -> "tuple":
    position = _scoped_position(position_id)
    if position is None:
        return False, "Position not found"

    election = position.election
    if election and election.status == "Active":
        if name and name != position.name:
            return False, "Position name cannot be changed after election starts"
        if position_code and position_code != position.position_code:
            return False, "Position code cannot be changed after election starts"
        if display_order is not None and display_order != position.display_order:
            return False, "Display order cannot be changed after election starts"
        if maximum_winners is not None and maximum_winners != position.maximum_winners:
            return False, "Maximum winners cannot be changed after election starts"
        if status and status != position.status:
            return False, "Status cannot be changed after election starts"

    if name:
        validation_error = validate_position_name(name)
        if validation_error:
            return False, validation_error

    if name and position_exists(position.election_id, name, exclude_id=position.id):
        return False, "Position name already exists for this election"

    if display_order is not None:
        validation_error = validate_display_order(display_order)
        if validation_error:
            return False, validation_error

    if maximum_winners is not None:
        validation_error = validate_max_winners(maximum_winners)
        if validation_error:
            return False, validation_error

    if position_code is not None:
        validation_error = validate_position_code(position_code)
        if validation_error:
            return False, validation_error

    old_name = position.name

    if name:
        position.name = name
    if position_code is not None:
        position.position_code = position_code or None
    if description is not None:
        position.description = description or None
    if display_order is not None:
        position.display_order = display_order
    if maximum_winners is not None:
        position.maximum_winners = maximum_winners
    if status is not None:
        position.status = status

    position.updated_by = updated_by or str(session.get("admin_id"))
    position.updated_at = datetime.utcnow()

    db.session.add(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Updated",
        f"Position '{old_name}' updated"
    )

    return True, None


def delete_position(position_id):
    position = _scoped_position(position_id)
    if position is None:
        return False, "Position not found"

    if count_candidates(position.id) > 0:
        return False, "Position cannot be deleted because it has candidates"

    if count_votes(position.id) > 0:
        return False, "Position cannot be deleted because it has votes"

    election = position.election
    if election and election.status == "Active":
        return False, "Position cannot be deleted while election is active"

    name = position.name
    db.session.delete(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Deleted",
        f"Position '{name}' deleted"
    )

    return True, None


def activate_position(position_id):
    position = _scoped_position(position_id)
    if position is None:
        return False, "Position not found"

    position.status = "Active"
    position.updated_by = str(session.get("admin_id"))
    position.updated_at = datetime.utcnow()
    db.session.add(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Activated",
        f"Position '{position.name}' activated"
    )

    return True, None


def deactivate_position(position_id):
    position = _scoped_position(position_id)
    if position is None:
        return False, "Position not found"

    position.status = "Inactive"
    position.updated_by = str(session.get("admin_id"))
    position.updated_at = datetime.utcnow()
    db.session.add(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Deactivated",
        f"Position '{position.name}' deactivated"
    )

    return True, None


def archive_position(position_id):
    position = _scoped_position(position_id)
    if position is None:
        return False, "Position not found"

    position.status = "Archived"
    position.updated_by = str(session.get("admin_id"))
    position.updated_at = datetime.utcnow()
    db.session.add(position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Archived",
        f"Position '{position.name}' archived"
    )

    return True, None


def change_display_order(position_ids):
    from modules.security import log_security_event

    # Only positions owned by this organization may be reordered; any foreign
    # ids submitted from the frontend are silently rejected and logged.
    owned_positions = Position.query.filter(
        Position.id.in_(position_ids),
        Position.organization_id == current_organization_id()
    ).all()
    owned_by_id = {position.id: position for position in owned_positions}

    rejected_ids = [pid for pid in position_ids if pid not in owned_by_id]
    if rejected_ids:
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Reorder request contained foreign position ids %s blocked "
                "for admin %s" % (rejected_ids, session.get("admin_id"))
            ),
        )

    ordered_owned = [pid for pid in position_ids if pid in owned_by_id]
    for index, pos_id in enumerate(ordered_owned):
        position = owned_by_id[pos_id]
        position.display_order = index
        position.updated_by = str(session.get("admin_id"))
        position.updated_at = datetime.utcnow()
        db.session.add(position)

    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Display Order Changed",
        "Position display order updated"
    )

    return True


def get_positions_for_election(election_id):
    return Position.query.filter_by(election_id=election_id).order_by(Position.display_order.asc(), Position.name.asc()).all()


def clone_position(source_position_id, target_election_id):
    source = _scoped_position(source_position_id)
    if source is None:
        return None, "Source position not found"

    # Target election MUST be inside this organization too.
    target_election = _scoped_election(target_election_id)
    if target_election is None:
        return None, "Target election not found"

    if position_exists(target_election_id, source.name):
        return None, "A position with this name already exists in the target election"

    new_position = Position(
        name=source.name,
        election_id=target_election.id,
        organization_id=current_organization_id(),
        position_code=source.position_code,
        description=source.description,
        display_order=source.display_order,
        maximum_winners=source.maximum_winners,
        status="Active",
        created_by=str(session.get("admin_id")),
        updated_by=str(session.get("admin_id")),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.session.add(new_position)
    db.session.commit()

    log_audit(
        session.get("admin_id"),
        "Position Cloned",
        f"Position '{source.name}' cloned to election '{target_election.title}'"
    )

    return new_position, None


def get_position_statistics(position_id):
    position = _scoped_position(position_id)
    if position is None:
        return None

    return {
        "position_id": position.id,
        "position_name": position.name,
        "election_title": position.election.title if position.election else None,
        "candidate_count": count_candidates(position.id),
        "vote_count": count_votes(position.id),
        "maximum_winners": position.maximum_winners,
        "status": position.status,
        "display_order": position.display_order,
    }


# ======================================
# VIEW POSITIONS
# ======================================

@positions.route(
    "/admin/positions"
)
@admin_required
def positions_page():
    search = request.args.get("search", "").strip()
    election_filter = request.args.get("election_filter", "")
    status_filter = request.args.get("status_filter", "")
    sort_by = request.args.get("sort_by", "display_order")

    # Organization isolation: admins only ever see their own positions.
    org_id = current_organization_id()
    query = Position.query.filter_by(organization_id=org_id)

    if search:
        query = query.filter(Position.name.contains(search))

    if election_filter:
        query = query.filter(Position.election_id == election_filter)

    if status_filter:
        query = query.filter(Position.status == status_filter)

    if sort_by == "name":
        query = query.order_by(Position.name.asc())
    elif sort_by == "status":
        query = query.order_by(Position.status.asc())
    elif sort_by == "created_at":
        query = query.order_by(Position.created_at.desc())
    else:
        query = query.order_by(Position.display_order.asc(), Position.name.asc())

    all_positions = query.all()
    elections = Election.query.filter_by(
        organization_id=current_organization_id()
    ).order_by(Election.title.asc()).all()
    statuses = ["Active", "Inactive", "Archived", "Draft"]

    return render_template(
        "positions.html",
        positions=all_positions,
        elections=elections,
        search=search,
        election_filter=election_filter,
        status_filter=status_filter,
        sort_by=sort_by,
        statuses=statuses,
        count_candidates=count_candidates,
        count_votes=count_votes
    )


# ======================================
# ADD POSITION
# ======================================

@positions.route(
    "/admin/positions/add",
    methods=[
        "POST"
    ]
)
@admin_required
def add_position():
    name = request.form.get("name", "").strip()
    election_id = request.form.get("election_id")
    position_code = request.form.get("position_code", "").strip()
    description = request.form.get("description", "").strip()
    display_order = request.form.get("display_order", "0").strip()
    maximum_winners = request.form.get("maximum_winners", "1").strip()
    status = request.form.get("status", "Active").strip() or "Active"

    position, error = create_position(
        election_id=election_id,
        name=name,
        position_code=position_code or None,
        description=description or None,
        display_order=display_order,
        maximum_winners=maximum_winners,
        status=status,
        created_by=str(session.get("admin_id"))
    )

    if error:
        flash(error, "danger")
        return redirect(url_for("positions.positions_page"))

    flash("Position added successfully", "success")
    return redirect(url_for("positions.positions_page"))


# ======================================
# UPDATE POSITION
# ======================================

@positions.route(
    "/admin/positions/update/<int:id>",
    methods=[
        "POST"
    ]
)
@admin_required
def update_position_route(id):
    position = _scoped_position(id)
    if position is None:
        flash("Position not found", "danger")
        return redirect(url_for("positions.positions_page"))

    name = request.form.get("name", "").strip()
    position_code = request.form.get("position_code", "").strip()
    description = request.form.get("description", "").strip()
    display_order = request.form.get("display_order", "0").strip()
    maximum_winners = request.form.get("maximum_winners", "1").strip()
    status = request.form.get("status", "Active").strip() or "Active"

    success, error = update_position(
        id,
        name=name or None,
        position_code=position_code or None,
        description=description or None,
        display_order=int(display_order) if display_order else None,
        maximum_winners=int(maximum_winners) if maximum_winners else None,
        status=status if status != position.status else None,
        updated_by=str(session.get("admin_id"))
    )

    if error:
        flash(error, "danger")
        return redirect(url_for("positions.positions_page"))

    flash("Position updated", "success")
    return redirect(url_for("positions.positions_page"))


# ======================================
# DELETE POSITION
# ======================================

@positions.route(
    "/admin/positions/delete/<int:id>"
)
@admin_required
def delete_position_route(id):
    success, error = delete_position(id)

    if error:
        flash(error, "danger")
    else:
        flash("Position deleted", "success")

    return redirect(url_for("positions.positions_page"))


@positions.route("/admin/positions/<int:id>/activate")
@admin_required
def activate_position_route(id):
    success, error = activate_position(id)

    if error:
        flash(error, "danger")
    else:
        flash("Position activated", "success")

    return redirect(url_for("positions.positions_page"))


@positions.route("/admin/positions/<int:id>/deactivate")
@admin_required
def deactivate_position_route(id):
    success, error = deactivate_position(id)

    if error:
        flash(error, "danger")
    else:
        flash("Position deactivated", "success")

    return redirect(url_for("positions.positions_page"))


@positions.route("/admin/positions/<int:id>/archive")
@admin_required
def archive_position_route(id):
    success, error = archive_position(id)

    if error:
        flash(error, "danger")
    else:
        flash("Position archived", "success")

    return redirect(url_for("positions.positions_page"))


# ======================================
# CHANGE DISPLAY ORDER
# ======================================

@positions.route(
    "/admin/positions/reorder",
    methods=[
        "POST"
    ]
)
@admin_required
def reorder_positions():
    position_ids = request.form.getlist("position_ids")

    if not position_ids:
        flash("No positions to reorder", "danger")
        return redirect(url_for("positions.positions_page"))

    try:
        position_ids = [int(pid) for pid in position_ids]
    except ValueError:
        flash("Invalid position IDs", "danger")
        return redirect(url_for("positions.positions_page"))

    change_display_order(position_ids)
    flash("Display order updated", "success")
    return redirect(url_for("positions.positions_page"))


# ======================================
# CLONE POSITION
# ======================================

@positions.route(
    "/admin/positions/clone/<int:id>",
    methods=[
        "POST"
    ]
)
@admin_required
def clone_position_route(id):
    target_election_id = request.form.get("target_election_id")

    if not target_election_id:
        flash("Please select a target election", "danger")
        return redirect(url_for("positions.positions_page"))

    position, error = clone_position(id, target_election_id)

    if error:
        flash(error, "danger")
    else:
        flash(f"Position cloned successfully to election", "success")

    return redirect(url_for("positions.positions_page"))


# ======================================
# GET POSITION STATISTICS
# ======================================

@positions.route(
    "/admin/positions/<int:id>/stats"
)
@admin_required
def position_stats(id):
    stats = get_position_statistics(id)

    if stats is None:
        flash("Position not found", "danger")
        return redirect(url_for("positions.positions_page"))

    return render_template(
        "positions.html",
        position_stats=stats,
        positions=get_all_positions(),
        elections=Election.query.filter_by(
            organization_id=current_organization_id()
        ).order_by(Election.title.asc()).all()
    )


# ======================================
# GET POSITIONS BY ELECTION API
# ======================================

@positions.route(
    "/api/positions/<int:election_id>"
)
def get_positions_api(election_id):
    from modules.security import log_security_event

    # Voters only ever receive positions of ACTIVE elections that belong to
    # their own organization (session-scoped).
    voter_org_id = session.get("voter_org_id")
    admin_org_id = session.get("organization_id")

    if admin_org_id is not None:
        org_id = admin_org_id
    elif voter_org_id is not None:
        org_id = voter_org_id
    else:
        return {"positions": []}

    election = Election.query.filter_by(
        id=election_id,
        organization_id=org_id
    ).first()

    if election is None:
        if Election.query.get(election_id) is not None:
            log_security_event(
                action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
                description=(
                    "Blocked cross-organization positions API access for "
                    "election #%s" % election_id
                ),
            )
        return {"positions": []}

    data = Position.query.filter_by(
        election_id=election.id,
        status="Active"
    ).all()

    return {
        "positions": [
            {
                "id": position.id,
                "name": position.name,
                "position_code": position.position_code,
                "description": position.description,
                "maximum_winners": position.maximum_winners,
                "display_order": position.display_order,
                "candidate_count": count_candidates(position.id),
                "vote_count": count_votes(position.id)
            }
            for position in data
        ]
    }


# ======================================
# EXPORT POSITIONS
# ======================================

@positions.route(
    "/admin/positions/export"
)
@admin_required
def export_positions():
    from flask import Response
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Position Name",
        "Election",
        "Position Code",
        "Description",
        "Display Order",
        "Maximum Winners",
        "Status",
        "Candidate Count",
        "Vote Count",
        "Created At"
    ])

    positions = Position.query.filter_by(
        organization_id=current_organization_id()
    ).order_by(Position.display_order.asc()).all()

    for position in positions:
        writer.writerow([
            position.name,
            position.election.title if position.election else "",
            position.position_code or "",
            position.description or "",
            position.display_order,
            position.maximum_winners,
            position.status,
            count_candidates(position.id),
            count_votes(position.id),
            position.created_at.strftime("%Y-%m-%d %H:%M") if position.created_at else ""
        ])

    log_audit(
        session.get("admin_id"),
        "Export Positions",
        "Position list exported to CSV"
    )

    response = Response(
        output.getvalue(),
        mimetype="text/csv"
    )
    response.headers["Content-Disposition"] = "attachment; filename=positions_export.csv"

    return response