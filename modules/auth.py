"""
MYVOICE — AUTHENTICATION BLUEPRINT (MULTI-ORGANIZATION)
=======================================================

Responsibility
--------------
- Organization + Administrator registration ("Create Organization Account").
- Administrator login with Email + Password (legacy full-name login kept as a
  backward-compatible fallback so existing accounts keep working).
- Email-based, single-use, expiring password reset tokens (admin + voter).
  Passwords are never revealed or emailed.
- Voter login that resolves the voter inside their own organization.
- Controlled, audited developer support requests (no hidden master password).
"""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    make_response
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from modules.security import verify_password as _verify_recovery_credential

from modules.database import (
    db,
    Admin,
    Student,
    AuditLog,
    SystemSetting,
    Organization,
    PasswordResetToken,
    RecoveryRequest
)
from sqlalchemy import inspect
import re
import secrets
import hashlib
import os
from datetime import datetime, timedelta
from modules.security import (
    admin_required,
    current_organization_id,
    log_security_event,
    verify_student_password,
)
from modules.emailer import (
    send_security_email,
    send_password_reset_email,
    is_smtp_configured
)


# =====================================
# CONFIGURATION
# =====================================
RESET_TOKEN_LIFETIME_MINUTES = 30
RECOVERY_REQUEST_LIFETIME_MINUTES = 30
RATE_LIMIT_WINDOW_MINUTES = 15
RATE_LIMIT_MAX_REQUESTS = 5
RECOVERY_ALLOWED_ATTEMPTS = 5
RECOVERY_LOCKOUT_MINUTES = 15

ORG_TYPES = [
    "School",
    "University",
    "Company",
    "Church",
    "NGO",
    "Government Institution",
    "Community Organization",
    "Other",
]


def ensure_db_ready():
    inspector = inspect(db.engine)
    required_tables = ["admin", "student", "audit_log", "organization"]
    missing_tables = [
        t for t in required_tables if not inspector.has_table(t)
    ]
    if missing_tables:
        db.create_all()
        inspector = inspect(db.engine)
        missing_tables = [
            t for t in required_tables if not inspector.has_table(t)
        ]
        if missing_tables:
            raise RuntimeError(
                "Database initialization failed. Missing tables: %s"
                % ", ".join(missing_tables)
            )


def create_default_admin():
    """Create the initial administrator when explicitly provisioned.

    Existing administrator accounts are preserved exactly as they are. A new
    default administrator is created only when
    MYVOICE_INITIAL_ADMIN_PASSWORD is configured in the environment.
    """
    ensure_db_ready()

    default_admin = Admin.query.filter_by(
        email="admin@myvoice.local",
        full_name="Super Admin",
    ).first()
    if default_admin is not None:
        return

    initial_password = os.environ.get("MYVOICE_INITIAL_ADMIN_PASSWORD", "").strip()
    if not initial_password:
        return

    from modules.migrate import run_migrations
    legacy_org_id = run_migrations()

    from modules.database import Organization
    org = Organization.query.get(legacy_org_id)
    new_admin = Admin(
        organization_id=legacy_org_id,
        full_name="Super Admin",
        email="admin@myvoice.local",
        password=generate_password_hash(initial_password, method="pbkdf2:sha256"),
        role="owner",
        is_owner=True,
        status="Active",
        email_verified=True,
        created_at=datetime.utcnow(),
    )
    db.session.add(new_admin)
    if org is not None:
        _ensure_org_settings(org)
    db.session.commit()


def validate_password_strength(password):
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain at least one special character")
    weak_passwords = [
        "password", "Password1!", "admin", "Admin123!", "12345678", "qwerty123!@#"
    ]
    if password in weak_passwords:
        errors.append("Password is too common. Please choose a stronger password")
    return errors


def _client_metadata():
    """Capture IP / device / browser details for audit trails (never credentials)."""
    platform = (request.user_agent.platform or "").lower()
    return {
        "ip_address": (
            request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"
        ),
        "browser": request.user_agent.browser or "Unknown",
        "operating_system": request.user_agent.platform or "Unknown",
        "device_type": "Mobile" if "iphone" in platform else "Desktop",
    }


def _ensure_org_settings(org):
    """Return (creating if needed) the settings row for an organization."""
    settings = SystemSetting.query.filter_by(organization_id=org.id).first()
    if settings is not None:
        return settings
    settings = SystemSetting(
        organization_id=org.id,
        system_name="MyVoice",
        school_name=org.organization_name,
        updated_at=datetime.utcnow(),
    )
    db.session.add(settings)
    db.session.commit()
    return settings


def _ensure_settings():
    """Settings row for the CURRENT organization context (fallback: legacy row)."""
    org_id = current_organization_id()
    if org_id:
        settings = SystemSetting.query.filter_by(organization_id=org_id).first()
        if settings is not None:
            return settings
    settings = SystemSetting.query.first()
    if settings is None:
        settings = SystemSetting()
        db.session.add(settings)
        db.session.commit()
    return settings


def _rate_limited(action, ip_address, limit=RATE_LIMIT_MAX_REQUESTS):
    """True when the caller has exceeded the rate limit for an action from an IP."""
    since = datetime.utcnow() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    count = AuditLog.query.filter(
        AuditLog.action == action,
        AuditLog.ip_address == ip_address,
        AuditLog.created_at >= since,
    ).count()
    return count >= limit


def _issue_reset_token(account_type, account_id, org_id):
    """Create a single-use reset token and return the PLAINTEXT token.

    Only the SHA-256 hash is stored. The plaintext is sent to the account
    holder's email and is never persisted."""
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record = PasswordResetToken(
        organization_id=org_id,
        token_hash=token_hash,
        account_type=account_type,
        account_id=account_id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow()
        + timedelta(minutes=RESET_TOKEN_LIFETIME_MINUTES),
        consumed=False,
    )
    db.session.add(record)
    db.session.commit()
    return token


def _validate_reset_token(token, account_type):
    """Validate a reset token. Returns (record, error_key) where error_key is
    None on success or one of invalid | used | expired."""
    if not token:
        return None, "invalid"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record = PasswordResetToken.query.filter_by(
        token_hash=token_hash,
        account_type=account_type,
    ).first()
    if record is None:
        return None, "invalid"
    if record.consumed:
        return None, "used"
    if datetime.utcnow() > record.expires_at:
        return None, "expired"
    return record, None


def _log_audit_entry(meta=None, **fields):
    meta = meta or _client_metadata()
    base = {
        "organization_id": current_organization_id(),
        "ip_address": meta.get("ip_address"),
        "browser": meta.get("browser"),
        "operating_system": meta.get("operating_system"),
        "device_type": meta.get("device_type"),
        "request_url": request.url or request.path,
        "created_at": datetime.utcnow(),
    }
    base.update(fields)
    db.session.add(AuditLog(**base))
    db.session.commit()


def send_developer_recovery_notification(recovery_request, admin, meta=None):
    """Notify the authorized developer of a support request.

    Notification ONLY — never authorizes recovery and never includes the
    administrator's password or any token. Returns True if emailed/logged."""
    meta = meta or _client_metadata()
    subject = "MYVOICE SECURITY ALERT — Administrator Support Request"
    body = (
        "MYVOICE SECURITY ALERT\n\n"
        "An administrator has requested developer support for account recovery.\n\n"
        "Support Request ID:\n{0}\n\n"
        "Administrator:\n{1}\n\n"
        "Organization:\n{2}\n\n"
        "Date:\n{3}\n\n"
        "Time:\n{4} UTC\n\n"
        "IP Address:\n{5}\n\n"
        "Status:\nPENDING DEVELOPER REVIEW\n\n"
        "IMPORTANT:\nThis notification does NOT contain the administrator's "
        "password or any reset token."
    ).format(
        recovery_request.request_id,
        admin.full_name if admin else "Unknown",
        (
            admin.organization.organization_name
            if admin and admin.organization else "Unknown"
        ),
        datetime.utcnow().strftime("%d %b %Y"),
        datetime.utcnow().strftime("%H:%M:%S"),
        meta.get("ip_address", "Unknown"),
    )
    return send_security_email(subject, body)


auth = Blueprint(
    "auth",
    __name__
)


# =====================================
# CREATE ORGANIZATION ACCOUNT
# =====================================

@auth.route(
    "/admin/register",
    methods=["GET", "POST"]
)
def admin_register():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (
            request.form.get("register_email")
            or request.form.get("email")
            or ""
        ).strip().lower()
        password = (
            request.form.get("register_password")
            or request.form.get("password")
            or ""
        )
        confirm_password = (
            request.form.get("register_confirm")
            or request.form.get("confirm_password")
            or ""
        )
        organization_name = (request.form.get("organization_name") or "").strip()
        organization_type = (request.form.get("organization_type") or "Other").strip()

        errors = []
        if not full_name or len(full_name) < 2:
            errors.append("Full name is required.")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("A valid email address is required.")
        if not organization_name or len(organization_name) < 2:
            errors.append("Organization name is required.")
        if organization_type not in ORG_TYPES:
            errors.append("Please select a valid organization type.")
        password_errors = validate_password_strength(password)
        if password_errors:
            errors.extend(password_errors)
        if password != confirm_password:
            errors.append("Passwords do not match.")

        if not errors:
            existing = Admin.query.filter_by(email=email).first()
            if existing is not None:
                errors.append(
                    "An account with this email address already exists."
                )

            duplicate_org = Organization.query.filter(
                db.func.lower(Organization.organization_name)
                == organization_name.lower()
            ).first()
            if duplicate_org is not None:
                errors.append(
                    "An organization with this name already exists. Please "
                    "contact the platform for assistance."
                )

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "admin_register.html",
                org_types=ORG_TYPES,
                form=request.form,
            )

        # ---- create organization ----
        organization = Organization(
            organization_uuid=secrets.token_urlsafe(24),
            organization_name=organization_name,
            organization_type=organization_type,
            status="Active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(organization)
        db.session.flush()  # obtain organization.id

        # ---- organization workspace (settings row) ----
        _ensure_org_settings(organization)

        # ---- owner / primary administrator ----
        admin = Admin(
            organization_id=organization.id,
            full_name=full_name,
            email=email,
            password=generate_password_hash(password, method="pbkdf2:sha256"),
            role="owner",
            is_owner=True,
            status="Active",
            email_verified=False,
            created_at=datetime.utcnow(),
        )
        db.session.add(admin)
        db.session.flush()

        db.session.add(AuditLog(
            organization_id=organization.id,
            user=str(admin.id),
            user_id=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Owner",
            action="ORGANIZATION_CREATED",
            module="Auth",
            description="Organization workspace created during account registration.",
            severity="Info",
            status="Success",
            ip_address=request.headers.get("X-Forwarded-For") or request.remote_addr,
        ))
        db.session.add(AuditLog(
            organization_id=organization.id,
            user=str(admin.id),
            user_id=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Owner",
            action="ADMIN_REGISTERED",
            module="Auth",
            description="Administrator account created as organization owner.",
            severity="Info",
            status="Success",
            ip_address=request.headers.get("X-Forwarded-For") or request.remote_addr,
        ))
        db.session.commit()

        if email:
            sent = send_security_email(
                "MYVOICE — Organization Account Created",
                (
                    "Welcome to MyVoice!\n\n"
                    "Your organization workspace has been created.\n\n"
                    "Organization: {0}\n"
                    "Account Email: {1}\n\n"
                    "You can now sign in with your email address and password."
                ).format(organization_name, email),
                to_email=email,
            )
            if not sent and not is_smtp_configured():
                flash(
                    "Your account is ready. NOTE: Email is not configured on "
                    "this server yet, so no welcome email was delivered.",
                    "info",
                )

        session.clear()
        flash(
            "Your organization account was created successfully. You can now "
            "sign in with your email address.",
            "success",
        )
        return redirect(url_for("auth.admin_login"))

    return render_template(
        "admin_register.html",
        org_types=ORG_TYPES,
        form=request.form if request.method == "POST" else {},
    )


def _render_admin_login():
    """Render admin_login with a fresh per-request nonce used to
    generate unique field names. This is the most reliable defense
    against browser password manager autofill: the browser keys
    saved credentials to the form's `name`/`id`, and those values
    change on every page load, so no saved credential can be
    automatically injected.

    The response is additionally marked uncacheable so that the
    back/forward cache and browser caches can never resurrect a
    previously rendered login page (or anything typed into it).
    Every call site returns this response directly, so every render
    path — GET, failed POST, DB-init failure, rate-limited — is
    covered."""
    import secrets as _secrets
    nonce = _secrets.token_urlsafe(16)
    response = make_response(render_template("admin_login.html", nonce=nonce))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# =====================================
# ADMIN LOGIN (EMAIL + PASSWORD)
# =====================================

@auth.route(
    "/admin/login",
    methods=["GET", "POST"]
)
def admin_login():
    try:
        ensure_db_ready()
        create_default_admin()
    except Exception as exc:
        flash("Database initialization failed: %s" % exc, "danger")
        return _render_admin_login()

    if request.method == "POST":
        # Find the dynamically-named email and password fields.
        # The form uses a per-request nonce to prevent browser
        # password manager autofill, so the field names are
        # `f1_<nonce>` and `f2_<nonce>`.
        identifier = ""
        password = ""
        for k in request.form.keys():
            if k.startswith("f1_"):
                identifier = (request.form.get(k) or "").strip()
            elif k.startswith("f2_"):
                password = request.form.get(k) or ""
        # Legacy fallback (older forms or simpler tests)
        if not identifier:
            identifier = (
                request.form.get("admin_email")
                or request.form.get("email")
                or request.form.get("username")
                or ""
            ).strip()
        if not password:
            password = (
                request.form.get("admin_password")
                or request.form.get("password")
                or ""
            )
        ip_address = request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"

        if not identifier or not password:
            flash("Email and password are required.", "warning")
            return _render_admin_login()

        if _rate_limited("ADMIN_LOGIN_FAILED", ip_address):
            log_security_event(
                "LOGIN_BRUTE_FORCE_BLOCKED",
                "Repeated failed administrator login attempts from %s" % ip_address,
            )
            flash(
                "Too many failed attempts. Please wait 15 minutes and try again.",
                "danger",
            )
            return _render_admin_login()

        # Find account by email OR legacy full-name login (backward compatible).
        admin = Admin.query.filter_by(email=identifier.lower()).first()
        if admin is None:
            admin = Admin.query.filter_by(full_name=identifier).first()

        if admin is not None and check_password_hash(admin.password, password):
            if (admin.status or "Active").strip().lower() != "active":
                db.session.add(AuditLog(
                    organization_id=admin.organization_id,
                    user=str(admin.id),
                    username=admin.full_name,
                    full_name=admin.full_name,
                    role="Administrator",
                    action="ADMIN_LOGIN_BLOCKED",
                    module="Auth",
                    description="Login blocked - administrator account is not active.",
                    severity="Warning",
                    status="Blocked",
                    ip_address=ip_address,
                ))
                db.session.commit()
                flash(
                    "This account has been disabled. Contact your organization "
                    "administrator for assistance.",
                    "danger",
                )
                return _render_admin_login()

            session.clear()
            session["admin_id"] = admin.id
            session["organization_id"] = admin.organization_id
            session["admin_name"] = admin.full_name
            session["admin_role"] = admin.role or "owner"
            session["is_owner"] = bool(admin.is_owner)

            admin.last_login = datetime.utcnow()
            db.session.add(AuditLog(
                organization_id=admin.organization_id,
                user=str(admin.id),
                user_id=str(admin.id),
                username=admin.full_name,
                full_name=admin.full_name,
                role="Administrator",
                action="Admin Login",
                module="Auth",
                description="Administrator signed in successfully.",
                severity="Info",
                status="Success",
                ip_address=ip_address,
            ))
            db.session.commit()
            return redirect(url_for("admin_home"))

        db.session.add(AuditLog(
            organization_id=admin.organization_id if admin else None,
            user=str(admin.id) if admin else "System",
            username=(admin.full_name if admin else identifier),
            full_name=(admin.full_name if admin else identifier),
            role="Administrator",
            action="ADMIN_LOGIN_FAILED",
            module="Auth",
            description="Failed administrator login attempt.",
            severity="Warning",
            status="Failed",
            ip_address=ip_address,
        ))
        db.session.commit()
        flash("Invalid email or password.", "danger")

    # _render_admin_login() already sends no-store cache headers, so the
    # login page can never be restored from cache with old field values.
    return _render_admin_login()


def _render_voter_login():
    """Render a fresh, uncacheable voter login page."""
    response = make_response(render_template("voter_login.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# =====================================
# ADMIN LOGOUT
# =====================================

@auth.route("/admin/logout")
def admin_logout():
    if session.get("admin_id"):
        _log_audit_entry(
            user=str(session.get("admin_id")),
            username=session.get("admin_name"),
            full_name=session.get("admin_name"),
            role="Administrator",
            action="Admin Logout",
            module="Auth",
            description="Administrator signed out.",
            severity="Info",
            status="Success",
        )
    # Completely destroy the session — both clear contents and
    # invalidate the session cookie itself to prevent any reuse.
    session.clear()
    response = redirect(url_for("auth.admin_login"))
    # Set explicit cache-control to prevent back-button showing protected data
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    flash("You have been signed out.", "info")
    return response


# =====================================
# ADMIN CHANGE PASSWORD (logged in)
# =====================================

@auth.route(
    "/admin/change-password",
    methods=["GET", "POST"]
)
@admin_required
def admin_change_password():
    admin = Admin.query.get(session.get("admin_id"))
    if admin is None:
        session.clear()
        return redirect(url_for("auth.admin_login"))

    if request.method == "POST":
        current_password = (
            request.form.get("admin_change_current")
            or request.form.get("current_password")
            or ""
        )
        new_password = (
            request.form.get("admin_change_new")
            or request.form.get("new_password")
            or request.form.get("password")
            or ""
        )
        confirm_password = (
            request.form.get("admin_change_confirm")
            or request.form.get("confirm_password")
            or ""
        )

        if not check_password_hash(admin.password, current_password):
            flash("Current password is incorrect.", "danger")
            return render_template("admin_change_password.html")

        password_errors = validate_password_strength(new_password)
        if password_errors:
            for error in password_errors:
                flash(error, "warning")
            return render_template("admin_change_password.html")

        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return render_template("admin_change_password.html")

        admin.password = generate_password_hash(new_password, method="pbkdf2:sha256")
        admin.updated_at = datetime.utcnow()
        db.session.add(AuditLog(
            organization_id=admin.organization_id,
            user=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Administrator",
            action="ADMIN_PASSWORD_CHANGED",
            module="Auth",
            description="Administrator changed own password.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        db.session.commit()
        session.clear()
        flash("Password changed successfully. Please sign in again.", "success")
        return redirect(url_for("auth.admin_login"))

    return render_template("admin_change_password.html")


# =====================================
# ADMIN FORGOT PASSWORD (RECOVERY REQUEST)
# =====================================

def _send_recovery_request_notification(recovery_request, admin, meta=None):
    """Notify the authorized developer that an administrator has requested
    emergency account recovery.

    The notification contains ONLY the request id and administrator identity.
    It never contains passwords, tokens, or the recovery credential."""
    meta = meta or _client_metadata()
    body = (
        "MYVOICE SECURITY SYSTEM\n\n"
        "An administrator emergency recovery request has been submitted.\n\n"
        "Recovery Request ID:\n{0}\n\n"
        "Administrator:\n{1}\n\n"
        "Date:\n{2} UTC\n\n"
        "IP Address:\n{3}\n\n"
        "Status:\nPENDING DEVELOPER REVIEW\n\n"
        "IMPORTANT:\nThis notification does NOT contain the administrator's "
        "password or any recovery credential. Verify the requester through an "
        "out-of-band channel before providing the Developer Recovery Credential."
    ).format(
        recovery_request.request_id,
        admin.full_name if admin else "Unknown",
        datetime.utcnow().strftime("%d %b %Y %H:%M:%S"),
        meta.get("ip_address", "Unknown"),
    )
    subject = "MYVOICE — Recovery Request"
    try:
        from modules.emailer import developer_security_email
        return send_security_email(
            subject, body, to_email=developer_security_email()
        )
    except Exception:
        return send_security_email(subject, body)


@auth.route(
    "/admin/forgot-password",
    methods=["GET", "POST"]
)
def admin_forgot_password():
    if request.method == "POST":
        username = (
            (request.form.get("username") or "").strip()
            or (request.form.get("email") or "").strip()
        )
        ip_address = (
            request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"
        )

        if _rate_limited("DEVELOPER_SUPPORT_REQUESTED", ip_address):
            flash(
                "Too many recovery requests. Please wait 15 minutes and try again.",
                "danger",
            )
            return render_template("admin_forgot_password.html")

        admin = None
        if username:
            admin = Admin.query.filter_by(full_name=username).first()
            if admin is None and "@" in username:
                admin = Admin.query.filter_by(email=username.lower()).first()

        # Anti-enumeration: identical response whether or not the account exists.
        if admin is not None:
            # Do not create a duplicate pending request for the same admin.
            existing_pending = RecoveryRequest.query.filter_by(
                admin_id=admin.id,
                status="PENDING",
            ).order_by(RecoveryRequest.id.desc()).first()

            if existing_pending is None:
                meta = _client_metadata()
                request_id = secrets.token_urlsafe(16)
                support_request = RecoveryRequest(
                    organization_id=admin.organization_id,
                    request_id=request_id,
                    admin_id=admin.id,
                    key_hash=None,
                    created_at=datetime.utcnow(),
                    expires_at=datetime.utcnow()
                    + timedelta(minutes=RECOVERY_REQUEST_LIFETIME_MINUTES),
                    status="PENDING",
                    ip_address=meta["ip_address"],
                    user_agent=(request.user_agent.string or "")[:255],
                )
                db.session.add(support_request)
                db.session.add(AuditLog(
                    organization_id=admin.organization_id,
                    user=str(admin.id),
                    username=admin.full_name,
                    full_name=admin.full_name,
                    role="Administrator",
                    action="ADMIN_RECOVERY_REQUEST_CREATED",
                    module="Auth",
                    description="Administrator recovery request created.",
                    severity="Info",
                    status="Pending",
                    ip_address=meta["ip_address"],
                ))
                db.session.commit()

                notified = _send_recovery_request_notification(
                    support_request, admin, meta
                )
                db.session.add(AuditLog(
                    organization_id=admin.organization_id,
                    user=str(admin.id),
                    username=admin.full_name,
                    full_name=admin.full_name,
                    role="Administrator",
                    action=(
                        "DEVELOPER_RECOVERY_NOTIFICATION_SENT"
                        if notified
                        else "DEVELOPER_RECOVERY_NOTIFICATION_FAILED"
                    ),
                    module="Auth",
                    description=(
                        "Developer notified of recovery request."
                        if notified
                        else "Developer notification could not be delivered."
                    ),
                    severity="Info",
                    status="Success" if notified else "Failed",
                    ip_address=meta["ip_address"],
                ))
                db.session.commit()

        flash(
            "If an account matches the information provided, a recovery "
            "request has been sent to the authorized developer for review.",
            "success",
        )
        return redirect(url_for("auth.admin_recovery"))

    return render_template("admin_forgot_password.html")


# =====================================
# ADMIN RESET PASSWORD (RECOVERY SESSION)
# =====================================

@auth.route(
    "/admin/reset-password",
    methods=["GET", "POST"]
)
def admin_reset_password_recovery():
    """Session-based reset endpoint reached after the developer recovery
    credential has been verified at /admin/recovery."""

    if not session.get("recovery_authorized") or not session.get(
        "recovery_admin_id"
    ):
        return redirect(url_for("auth.admin_forgot_password"))

    admin = Admin.query.get(session.get("recovery_admin_id"))
    if admin is None:
        session.pop("recovery_authorized", None)
        session.pop("recovery_admin_id", None)
        return redirect(url_for("auth.admin_forgot_password"))

    if request.method == "POST":
        new_password = (
            request.form.get("admin_reset_pwd")
            or request.form.get("new_password")
            or request.form.get("password")
            or ""
        )
        confirm_password = (
            request.form.get("admin_reset_confirm")
            or request.form.get("confirm_password")
            or ""
        )

        password_errors = validate_password_strength(new_password)
        if password_errors:
            for error in password_errors:
                flash(error, "warning")
            return render_template(
                "admin_reset_password.html",
                account_name=admin.full_name,
                recovery_authorized=True,
            )

        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return render_template(
                "admin_reset_password.html",
                account_name=admin.full_name,
                recovery_authorized=True,
            )

        admin.password = generate_password_hash(
            new_password, method="pbkdf2:sha256"
        )
        admin.updated_at = datetime.utcnow()

        # Mark the originating recovery request as COMPLETED.
        req_id = session.get("recovery_request_id")
        recovery_req = None
        if req_id:
            recovery_req = RecoveryRequest.query.filter_by(
                request_id=req_id
            ).first()
        if recovery_req is None:
            recovery_req = RecoveryRequest.query.filter_by(
                admin_id=admin.id,
                status="APPROVED",
            ).order_by(RecoveryRequest.id.desc()).first()
        if recovery_req is None:
            recovery_req = RecoveryRequest.query.filter_by(
                admin_id=admin.id,
            ).order_by(RecoveryRequest.id.desc()).first()

        now = datetime.utcnow()
        if recovery_req is not None:
            if recovery_req.status in ("PENDING", "APPROVED"):
                recovery_req.status = "COMPLETED"
            recovery_req.used_at = now
            if recovery_req.approved_at is None:
                recovery_req.approved_at = now
            db.session.add(recovery_req)

        db.session.add(AuditLog(
            organization_id=admin.organization_id,
            user=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Administrator",
            action="ADMIN_PASSWORD_RESET",
            module="Auth",
            description="Administrator password reset via developer-assisted recovery.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        db.session.add(AuditLog(
            organization_id=admin.organization_id,
            user=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Administrator",
            action="ADMIN_SESSIONS_REVOKED",
            module="Auth",
            description="All administrator sessions invalidated after password reset.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        if recovery_req is not None:
            db.session.add(AuditLog(
                organization_id=admin.organization_id,
                user=str(admin.id),
                username=admin.full_name,
                full_name=admin.full_name,
                role="Administrator",
                action="ADMIN_RECOVERY_COMPLETED",
                module="Auth",
                description=(
                    "Recovery request %s completed." % recovery_req.request_id
                ),
                severity="Info",
                status="Success",
                **_client_metadata(),
            ))
        db.session.commit()

        session.clear()
        flash(
            "Your password has been reset successfully. You can now sign in.",
            "success",
        )
        return redirect(url_for("auth.admin_login"))

    return render_template(
        "admin_reset_password.html",
        account_name=admin.full_name,
        recovery_authorized=True,
    )


# =====================================
# ADMIN RESET PASSWORD (TOKEN)
# =====================================

@auth.route(
    "/admin/reset-password/<token>",
    methods=["GET", "POST"]
)
def admin_reset_password(token):
    record, error_key = _validate_reset_token(token, "admin")
    if error_key is not None:
        db.session.add(AuditLog(
            action="PASSWORD_RESET_TOKEN_REJECTED",
            module="Auth",
            description="Reset token rejected: %s." % error_key,
            severity="Warning",
            status="Failed",
            **_client_metadata(),
        ))
        db.session.commit()
        flash(
            "This password reset link is invalid, has already been used, or has "
            "expired. Please request a new one.",
            "danger",
        )
        return redirect(url_for("auth.admin_forgot_password"))

    admin = Admin.query.get(record.account_id)
    if admin is None:
        flash("The account for this reset link no longer exists.", "danger")
        return redirect(url_for("auth.admin_forgot_password"))

    if request.method == "POST":
        new_password = (
            request.form.get("admin_reset_pwd")
            or request.form.get("new_password")
            or request.form.get("password")
            or ""
        )
        confirm_password = (
            request.form.get("admin_reset_confirm")
            or request.form.get("confirm_password")
            or ""
        )

        password_errors = validate_password_strength(new_password)
        if password_errors:
            for error in password_errors:
                flash(error, "warning")
            return render_template(
                "admin_reset_password.html",
                token=token,
                account_name=admin.full_name,
            )

        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return render_template(
                "admin_reset_password.html",
                token=token,
                account_name=admin.full_name,
            )

        admin.password = generate_password_hash(new_password, method="pbkdf2:sha256")
        admin.updated_at = datetime.utcnow()
        record.consumed = True
        record.used_at = datetime.utcnow()

        db.session.add(AuditLog(
            organization_id=admin.organization_id,
            user=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Administrator",
            action="PASSWORD_RESET_COMPLETED",
            module="Auth",
            description="Administrator password reset completed via secure link.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        db.session.add(AuditLog(
            organization_id=admin.organization_id,
            user=str(admin.id),
            username=admin.full_name,
            full_name=admin.full_name,
            role="Administrator",
            action="ADMIN_SESSIONS_REVOKED",
            module="Auth",
            description="All administrator sessions invalidated after password reset.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        db.session.commit()

        session.clear()
        flash(
            "Your password has been reset successfully. You can now sign in.",
            "success",
        )
        return redirect(url_for("auth.admin_login"))

    return render_template(
        "admin_reset_password.html",
        token=token,
        account_name=admin.full_name,
    )


# =====================================
# VERIFY DEVELOPER RECOVERY CREDENTIAL
# =====================================

def _recovery_lock_active(settings):
    if not settings or not settings.recovery_locked_until:
        return False
    return datetime.utcnow() < settings.recovery_locked_until


def _resolve_recovery_settings():
    """Return the SystemSetting row that owns the developer recovery
    credential. Falls back to the first row when no org context is set."""
    org_id = current_organization_id()
    if org_id:
        row = SystemSetting.query.filter_by(organization_id=org_id).first()
        if row is not None:
            return row
    return SystemSetting.query.first()


@auth.route(
    "/admin/recovery",
    methods=["GET", "POST"]
)
def admin_recovery():
    settings = _resolve_recovery_settings()

    if request.method == "GET":
        if settings is not None:
            settings.recovery_locked_until  # touch to keep linter quiet
        return render_template(
            "admin_recovery.html",
            locked=_recovery_lock_active(settings),
            request_status=None,
            username="",
        )

    username = (request.form.get("username") or "").strip()
    credential = (request.form.get("recovery_credential") or "").strip()
    ip_address = (
        request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"
    )

    if _recovery_lock_active(settings):
        flash(
            "Recovery is temporarily locked due to repeated failed attempts. "
            "Please wait before trying again.",
            "danger",
        )
        return render_template(
            "admin_recovery.html",
            locked=True,
            request_status=None,
            username=username,
        )

    if not settings or not settings.developer_recovery_hash:
        flash("Recovery could not be verified.", "danger")
        return render_template(
            "admin_recovery.html",
            locked=False,
            request_status=None,
            username=username,
        )

    # Resolve the admin this attempt belongs to.
    admin = None
    if username:
        admin = Admin.query.filter_by(full_name=username).first()
        if admin is None and "@" in username:
            admin = Admin.query.filter_by(email=username.lower()).first()

    credential_valid = False
    try:
        credential_valid = _verify_recovery_credential(
            credential, settings.developer_recovery_hash
        )
    except Exception:
        credential_valid = False

    if not credential_valid:
        settings.recovery_failed_attempts = (
            (settings.recovery_failed_attempts or 0) + 1
        )
        if settings.recovery_failed_attempts >= RECOVERY_ALLOWED_ATTEMPTS:
            settings.recovery_locked_until = (
                datetime.utcnow() + timedelta(minutes=RECOVERY_LOCKOUT_MINUTES)
            )
            settings.recovery_lockout_count = (
                (settings.recovery_lockout_count or 0) + 1
            )
            settings.recovery_failed_attempts = 0
        db.session.add(AuditLog(
            organization_id=(
                admin.organization_id if admin else settings.organization_id
            ),
            user=str(admin.id) if admin else "System",
            username=(admin.full_name if admin else username or "Unknown"),
            full_name=(admin.full_name if admin else username or "Unknown"),
            role="Administrator",
            action="ADMIN_RECOVERY_FAILED",
            module="Auth",
            description="Failed developer recovery credential attempt.",
            severity="Warning",
            status="Failed",
            ip_address=ip_address,
        ))
        db.session.commit()

        if _recovery_lock_active(settings):
            flash(
                "Recovery is temporarily locked due to repeated failed attempts. "
                "Please wait before trying again.",
                "danger",
            )
            return render_template(
                "admin_recovery.html",
                locked=True,
                request_status=None,
                username=username,
            )

        flash("Recovery could not be verified.", "danger")
        return render_template(
            "admin_recovery.html",
            locked=False,
            request_status=None,
            username=username,
        )

    # Credential valid — authorize the recovery.
    settings.recovery_failed_attempts = 0
    settings.recovery_locked_until = None
    settings.recovery_last_at = datetime.utcnow()

    target_admin = admin
    if target_admin is None and session.get("admin_id"):
        target_admin = Admin.query.get(session.get("admin_id"))
    if target_admin is None:
        # Fall back to the most recent pending recovery request.
        pending = RecoveryRequest.query.filter_by(
            status="PENDING"
        ).order_by(RecoveryRequest.id.desc()).first()
        if pending is not None:
            target_admin = Admin.query.get(pending.admin_id)

    if target_admin is None:
        flash("Recovery could not be verified.", "danger")
        return render_template(
            "admin_recovery.html",
            locked=False,
            request_status=None,
            username=username,
        )

    # Mark the originating request as APPROVED.
    recovery_req = None
    if target_admin is not None:
        recovery_req = RecoveryRequest.query.filter_by(
            admin_id=target_admin.id,
            status="PENDING",
        ).order_by(RecoveryRequest.id.desc()).first()
    if recovery_req is not None:
        recovery_req.status = "APPROVED"
        recovery_req.approved_at = datetime.utcnow()
        db.session.add(recovery_req)

    db.session.add(AuditLog(
        organization_id=target_admin.organization_id,
        user=str(target_admin.id),
        username=target_admin.full_name,
        full_name=target_admin.full_name,
        role="Administrator",
        action="ADMIN_RECOVERY_APPROVED",
        module="Auth",
        description="Administrator recovery approved via developer credential.",
        severity="Info",
        status="Success",
        ip_address=ip_address,
    ))
    db.session.commit()

    session["recovery_authorized"] = True
    session["recovery_admin_id"] = target_admin.id
    session["recovery_request_id"] = (
        recovery_req.request_id if recovery_req else None
    )
    return redirect(url_for("auth.admin_reset_password_recovery"))


# =====================================
# RECOVERY / SUPPORT REQUESTS OVERVIEW
# =====================================
# Visible to administrators so every request is auditable. Requests are scoped
# to the administrator's own organization.

@auth.route("/admin/recovery-requests")
@admin_required
def admin_recovery_requests():
    org_id = current_organization_id()
    requests = RecoveryRequest.query.filter_by(organization_id=org_id).order_by(
        RecoveryRequest.created_at.desc()
    ).all()
    return render_template(
        "admin_recovery_requests.html",
        requests=requests,
        now=datetime.utcnow(),
    )


# =====================================
# VOTER LOGIN (ORGANIZATION-AWARE)
# =====================================

@auth.route(
    "/voter/login",
    methods=["GET", "POST"]
)
def voter_login():
    if request.method == "POST":
        student_id = (
            request.form.get("voter_student_id")
            or request.form.get("student_id")
            or request.form.get("username")
            or ""
        ).strip()
        password = (
            request.form.get("voter_password")
            or request.form.get("password")
            or ""
        )
        ip_address = (
            request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"
        )

        if not student_id or not password:
            flash("Student ID and password are required.", "warning")
            return _render_voter_login()

        if _rate_limited("VOTER_LOGIN_FAILED", ip_address):
            flash(
                "Too many failed attempts. Please wait 15 minutes and try again.",
                "danger",
            )
            return _render_voter_login()

        # Student IDs are only unique WITHIN an organization, so multiple rows
        # may share the same student_id. Resolve the correct one via password.
        # Support both Werkzeug-format hashes and legacy custom-format hashes
        # (salt_hex:key_hex) so that students imported by older code paths
        # can still authenticate.
        students = Student.query.filter(
            (Student.student_id == student_id) | (Student.username == student_id)
        ).all()

        matched = None
        for student in students:
            if student.password and verify_student_password(password, student.password):
                matched = student
                break

        if matched is None:
            db.session.add(AuditLog(
                action="VOTER_LOGIN_FAILED",
                module="Auth",
                description="Failed voter login attempt for student ID: %s" % student_id,
                severity="Warning",
                status="Failed",
                ip_address=ip_address,
            ))
            db.session.commit()
            flash("Invalid student ID or password.", "danger")
            return _render_voter_login()

        if (matched.status or "Active").strip().lower() != "active":
            flash(
                "Your account is disabled. Contact your organization administrator.",
                "danger",
            )
            return _render_voter_login()

        session.clear()
        session["voter_id"] = matched.id
        session["student_id"] = matched.id
        session["voter_name"] = matched.full_name
        session["voter_org_id"] = matched.organization_id
        session["voter_student_id"] = matched.student_id

        db.session.add(AuditLog(
            organization_id=matched.organization_id,
            user=str(matched.id),
            user_id=str(matched.id),
            username=matched.username or matched.student_id,
            full_name=matched.full_name,
            role="Student",
            action="Student Login",
            module="Auth",
            description="Student signed in successfully.",
            severity="Info",
            status="Success",
            ip_address=ip_address,
        ))
        db.session.commit()
        return redirect(url_for("voting.voter_dashboard"))

    return _render_voter_login()


# =====================================
# VOTER LOGOUT
# =====================================

@auth.route("/voter/logout")
def voter_logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.voter_login"))


# =====================================
# VOTER FORGOT PASSWORD (STUDENT ID + EMAIL)
# =====================================

@auth.route(
    "/voter/forgot-password",
    methods=["GET", "POST"]
)
def voter_forgot_password():
    if request.method == "POST":
        student_id = (
            request.form.get("voter_forgot_studentid")
            or request.form.get("student_id")
            or ""
        ).strip()
        email = (
            request.form.get("voter_forgot_email")
            or request.form.get("email")
            or ""
        ).strip().lower()
        ip_address = (
            request.headers.get("X-Forwarded-For") or request.remote_addr or "Unknown"
        )

        if _rate_limited("PASSWORD_RESET_REQUESTED", ip_address):
            flash(
                "Too many reset requests. Please wait 15 minutes and try again.",
                "danger",
            )
            return render_template("voter_forgot_password.html")

        student = None
        if student_id:
            student = Student.query.filter_by(student_id=student_id).first()
            if student is None:
                student = Student.query.filter_by(username=student_id).first()

        if (
            student is not None
            and student.email
            and student.email.strip().lower() == email
        ):
            token = _issue_reset_token(
                "voter", student.id, student.organization_id
            )
            reset_url = url_for(
                "auth.voter_reset_password",
                token=token,
                _external=True,
            )
            sent = send_password_reset_email(
                student.email,
                reset_url,
                student.full_name,
                "voter",
            )
            db.session.add(AuditLog(
                organization_id=student.organization_id,
                user=str(student.id),
                username=student.username or student.student_id,
                full_name=student.full_name,
                role="Student",
                action="PASSWORD_RESET_REQUESTED",
                module="Auth",
                description=(
                    "Password reset requested for voter account. "
                    + ("Email sent." if sent else "Email NOT delivered.")
                ),
                severity="Info",
                status="Success" if sent else "Failed",
                ip_address=ip_address,
            ))
            db.session.commit()
        elif student is not None and not student.email:
            flash(
                "Password recovery by email is not available for this account. "
                "Please contact your organization administrator.",
                "info",
            )
            return redirect(url_for("auth.voter_login"))

        # Anti-enumeration for the common path.
        flash(
            "If an account exists for this student ID and email, password reset "
            "instructions have been sent.",
            "success",
        )
        return redirect(url_for("auth.voter_login"))

    return render_template("voter_forgot_password.html")


# =====================================
# VOTER RESET PASSWORD (TOKEN)
# =====================================

@auth.route(
    "/voter/reset-password/<token>",
    methods=["GET", "POST"]
)
def voter_reset_password(token):
    record, error_key = _validate_reset_token(token, "voter")
    if error_key is not None:
        db.session.add(AuditLog(
            action="PASSWORD_RESET_TOKEN_REJECTED",
            module="Auth",
            description="Voter reset token rejected: %s." % error_key,
            severity="Warning",
            status="Failed",
            **_client_metadata(),
        ))
        db.session.commit()
        flash(
            "This password reset link is invalid, has already been used, or has "
            "expired. Please request a new one.",
            "danger",
        )
        return redirect(url_for("auth.voter_forgot_password"))

    student = Student.query.get(record.account_id)
    if student is None:
        flash("The account for this reset link no longer exists.", "danger")
        return redirect(url_for("auth.voter_forgot_password"))

    if request.method == "POST":
        new_password = (
            request.form.get("voter_reset_pwd")
            or request.form.get("new_password")
            or request.form.get("password")
            or ""
        )
        confirm_password = (
            request.form.get("voter_reset_confirm")
            or request.form.get("confirm_password")
            or ""
        )

        password_errors = validate_password_strength(new_password)
        if password_errors:
            for error in password_errors:
                flash(error, "warning")
            return render_template(
                "voter_reset_password.html",
                token=token,
                account_name=student.full_name,
            )

        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return render_template(
                "voter_reset_password.html",
                token=token,
                account_name=student.full_name,
            )

        student.password = generate_password_hash(new_password, method="pbkdf2:sha256")
        record.consumed = True
        record.used_at = datetime.utcnow()

        db.session.add(AuditLog(
            organization_id=student.organization_id,
            user=str(student.id),
            username=student.username or student.student_id,
            full_name=student.full_name,
            role="Student",
            action="PASSWORD_RESET_COMPLETED",
            module="Auth",
            description="Voter password reset completed via secure link.",
            severity="Info",
            status="Success",
            **_client_metadata(),
        ))
        db.session.commit()

        session.clear()
        flash(
            "Your password has been reset successfully. You can now sign in.",
            "success",
        )
        return redirect(url_for("auth.voter_login"))

    return render_template(
        "voter_reset_password.html",
        token=token,
        account_name=student.full_name,
    )