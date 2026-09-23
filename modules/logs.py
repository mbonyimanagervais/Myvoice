from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    Response,
    flash,
    session,
    abort
)

from modules.database import (
    db,
    AuditLog
)

from modules.auth import admin_required
from modules.security import current_organization_id

import csv
import io
import uuid
from datetime import datetime, timedelta


logs = Blueprint(
    "logs",
    __name__
)


def _get_client_metadata():
    return {
        "ip_address": request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown",
        "browser": request.user_agent.browser or "Unknown",
        "operating_system": request.user_agent.platform or "Unknown",
        "device_type": "Mobile" if request.user_agent.platform and "iphone" in request.user_agent.platform.lower() else "Desktop",
        "session_id": session.get("session_id") or session.get("admin_id") or session.get("student_id") or "guest",
        "request_url": request.url or request.path,
    }


def add_log(user_id=None, username=None, full_name=None, role="System", action=None, module="System",
            description=None, severity="Info", status="Success", ip_address=None, browser=None,
            operating_system=None, device_type=None, session_id=None, request_url=None):
    log = AuditLog(
        organization_id=session.get("organization_id"),
        event_id=str(uuid.uuid4()),
        user=str(user_id) if user_id is not None else "System",
        user_id=str(user_id) if user_id is not None else None,
        username=username,
        full_name=full_name,
        role=role,
        action=action or "System Activity",
        module=module,
        description=description or action or "System activity recorded.",
        severity=severity,
        status=status,
        ip_address=ip_address,
        browser=browser,
        operating_system=operating_system,
        device_type=device_type,
        session_id=session_id,
        request_url=request_url,
        created_at=datetime.utcnow()
    )
    db.session.add(log)
    db.session.commit()
    return log


def _org_logs_query():
    """Base query restricting audit logs to the administrator's own
    organization. Audit entries are tenant-isolated data."""
    return AuditLog.query.filter_by(
        organization_id=current_organization_id()
    )


def get_all_logs():
    return _org_logs_query().order_by(AuditLog.id.desc()).all()


def get_log(log_id):
    return _org_logs_query().filter_by(id=log_id).first()


def get_logs_by_user(user_id):
    return _org_logs_query().filter(
        AuditLog.user_id == str(user_id)
    ).order_by(AuditLog.id.desc()).all()


def get_logs_by_module(module_name):
    return _org_logs_query().filter(
        AuditLog.module == module_name
    ).order_by(AuditLog.id.desc()).all()


def get_logs_by_severity(severity):
    return _org_logs_query().filter(
        AuditLog.severity == severity
    ).order_by(AuditLog.id.desc()).all()


def get_failed_logs():
    return _org_logs_query().filter(
        AuditLog.status == "Failed"
    ).order_by(AuditLog.id.desc()).all()


def get_security_logs():
    return _org_logs_query().filter(
        AuditLog.severity.in_(["Warning", "Critical"])
    ).order_by(AuditLog.id.desc()).all()


def get_recent_logs(limit=20):
    return _org_logs_query().order_by(AuditLog.id.desc()).limit(limit).all()


def generate_statistics():
    base = _org_logs_query()
    total = base.count()
    successful = base.filter(AuditLog.status == "Success").count()
    failed = base.filter(AuditLog.status == "Failed").count()
    critical = base.filter(AuditLog.severity == "Critical").count()
    admin_logins = base.filter(AuditLog.action == "Admin Login").count()
    student_logins = base.filter(AuditLog.action == "Student Login").count()
    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "critical": critical,
        "admin_logins": admin_logins,
        "student_logins": student_logins,
    }


def detect_suspicious_activity(log):
    if log and log.status == "Failed" and log.action and "login" in log.action.lower():
        return True
    return False


def archive_logs():
    return True


def restore_logs():
    return True


# ======================================
# VIEW ALL AUDIT LOGS
# ======================================

@logs.route(
    "/admin/audit-logs"
)
@admin_required
def audit_logs_page():
    # Organization isolation: administrators audit only their own workspace.
    query = _org_logs_query()

    action = request.args.get("action")
    module = request.args.get("module")
    severity = request.args.get("severity")
    status = request.args.get("status")
    role = request.args.get("role")
    username = request.args.get("username")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if module:
        query = query.filter(AuditLog.module.ilike(f"%{module}%"))
    if severity:
        query = query.filter(AuditLog.severity == severity)
    if status:
        query = query.filter(AuditLog.status == status)
    if role:
        query = query.filter(AuditLog.role.ilike(f"%{role}%"))
    if username:
        query = query.filter(
            (AuditLog.username.ilike(f"%{username}%")) | (AuditLog.full_name.ilike(f"%{username}%"))
        )
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= start_date)
        except ValueError:
            pass
    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at <= end_date)
        except ValueError:
            pass

    all_logs = query.order_by(AuditLog.id.desc()).all()
    stats = generate_statistics()
    recent_logs = get_recent_logs(8)

    return render_template(
        "audit_logs.html",
        logs=all_logs,
        stats=stats,
        recent_logs=recent_logs,
        filters={}
    )


# ======================================
# SEARCH LOGS
# ======================================

@logs.route(
    "/admin/audit-logs/search"
)
@admin_required
def search_logs():
    keyword = request.args.get("q", "")
    results = _org_logs_query().filter(
        (AuditLog.action.ilike(f"%{keyword}%")) |
        (AuditLog.description.ilike(f"%{keyword}%")) |
        (AuditLog.module.ilike(f"%{keyword}%"))
    ).order_by(AuditLog.id.desc()).all()

    return render_template(
        "audit_logs.html",
        logs=results,
        stats=generate_statistics(),
        recent_logs=get_recent_logs(8),
        filters={}
    )


# ======================================
# DELETE SINGLE LOG
# ======================================

@logs.route(
    "/admin/audit-logs/delete/<int:id>"
)
@admin_required
def delete_log(id):
    log = _org_logs_query().filter_by(id=id).first()
    if log is None:
        # Missing, or owned by another organization — never disclose.
        abort(404)
    db.session.delete(log)
    db.session.commit()

    flash("Log deleted", "success")
    return redirect(url_for("logs.audit_logs_page"))


# ======================================
# CLEAR ALL LOGS
# ======================================

@logs.route(
    "/admin/audit-logs/clear"
)
@admin_required
def clear_logs():
    # Danger-zone action: clears ONLY the current organization's audit trail.
    _org_logs_query().delete(synchronize_session=False)
    db.session.commit()

    flash("All logs cleared", "success")
    return redirect(url_for("logs.audit_logs_page"))


# ======================================
# EXPORT LOGS CSV
# ======================================

@logs.route(
    "/admin/audit-logs/export/csv"
)
@admin_required
def export_logs_csv():
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Event ID",
        "User",
        "Username",
        "Full Name",
        "Role",
        "Action",
        "Module",
        "Severity",
        "Status",
        "Description",
        "Date"
    ])

    all_logs = _org_logs_query().order_by(AuditLog.id.desc()).all()
    for log in all_logs:
        writer.writerow([
            log.id,
            log.event_id,
            log.user,
            log.username or "",
            log.full_name or "",
            log.role,
            log.action,
            log.module,
            log.severity,
            log.status,
            log.description or "",
            log.created_at
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=myvoice_audit_logs.csv"
    return response


@logs.route(
    "/admin/audit-logs/export"
)
@admin_required
def export_logs():
    return export_logs_csv()
