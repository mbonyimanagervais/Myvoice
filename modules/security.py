from flask import (
    session,
    request,
    redirect,
    url_for,
    abort
)
from functools import wraps
from datetime import datetime, timedelta
from modules.database import db, AuditLog
import hashlib
import os

try:
    from werkzeug.security import check_password_hash as _werkzeug_check_password_hash
except ImportError:  # pragma: no cover
    _werkzeug_check_password_hash = None


LOGIN_ATTEMPTS_LIMIT = 5
LOGIN_ATTEMPTS_WINDOW = timedelta(minutes=15)


# =====================================
# ORGANIZATION CONTEXT HELPERS
# =====================================

def current_organization_id():
    """The organization id is ALWAYS taken from the authenticated session.
    It is never trusted from the frontend / query string."""
    return session.get("organization_id")


def current_admin():
    from modules.database import Admin
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return Admin.query.get(admin_id)


def current_organization():
    from modules.database import Organization
    org_id = current_organization_id()
    if not org_id:
        return None
    return Organization.query.get(org_id)


def organization_name():
    org = current_organization()
    return org.organization_name if org else "MyVoice"


def org_scoped_get(model, obj_id):
    """Fetch a record ONLY if it belongs to the administrator's organization.
    A cross-organization attempt is blocked, logged and treated as a security
    violation (never leaks whether the record exists)."""
    org_id = current_organization_id()
    obj = model.query.filter_by(id=obj_id).first()

    if obj is None:
        abort(404)

    owner_org = getattr(obj, "organization_id", None)
    if org_id is None or owner_org != org_id:
        log_security_event(
            action="CROSS_ORGANIZATION_ACCESS_BLOCKED",
            description=(
                "Blocked cross-organization access attempt to %s #%s by admin %s"
                % (model.__tablename__, obj_id, session.get("admin_id"))
            ),
        )
        abort(404)

    return obj


def log_security_event(action, description, severity="Warning", status="Blocked"):
    """Record a security-relevant event in the audit log with org context."""
    try:
        import uuid as _uuid
        log = AuditLog(
            event_id=_uuid.uuid4().hex,
            organization_id=session.get("organization_id"),
            user=str(session.get("admin_id")) if session.get("admin_id") else "System",
            username=session.get("admin_name") or "System",
            full_name=session.get("admin_name"),
            role="Administrator" if session.get("admin_id") else "System",
            action=action,
            module="Security",
            description=description,
            severity=severity,
            status=status,
            ip_address=request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown",
            request_url=request.url or request.path,
            created_at=datetime.utcnow(),
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


# =====================================
# DECORATORS
# =====================================

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("auth.admin_login"))
        if not session.get("organization_id"):
            session.clear()
            return redirect(url_for("auth.admin_login"))
        return f(*args, **kwargs)
    return decorated


def is_admin():
    return "admin_id" in session and bool(session.get("organization_id"))


def voter_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "voter_id" not in session:
            return redirect(url_for("auth.voter_login"))
        return f(*args, **kwargs)
    return decorated


def log_audit(user_id, action, details=None):
    """Lightweight audit helper used across modules. Includes org context."""
    log = AuditLog(
        organization_id=session.get("organization_id"),
        user=str(user_id),
        action="%s: %s" % (action, details) if details else action,
        ip_address=request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown",
    )
    db.session.add(log)
    db.session.commit()


def generate_password_hash(password):
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100000
    )
    return salt.hex() + ":" + key.hex()


def verify_password(password, stored_hash):
    try:
        salt_hex, key_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            100000
        )
        return new_key == key
    except (ValueError, AttributeError):
        return False


def verify_student_password(password, stored_hash):
    """Verify a student/voter password against either hash format.

    Tries Werkzeug's check_password_hash first (the current standard),
    then falls back to the legacy custom format (salt_hex:key_hex).
    This ensures students created by older code paths can still log in.
    """
    if not stored_hash:
        return False
    if _werkzeug_check_password_hash is not None:
        try:
            if _werkzeug_check_password_hash(stored_hash, password):
                return True
        except Exception:
            pass
    try:
        if verify_password(password, stored_hash):
            return True
    except Exception:
        pass
    return False


def check_login_lockout(ip_address):
    recent_attempts = AuditLog.query.filter(
        AuditLog.action.contains("Failed login"),
        AuditLog.created_at >= datetime.utcnow() - LOGIN_ATTEMPTS_WINDOW
    ).count()
    return recent_attempts >= LOGIN_ATTEMPTS_LIMIT


def validate_position_name(name):
    if not name or not name.strip():
        return "Position name cannot be empty"
    if len(name.strip()) > 100:
        return "Position name must be 100 characters or less"
    return None


def validate_display_order(order):
    try:
        val = int(order)
        if val < 0:
            return "Display order must be a non-negative integer"
        return None
    except (ValueError, TypeError):
        return "Display order must be a valid number"


def validate_max_winners(winners):
    try:
        val = int(winners)
        if val < 1:
            return "Maximum winners must be at least 1"
        return None
    except (ValueError, TypeError):
        return "Maximum winners must be a valid number"


def validate_position_code(code):
    if code and len(code.strip()) > 50:
        return "Position code must be 50 characters or less"
    return None