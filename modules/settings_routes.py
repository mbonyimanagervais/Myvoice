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
    SystemSetting,
    AuditLog,
    Student,
)

from modules.security import admin_required, is_admin, generate_password_hash, verify_student_password
from werkzeug.security import generate_password_hash as werkzeug_generate_password_hash, check_password_hash

from modules.emailer import send_security_email

from datetime import datetime
from werkzeug.utils import secure_filename
import os
import secrets
from werkzeug.exceptions import RequestEntityTooLarge


# =====================================
# DEVELOPER RECOVERY CONFIGURATION
# =====================================

DEV_RECOVERY_EMAIL_ENV = "MYVOICE_SECURITY_EMAIL"

# Developer recovery support is DISABLED BY DEFAULT. It only becomes active
# when MYVOICE_SECURITY_EMAIL is configured in the environment (or .env file).
# No developer email address, password, or secret may ever be hard-coded here.


def _developer_security_email():
    """The configured developer security email, or None when not configured."""
    email = os.environ.get(DEV_RECOVERY_EMAIL_ENV, "")
    email = (email or "").strip()
    return email or None


def developer_recovery_enabled():
    """True only when a secure delivery channel for developer support is set."""
    return _developer_security_email() is not None


def _recovery_admin_authorized():
    """Init/rotate recovery is allowed for any authenticated administrator,
    even when the organization context has not been attached to the session.
    The credential lives on a system-wide settings row, so no org scope is
    required to provision or rotate it."""
    return "admin_id" in session


# Excludes visually ambiguous characters (0/O/1/I) from the credential alphabet.
CREDENTIAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_developer_credential():
    """Generate a cryptographically random credential in MYV-REC-XXXX-XXXX-XXXX-XXXX format."""
    groups = []
    for _ in range(4):
        groups.append(
            "".join(secrets.choice(CREDENTIAL_ALPHABET) for _ in range(4))
        )
    return "MYV-REC-" + "-".join(groups)


def _credential_delivery_message(credential, action):
    return (
        "MYVOICE SECURITY SYSTEM\n\n"
        "A new Developer Recovery Credential has been generated for this "
        "MyVoice installation.\n\n"
        "System:\nMyVoice Voting System\n\n"
        "Action:\n{0}\n\n"
        "Generated:\n{1} UTC\n\n"
        "Recovery Credential:\n{2}\n\n"
        "IMPORTANT:\nKeep this credential confidential. It is intended only for "
        "authorized emergency administrator account recovery. Do not publish or "
        "share this credential."
    ).format(
        action,
        datetime.utcnow().strftime("%d %b %Y, %H:%M:%S"),
        credential,
    )


def _deliver_developer_credential(settings, credential, action="generated"):
    """Deliver the credential to the developer security email (or secure server log).
    The plaintext is never stored in the DB or shown in the UI.

    Returns the recipient email, or None when recovery support is not enabled
    (no MYVOICE_SECURITY_EMAIL configured) so no phantom credential exists."""
    email = _developer_security_email()

    if not email:
        # Disabled by default: refuse to fabricate a credential that could
        # never be delivered securely. Callers must surface this clearly.
        return None

    send_security_email(
        "MYVOICE — Developer Recovery Credential Generated",
        _credential_delivery_message(credential, action),
        to_email=email,
    )
    settings.developer_security_email = email
    return email


def mask_email(email):
    """Partially mask the developer security email for display in the UI."""
    if not email:
        return ""
    local, _, domain = email.partition("@")
    if not local:
        return email
    visible = local[:2]
    return f"{visible}{'•' * 4}@{domain}"


def _recovery_status(settings):
    configured = bool(settings and settings.developer_recovery_hash)
    generated_at = settings.recovery_generated_at if settings else None
    last_at = settings.recovery_last_at if settings else None
    events = settings.recovery_events_count if settings else 0

    return {
        "configured": configured,
        "email": mask_email(settings.developer_security_email if settings else ""),
        "generated_at": generated_at,
        "last_at": last_at,
        "events": events,
    }


# =====================================
# SETTINGS BLUEPRINT
# =====================================

settings_bp = Blueprint(
    "settings",
    __name__,
    url_prefix="/admin"
)



# =====================================
# UPLOAD CONFIGURATION
# =====================================

UPLOAD_FOLDER = "static/uploads"

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg"
}



if not os.path.exists(UPLOAD_FOLDER):

    os.makedirs(UPLOAD_FOLDER)




def allowed_file(filename):

    return (
        "." in filename
        and
        filename.rsplit(".",1)[1].lower()
        in ALLOWED_EXTENSIONS
    )




# =====================================
# GET SETTINGS
# =====================================

def get_current_settings():

    org_id = session.get("organization_id")


    if org_id:

        # Organization-isolated settings: each administrator manages ONLY the
        # branding/theme row belonging to their own organization workspace.
        settings = SystemSetting.query.filter_by(
            organization_id=org_id
        ).first()


        if settings is not None:

            return settings


        settings = SystemSetting(

            system_name="",

            school_name="",

            school_motto="",

            footer_text="",


            school_logo="",

            home_image="",

            admin_image="",

            voter_image="",

            dashboard_image="",


            theme="Light",


            primary_color="#0066ff",

            secondary_color="#222222",

            accent_color="#00ff99",


            election_year="",


            default_student_password="",

            organization_id=org_id,

            updated_at=datetime.utcnow()

        )


        db.session.add(settings)

        db.session.commit()


        return settings


    # Global/public fallback (pages rendered before an organization session
    # exists, e.g. the landing page theme). This preserves legacy behaviour.
    settings = SystemSetting.query.first()


    if settings is None:


        settings = SystemSetting(

            system_name="",

            school_name="",

            school_motto="",

            footer_text="",


            school_logo="",

            home_image="",

            admin_image="",

            voter_image="",

            dashboard_image="",


            theme="Light",


            primary_color="#0066ff",

            secondary_color="#222222",

            accent_color="#00ff99",


            election_year="",


            default_student_password="",

            updated_at=datetime.utcnow()

        )


        db.session.add(settings)

        db.session.commit()


    return settings





# =====================================
# SAVE IMAGE FUNCTION
# =====================================

def save_image(file):


    if not file or not file.filename:

        return None


    if not allowed_file(file.filename):

        raise ValueError("Only JPG, JPEG, and PNG files are allowed")


    filename = secure_filename(file.filename)

    filepath = os.path.join(UPLOAD_FOLDER, filename)

    file.save(filepath)

    return filename





# =====================================
# SETTINGS PAGE
# =====================================

@settings_bp.route(
    "/settings",
    methods=[
        "GET",
        "POST"
    ]
)

def settings_page():


    if not is_admin():

        return redirect(
            url_for(
                "auth.admin_login"
            )
        )



    settings = get_current_settings()



    if request.method == "POST":

        system_name = request.form.get("system_name", "").strip()
        school_name = request.form.get("school_name", "").strip()
        election_year = request.form.get("election_year", "").strip()

        if not system_name or not school_name:
            flash("System Name and School Name are required", "danger")
            return render_template("settings.html", settings=settings, recovery_status=_recovery_status(settings))

        settings.system_name = system_name
        settings.school_name = school_name

        if election_year and not election_year.isdigit():
            flash("Election Year must be a valid year", "danger")
            return render_template("settings.html", settings=settings, recovery_status=_recovery_status(settings))


        settings.school_motto = request.form.get(
            "school_motto"
        )


        settings.footer_text = request.form.get(
            "footer_text"
        )



        settings.theme = request.form.get(
            "theme"
        )



        settings.primary_color = request.form.get(
            "primary_color"
        )


        settings.secondary_color = request.form.get(
            "secondary_color"
        )


        settings.accent_color = request.form.get(
            "accent_color"
        )



        settings.election_year = election_year



        previous_default_password = (settings.default_student_password or "").strip()
        new_default_password = (request.form.get("default_student_password") or "").strip()

        settings.default_student_password = new_default_password

        # Always check for legacy "12345" passwords when current default is not "12345"
        org_id = session.get("organization_id")
        students = Student.query.filter_by(organization_id=org_id).all() if org_id else []
        for student in students:
            password_matches_previous_default = bool(
                previous_default_password
                and verify_student_password(previous_default_password, student.password)
            )
            password_matches_legacy_default = bool(
                new_default_password != "12345"
                and verify_student_password("12345", student.password)
            )
            if password_matches_previous_default or password_matches_legacy_default:
                student.password = werkzeug_generate_password_hash(new_default_password)


        # ===============================
        # IMAGES UPLOAD
        # ===============================


        images = {

            "school_logo":
            request.files.get("school_logo"),


            "home_image":
            request.files.get("home_image"),


            "admin_image":
            request.files.get("admin_image"),


            "voter_image":
            request.files.get("voter_image"),


            "dashboard_image":
            request.files.get("dashboard_image")

        }





        for field,file in images.items():


            filename = save_image(
                file
            )


            if filename:


                setattr(
                    settings,
                    field,
                    filename
                )




        settings.updated_at = datetime.utcnow()




        # ===============================
        # AUDIT LOG
        # ===============================


        log = AuditLog(

            user=str(
                session.get(
                    "admin_id"
                )
            ),

            organization_id=session.get("organization_id"),

            action="Updated System Settings"

        )


        db.session.add(
            log
        )



        db.session.commit()




        flash(
            "Settings saved successfully",
            "success"
        )



        return redirect(
            url_for(
                "settings.settings_page"
            )
        )




    return render_template(

        "settings.html",

        settings=settings,

        recovery_status=_recovery_status(settings)

    )





# =====================================
# DEVELOPER RECOVERY - INITIALIZE
# =====================================

@settings_bp.route(
    "/settings/recovery/init",
    methods=["POST"]
)

def init_developer_recovery():


    if not _recovery_admin_authorized():

        return redirect(
            url_for(
                "auth.admin_login"
            )
        )


    settings = get_current_settings()


    if settings.developer_recovery_hash:

        flash(
            "Developer Emergency Recovery is already configured.",
            "warning"
        )

        return redirect(
            url_for(
                "settings.settings_page"
            )
        )


    admin_id = session.get("admin_id")

    if not developer_recovery_enabled():
        # Security requirement: developer support recovery is DISABLED BY
        # DEFAULT unless a secure delivery channel (MYVOICE_SECURITY_EMAIL)
        # is configured. Never pretend a credential was generated or sent.
        flash(
            "Developer recovery support is not enabled. Set "
            f"{DEV_RECOVERY_EMAIL_ENV} in the environment to enable it.",
            "warning"
        )
        return redirect(url_for("settings.settings_page"))

    credential = _generate_developer_credential()

    settings.developer_recovery_hash = generate_password_hash(credential)

    delivered_to = _deliver_developer_credential(
        settings, credential, action="generated during initialization"
    )

    if not delivered_to:
        db.session.rollback()
        flash(
            "Recovery credential could not be delivered securely. "
            "No credential was created.",
            "danger"
        )
        return redirect(url_for("settings.settings_page"))

    settings.recovery_generated_at = datetime.utcnow()

    settings.recovery_events_count = (settings.recovery_events_count or 0) + 1

    # Reset any stale lockout state from a prior configuration.
    settings.recovery_failed_attempts = 0
    settings.recovery_locked_until = None
    settings.recovery_lockout_count = 0


    db.session.add(
        AuditLog(
            user=str(admin_id),
            organization_id=session.get("organization_id"),
            action="DEVELOPER_RECOVERY_GENERATED",
            module="Settings",
            description="Developer Emergency Recovery credential generated securely.",
            severity="Info",
            status="Success",
            ip_address=request.remote_addr,
        )
    )

    db.session.commit()


    db.session.add(
        AuditLog(
            user=str(admin_id),
            organization_id=session.get("organization_id"),
            action="DEVELOPER_RECOVERY_EMAIL_SENT",
            module="Settings",
            description=f"Recovery credential delivered to {mask_email(settings.developer_security_email)}.",
            severity="Info",
            status="Success",
            ip_address=request.remote_addr,
        )
    )

    db.session.commit()


    flash(
        "Developer Emergency Recovery initialized. The recovery credential was delivered "
        "to the developer's security email. It is stored only as a hash and is not "
        "visible in this dashboard.",
        "success"
    )

    return redirect(
        url_for(
            "settings.settings_page"
        )
    )




# =====================================
# DEVELOPER RECOVERY - ROTATE
# =====================================

@settings_bp.route(
    "/settings/recovery/rotate",
    methods=["POST"]
)

def rotate_developer_recovery():


    if not _recovery_admin_authorized():

        return redirect(
            url_for(
                "auth.admin_login"
            )
        )


    settings = get_current_settings()


    if not settings.developer_recovery_hash:

        flash(
            "Developer Emergency Recovery is not configured yet. Please initialize it first.",
            "warning"
        )

        return redirect(
            url_for(
                "settings.settings_page"
            )
        )


    admin_id = session.get("admin_id")

    if not developer_recovery_enabled():
        flash(
            "Developer recovery support is not enabled. Set "
            f"{DEV_RECOVERY_EMAIL_ENV} in the environment to enable it.",
            "warning"
        )
        return redirect(url_for("settings.settings_page"))

    credential = _generate_developer_credential()

    settings.developer_recovery_hash = generate_password_hash(credential)

    delivered_to = _deliver_developer_credential(settings, credential, action="rotated")

    if not delivered_to:
        db.session.rollback()
        flash(
            "Recovery credential could not be delivered securely. "
            "No new credential was created.",
            "danger"
        )
        return redirect(url_for("settings.settings_page"))

    settings.recovery_generated_at = datetime.utcnow()

    settings.recovery_events_count = (settings.recovery_events_count or 0) + 1

    # Reset any stale lockout state after rotation.
    settings.recovery_failed_attempts = 0
    settings.recovery_locked_until = None
    settings.recovery_lockout_count = 0


    db.session.add(
        AuditLog(
            user=str(admin_id),
            organization_id=session.get("organization_id"),
            action="DEVELOPER_RECOVERY_GENERATED",
            module="Settings",
            description="Developer Emergency Recovery credential rotated.",
            severity="Info",
            status="Success",
            ip_address=request.remote_addr,
        )
    )

    db.session.commit()


    db.session.add(
        AuditLog(
            user=str(admin_id),
            action="DEVELOPER_RECOVERY_EMAIL_SENT",
            module="Settings",
            description=f"Rotated recovery credential delivered to {mask_email(settings.developer_security_email)}.",
            severity="Info",
            status="Success",
            ip_address=request.remote_addr,
        )
    )

    db.session.commit()


    flash(
        "Developer Recovery Credential rotated. The new credential is active and the previous "
        "one has been invalidated. It was delivered to the developer's security email and is "
        "never displayed here.",
        "success"
    )

    return redirect(
        url_for(
            "settings.settings_page"
        )
    )








# =====================================
# RESET SETTINGS
# =====================================

@settings_bp.route(
    "/settings/reset"
)

def reset_settings():


    if not is_admin():

        return redirect(
            url_for(
                "auth.admin_login"
            )
        )



    settings = get_current_settings()



    settings.system_name=""

    settings.school_name=""

    settings.school_motto=""

    settings.footer_text=""



    settings.school_logo=""

    settings.home_image=""

    settings.admin_image=""

    settings.voter_image=""

    settings.dashboard_image=""



    settings.theme="Light"



    settings.primary_color="#0066ff"

    settings.secondary_color="#222222"

    settings.accent_color="#00ff99"



    settings.election_year=""


    settings.default_student_password=""


    settings.updated_at=datetime.utcnow()




    db.session.commit()




    flash(

        "Settings reset successfully",

        "success"

    )



    return redirect(

        url_for(

            "settings.settings_page"

        )

    )