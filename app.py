from flask import (
    Flask,
    Response,
    render_template,
    redirect,
    url_for,
    session,
    request
)

from sqlalchemy import inspect, text
import os

from config import Config

from modules.database import (
    db,
    SystemSetting,
    Student,
    Election,
    ElectionCategory,
    ResultsVisibility
)

from modules.auth import (
    auth,
    create_default_admin
)

from modules.security import (
    admin_required,
    is_admin,
    log_audit,
    generate_password_hash,
    verify_password
)
from modules.settings import get_settings


# =====================================
# CREATE APPLICATION
# =====================================

app = Flask(__name__)


# =====================================
# CONFIGURATION
# =====================================

app.config.from_object(Config)


# =====================================
# CREATE REQUIRED FOLDERS
# =====================================

folders = [
    "static/uploads",
    "uploads",
    "backups"
]


if not (
    os.environ.get("VERCEL")
    or os.environ.get("AWS_LAMBDA_FUNCTION_VERSION")
):

    for folder in folders:

        if not os.path.exists(folder):

            os.makedirs(folder)


# =====================================
# DATABASE INIT
# =====================================

db.init_app(app)


# =====================================
# GLOBAL SETTINGS
# =====================================

@app.context_processor
def inject_settings():

    from modules.security import current_organization_id

    try:
        org_id = current_organization_id()
        settings = None
        if org_id:
            settings = SystemSetting.query.filter_by(organization_id=org_id).first()
        if settings is None:
            settings = SystemSetting.query.first()
    except Exception:
        settings = None

    from datetime import datetime

    return {
        "system_settings": settings,
        "now": datetime.now()
    }


# =====================================
# REGISTER BLUEPRINTS
# =====================================

# AUTH

app.register_blueprint(
    auth
)


# SETTINGS

from modules.settings_routes import settings_bp

app.register_blueprint(
    settings_bp
)


# STUDENTS

from modules.students import students_bp

app.register_blueprint(
    students_bp
)


# ELECTIONS

from modules.elections import elections

app.register_blueprint(
    elections
)


# POSITIONS

from modules.positions import positions

app.register_blueprint(
    positions
)


# CANDIDATES

from modules.candidates import candidates

app.register_blueprint(
    candidates
)


# VOTING

from modules.voting import voting

app.register_blueprint(
    voting
)


# REPORTS

from modules.reports import reports

app.register_blueprint(
    reports
)


# NOTIFICATIONS

from modules.notifications import notifications

app.register_blueprint(
    notifications
)


# AUDIT LOGS

from modules.logs import logs

app.register_blueprint(
    logs
)


# VOTER PARTICIPATION

from modules.participation import participation

app.register_blueprint(
    participation
)


# =====================================
# DATABASE CREATE
# =====================================

def ensure_student_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("student"):
        return

    columns = [column["name"] for column in inspector.get_columns("student")]

    with db.engine.begin() as connection:
        if "department" not in columns:
            connection.execute(text("ALTER TABLE student ADD COLUMN department VARCHAR(100)"))

        if "username" not in columns:
            connection.execute(text("ALTER TABLE student ADD COLUMN username VARCHAR(100)"))

        if "voted_at" not in columns:
            connection.execute(text("ALTER TABLE student ADD COLUMN voted_at DATETIME"))

        if "last_election" not in columns:
            connection.execute(text("ALTER TABLE student ADD COLUMN last_election INTEGER"))


def ensure_election_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("election"):
        return

    columns = [column["name"] for column in inspector.get_columns("election")]
    column_definitions = {
        "visibility": "VARCHAR(20)",
        "allow_student_login_before_election": "BOOLEAN",
        "show_live_results": "BOOLEAN",
        "auto_close": "BOOLEAN",
        "auto_archive": "BOOLEAN",
        "enable_candidate_photos": "BOOLEAN",
        "enable_candidate_manifestos": "BOOLEAN",
        "allow_blank_votes": "BOOLEAN",
        "enable_vote_confirmation": "BOOLEAN",
        "enable_vote_receipts": "BOOLEAN",
        "max_votes_per_position": "INTEGER",
        "theme_color": "VARCHAR(20)",
        "timezone": "VARCHAR(50)",
        "default_language": "VARCHAR(20)",
        "require_final_confirmation": "BOOLEAN",
        "start_date": "DATETIME",
        "end_date": "DATETIME",
        "instructions": "TEXT",
        "welcome_message": "TEXT",
        "help_information": "TEXT",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE election ADD COLUMN {column_name} {definition}"))


def ensure_position_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("position"):
        return

    columns = [column["name"] for column in inspector.get_columns("position")]
    column_definitions = {
        "position_code": "VARCHAR(50)",
        "description": "TEXT",
        "display_order": "INTEGER",
        "maximum_winners": "INTEGER",
        "status": "VARCHAR(20)",
        "created_by": "VARCHAR(100)",
        "updated_by": "VARCHAR(100)",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE position ADD COLUMN {column_name} {definition}"))


def ensure_candidate_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("candidate"):
        return

    columns = [column["name"] for column in inspector.get_columns("candidate")]
    column_definitions = {
        "full_name": "VARCHAR(150)",
        "election_id": "INTEGER",
        "student_id": "INTEGER",
        "biography": "TEXT",
        "manifesto": "TEXT",
        "slogan": "VARCHAR(150)",
        "display_order": "INTEGER",
        "status": "VARCHAR(50)",
        "created_by": "VARCHAR(100)",
        "updated_by": "VARCHAR(100)",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE candidate ADD COLUMN {column_name} {definition}"))


def ensure_system_setting_table():
    inspector = inspect(db.engine)
    if inspector.has_table("system_setting"):
        return

    with db.engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE system_setting (
                id INTEGER NOT NULL,
                system_name VARCHAR(150),
                school_name VARCHAR(150),
                school_motto VARCHAR(255),
                school_logo VARCHAR(255),
                home_image VARCHAR(255),
                admin_image VARCHAR(255),
                voter_image VARCHAR(255),
                dashboard_image VARCHAR(255),
                theme VARCHAR(50),
                primary_color VARCHAR(50),
                secondary_color VARCHAR(50),
                accent_color VARCHAR(50),
                election_year VARCHAR(20),
                default_student_password VARCHAR(255),
                allow_voter_results BOOLEAN DEFAULT 0 NOT NULL,
                footer_text VARCHAR(255),
                developer_recovery_hash VARCHAR(255),
                developer_security_email VARCHAR(150),
                recovery_generated_at DATETIME,
                recovery_last_at DATETIME,
                recovery_events_count INTEGER,
                recovery_failed_attempts INTEGER,
                recovery_locked_until DATETIME,
                recovery_lockout_count INTEGER,
                updated_at DATETIME,
                PRIMARY KEY (id)
            )
        """))


def ensure_system_setting_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("system_setting"):
        return

    columns = [column["name"] for column in inspector.get_columns("system_setting")]
    column_definitions = {
        "developer_recovery_hash": "VARCHAR(255)",
        "developer_security_email": "VARCHAR(150)",
        "recovery_generated_at": "DATETIME",
        "recovery_last_at": "DATETIME",
        "recovery_events_count": "INTEGER",
        "recovery_failed_attempts": "INTEGER",
        "recovery_locked_until": "DATETIME",
        "recovery_lockout_count": "INTEGER",
        "home_hero_images": "TEXT",
        "allow_voter_results": "BOOLEAN DEFAULT 0 NOT NULL",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE system_setting ADD COLUMN {column_name} {definition}"))


def ensure_audit_log_columns():
    inspector = inspect(db.engine)
    if not inspector.has_table("audit_log"):
        return

    columns = [column["name"] for column in inspector.get_columns("audit_log")]
    column_definitions = {
        "event_id": "VARCHAR(100)",
        "user_id": "VARCHAR(100)",
        "username": "VARCHAR(100)",
        "full_name": "VARCHAR(150)",
        "role": "VARCHAR(50)",
        "module": "VARCHAR(100)",
        "description": "TEXT",
        "severity": "VARCHAR(20)",
        "status": "VARCHAR(20)",
        "ip_address": "VARCHAR(50)",
        "browser": "VARCHAR(100)",
        "operating_system": "VARCHAR(100)",
        "device_type": "VARCHAR(50)",
        "session_id": "VARCHAR(100)",
        "request_url": "VARCHAR(255)",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE audit_log ADD COLUMN {column_name} {definition}"))


def ensure_recovery_request_columns():
    """Ensure the recovery_request lifecycle column exists on older databases."""
    inspector = inspect(db.engine)
    if not inspector.has_table("recovery_request"):
        return

    columns = [column["name"] for column in inspector.get_columns("recovery_request")]
    column_definitions = {
        "approved_at": "DATETIME",
    }

    with db.engine.begin() as connection:
        for column_name, definition in column_definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE recovery_request ADD COLUMN {column_name} {definition}"))


def ensure_category_tables():
    """Create election_category and results_visibility tables on legacy databases."""
    inspector = inspect(db.engine)

    if not inspector.has_table("election_category"):
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE election_category (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    election_id INTEGER,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    display_order INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'Active',
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))

    if not inspector.has_table("results_visibility"):
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE results_visibility (
                    category_id INTEGER NOT NULL,
                    organization_id INTEGER,
                    election_id INTEGER,
                    is_published BOOLEAN DEFAULT 0,
                    broadcasted_at DATETIME,
                    PRIMARY KEY (category_id),
                    FOREIGN KEY (category_id) REFERENCES election_category(id)
                )
            """))
    for table in ("election_category", "results_visibility"):
        columns = [column["name"] for column in inspect(db.engine).get_columns(table)]
        if "election_id" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE %s ADD COLUMN election_id INTEGER" % table)
                )


def ensure_category_columns():
    """Add category_id column to position table on legacy databases."""
    inspector = inspect(db.engine)
    if not inspector.has_table("position"):
        return

    columns = [column["name"] for column in inspector.get_columns("position")]
    if "category_id" not in columns:
        with db.engine.begin() as connection:
            connection.execute(text("ALTER TABLE position ADD COLUMN category_id INTEGER"))


with app.app_context():

    db.create_all()
    ensure_student_columns()
    ensure_election_columns()
    ensure_position_columns()
    ensure_candidate_columns()
    ensure_category_columns()
    ensure_category_tables()
    ensure_system_setting_table()
    ensure_system_setting_columns()
    ensure_audit_log_columns()
    ensure_recovery_request_columns()

    # Multi-organization migration: backs up the database, attaches every
    # legacy record to the default organization and adds the schema the
    # tenant (organization_id) columns require. Safe to run on every start.
    from modules.migrate import run_migrations
    run_migrations()

    create_default_admin()


# =====================================
# THEME STYLESHEET
# =====================================

# =====================================
# PUBLIC SETTINGS RESOLVER
# =====================================

def _resolve_public_settings():
    """Settings for public/theme pages: honor the active organization session
    (admin or voter) and fall back to the legacy global row for anonymous
    visitors — but never expose another organization's branding."""
    from modules.security import current_organization_id

    org_id = (
        current_organization_id()
        or session.get("voter_org_id")
    )

    if org_id is not None:
        org_settings = SystemSetting.query.filter_by(
            organization_id=org_id
        ).first()
        if org_settings is not None:
            return org_settings

    return SystemSetting.query.first()


@app.route("/theme.css")
def theme_css():

    try:
        settings = _resolve_public_settings()
    except Exception:
        settings = None

    if settings is None:
        settings = SystemSetting(
            theme="Light",
            primary_color="#2563eb",
            secondary_color="#0f172a",
            accent_color="#38bdf8"
        )

    theme_name = (settings.theme or "Light").strip().lower()
    primary = settings.primary_color or "#2563eb"
    secondary = settings.secondary_color or "#0f172a"
    accent = settings.accent_color or "#38bdf8"

    if theme_name == "dark":
        app_bg = "#07111f"
        surface = "#111827"
        surface_alt = "#1f2937"
        text_primary = "#f8fafc"
        text_muted = "#94a3b8"
        border = "rgba(148, 163, 184, 0.24)"
        shadow = "0 22px 55px rgba(2, 8, 23, 0.45)"
        shadow_sm = "0 10px 26px rgba(2, 8, 23, 0.3)"
        accent_soft = "rgba(56, 189, 248, 0.18)"
    elif theme_name == "blue":
        app_bg = "linear-gradient(135deg, #071b3d 0%, #0f4c81 100%)"
        surface = "#0f172a"
        surface_alt = "#11233f"
        text_primary = "#f8fafc"
        text_muted = "#cbd5e1"
        border = "rgba(125, 211, 252, 0.24)"
        shadow = "0 22px 55px rgba(2, 8, 23, 0.35)"
        shadow_sm = "0 10px 26px rgba(2, 8, 23, 0.24)"
        accent_soft = "rgba(56, 189, 248, 0.2)"
    elif theme_name == "school":
        app_bg = "linear-gradient(135deg, #f4f0e8 0%, #e7f0ea 100%)"
        surface = "#ffffff"
        surface_alt = "#f8f6ef"
        text_primary = "#17312f"
        text_muted = "#58706d"
        border = "rgba(88, 105, 95, 0.2)"
        shadow = "0 22px 55px rgba(15, 23, 42, 0.12)"
        shadow_sm = "0 10px 26px rgba(15, 23, 42, 0.08)"
        accent_soft = "rgba(0, 153, 102, 0.16)"
    else:
        app_bg = "linear-gradient(135deg, #f8fbff 0%, #eef4ff 100%)"
        surface = "#ffffff"
        surface_alt = "#f8fbff"
        text_primary = "#0f172a"
        text_muted = "#64748b"
        border = "rgba(148, 163, 184, 0.24)"
        shadow = "0 22px 55px rgba(15, 23, 42, 0.12)"
        shadow_sm = "0 10px 26px rgba(15, 23, 42, 0.08)"
        accent_soft = "rgba(37, 99, 235, 0.12)"

    css = f"""
:root {{
  --primary-color: {primary};
  --secondary-color: {secondary};
  --accent-color: {accent};
  --app-bg: {app_bg};
  --surface: {surface};
  --surface-alt: {surface_alt};
  --text-primary: {text_primary};
  --text-muted: {text_muted};
  --border-color: {border};
  --shadow-lg: {shadow};
  --shadow-md: {shadow_sm};
  --accent-soft: {accent_soft};
}}

body {{
  background: var(--app-bg);
  color: var(--text-primary);
}}

.card, .form-card, .table-card, .stat-card, .overview-card, .dashboard-header, .admin-container, .container, .home-card, .login-card, .option-card, .position-box, .candidate-card {{
  background: var(--surface);
  border-color: var(--border-color);
  color: var(--text-primary);
  box-shadow: var(--shadow-md);
}}

h1, h2, h3, h4, strong {{
  color: var(--text-primary);
}}

p, label, .muted {{
  color: var(--text-muted);
}}

button, .btn, .card-action, .logout-link {{
  background: var(--primary-color);
  color: #ffffff;
}}

button:hover, .btn:hover, .card-action:hover, .logout-link:hover {{
  background: var(--secondary-color);
}}

input, select, textarea {{
  background: var(--surface-alt);
  color: var(--text-primary);
  border-color: var(--border-color);
}}

input:focus, select:focus, textarea:focus {{
  border-color: var(--accent-color);
  box-shadow: 0 0 0 3px var(--accent-soft);
}}
"""

    return Response(css, mimetype="text/css")


# =====================================
# HOME PAGE
# =====================================

@app.route("/")
def index():
    from datetime import datetime
    try:
        settings = _resolve_public_settings()
    except Exception:
        settings = None

    # Dynamically load homepage images from uploads/homepage_image/
    hero_images = []
    homepage_img_dir = os.path.join(app.config["BASE_DIR"], "uploads", "homepage_image")
    if os.path.isdir(homepage_img_dir):
        for name in sorted(os.listdir(homepage_img_dir)):
            ext = os.path.splitext(name)[1].lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp"):
                hero_images.append(name)

    if not hero_images:
        hero_images = [
            "image-01.jpg",
            "image-02.jpg",
            "image-03.jpg",
            "image-04.jpg",
            "image-05.jpg",
            "image-06.jpg",
        ]

    return render_template(
        "index.html",
        system_settings=settings,
        home_hero_images=hero_images,
        now=datetime.now()
    )


# =====================================
# ADMIN DASHBOARD
# =====================================

@app.route("/admin/dashboard/voter-results", methods=["POST"])
@admin_required
def update_voter_results_visibility():
    settings = get_settings()
    settings.allow_voter_results = request.form.get("allow_voter_results") == "on"
    db.session.commit()
    return redirect(url_for("reports.results_page"))

@app.route("/admin/dashboard")
def admin_home():

    if "admin_id" not in session:

        return redirect(
            url_for(
                "auth.admin_login"
            )
        )

    from modules.database import (
        Admin,
        Organization,
        Election,
        Position,
        Candidate,
        Student,
        Vote,
        Notification,
        AuditLog,
    )
    from modules.security import current_organization_id
    from sqlalchemy import func

    admin = Admin.query.get(session.get("admin_id"))
    current_org = (
        Organization.query.get(session.get("organization_id"))
        if session.get("organization_id") else None
    )

    if admin is None:
        session.clear()
        return redirect(url_for("auth.admin_login"))

    org_id = current_organization_id()
    settings = get_settings()

    # --- KPI base queries (org-scoped where it makes sense) ---
    election_q = Election.query
    student_q = Student.query
    position_q = Position.query
    candidate_q = Candidate.query
    vote_q = Vote.query
    notification_q = Notification.query
    audit_q = AuditLog.query

    if org_id is not None:
        election_q = election_q.filter(Election.organization_id == org_id)
        student_q = student_q.filter(Student.organization_id == org_id)
        position_q = position_q.filter(Position.organization_id == org_id)
        candidate_q = candidate_q.filter(Candidate.organization_id == org_id)
        vote_q = vote_q.filter(Vote.organization_id == org_id)
        notification_q = notification_q.filter(Notification.organization_id == org_id)
        audit_q = audit_q.filter(AuditLog.organization_id == org_id)

    total_elections = election_q.count()
    active_elections = election_q.filter(Election.status == "Active").count()
    closed_elections = election_q.filter(Election.status == "Closed").count()
    draft_elections = election_q.filter(Election.status == "Draft").count()
    ready_elections = election_q.filter(Election.status == "Ready").count()
    archived_elections = election_q.filter(Election.status == "Archived").count()

    active_election = (
        election_q.filter(Election.status == "Active")
        .order_by(Election.id.desc())
        .first()
    )

    total_students = student_q.filter(Student.status == "Active").count()
    total_candidates = candidate_q.count()
    total_positions = position_q.count()
    total_votes = vote_q.count()

    if active_election is not None:
        eligible_students = student_q.filter(Student.status == "Active").count()
        voted_students = (
            db.session.query(func.count(func.distinct(Vote.student_id)))
            .filter(
                Vote.election_id == active_election.id,
                Vote.student_id.isnot(None),
            )
            .scalar()
            or 0
        )
        not_voted_students = max(int(eligible_students or 0) - int(voted_students or 0), 0)
        participation_rate = (
            round((voted_students / eligible_students) * 100, 1)
            if eligible_students
            else 0.0
        )
    else:
        eligible_students = total_students
        voted_students = total_votes
        not_voted_students = max(total_students - total_votes, 0)
        participation_rate = (
            round((total_votes / total_students) * 100, 1) if total_students else 0.0
        )

    # --- Active election position progress (top 5) ---
    position_progress = []
    candidate_ranking = []
    department_breakdown = []
    if active_election is not None:
        positions = (
            position_q.filter(Position.election_id == active_election.id)
            .order_by(Position.display_order.asc(), Position.id.asc())
            .all()
        )
        for pos in positions:
            pos_votes = (
                vote_q.filter(
                    Vote.election_id == active_election.id,
                )
                .join(Candidate, Candidate.id == Vote.candidate_id)
                .filter(Candidate.position_id == pos.id)
                .count()
            )
            position_progress.append({
                "id": pos.id,
                "name": pos.name,
                "votes": pos_votes,
            })

        for pos in positions:
            candidates = (
                candidate_q.filter(Candidate.position_id == pos.id)
                .order_by(Candidate.display_order.asc(), Candidate.id.asc())
                .all()
            )
            for cand in candidates:
                cv = (
                    vote_q.filter(
                        Vote.election_id == active_election.id,
                        Vote.candidate_id == cand.id,
                    ).count()
                )
                candidate_ranking.append({
                    "name": cand.full_name or cand.name or "Candidate",
                    "position": pos.name,
                    "votes": cv,
                })
        candidate_ranking.sort(key=lambda c: c["votes"], reverse=True)
        candidate_ranking = candidate_ranking[:8]

        # Department breakdown
        dept_rows = (
            db.session.query(
                func.coalesce(Student.department, "Unspecified").label("dept"),
                func.count(Student.id).label("total"),
            )
            .filter(Student.organization_id == org_id, Student.status == "Active")
            .group_by("dept")
            .order_by(func.count(Student.id).desc())
            .limit(6)
            .all()
        ) if org_id is not None else []
        for dept_name, dept_total in dept_rows:
            voted_in_dept = (
                db.session.query(func.count(func.distinct(Vote.student_id)))
                .join(Student, Student.id == Vote.student_id)
                .filter(
                    Vote.election_id == active_election.id,
                    Student.organization_id == org_id,
                    Student.department == dept_name,
                )
                .scalar()
                or 0
            )
            department_breakdown.append({
                "name": dept_name or "Unspecified",
                "total": int(dept_total or 0),
                "voted": int(voted_in_dept or 0),
            })

    # --- Recent activity (audit log) ---
    recent_activity = (
        audit_q.order_by(AuditLog.created_at.desc()).limit(8).all()
    )

    # --- Notifications (latest) ---
    recent_notifications = (
        notification_q.order_by(Notification.created_at.desc()).limit(5).all()
    )
    unread_notifications = (
        notification_q.filter(Notification.status != "Read").count()
        if hasattr(Notification, "status")
        else notification_q.count()
    )

    # --- Security / system health ---
    from datetime import datetime, timedelta
    fifteen_min_ago = datetime.utcnow() - timedelta(minutes=15)
    recent_failed_logins = (
        audit_q.filter(
            AuditLog.action.in_(
                [
                    "ADMIN_LOGIN_FAILED",
                    "VOTER_LOGIN_FAILED",
                    "ADMIN_RECOVERY_FAILED",
                ]
            ),
            AuditLog.created_at >= fifteen_min_ago,
        ).count()
    )

    # --- Voting activity (last 7 days, real Vote timestamps) ---
    voting_activity_labels = []
    voting_activity_values = []
    for offset in range(6, -1, -1):
        day_start = datetime.utcnow() - timedelta(days=offset, hours=datetime.utcnow().hour,
                                                  minutes=datetime.utcnow().minute,
                                                  seconds=datetime.utcnow().second)
        day_end = day_start + timedelta(days=1)
        count = (
            vote_q.filter(
                Vote.created_at >= day_start,
                Vote.created_at < day_end,
            ).count()
        )
        voting_activity_labels.append(day_start.strftime("%b %d"))
        voting_activity_values.append(int(count))

    # --- Election status distribution ---
    election_status_data = {
        "Draft": draft_elections,
        "Ready": ready_elections,
        "Active": active_elections,
        "Closed": closed_elections,
        "Archived": archived_elections,
    }

    return render_template(
        "admin_dashboard.html",
        current_admin=admin,
        current_org=current_org,
        kpis={
            "total_elections": total_elections,
            "active_elections": active_elections,
            "closed_elections": closed_elections,
            "total_students": total_students,
            "students_voted": int(voted_students or 0),
            "students_not_voted": not_voted_students,
            "participation_rate": participation_rate,
            "total_candidates": total_candidates,
            "total_positions": total_positions,
            "total_votes": total_votes,
        },
        active_election=active_election,
        position_progress=position_progress,
        candidate_ranking=candidate_ranking,
        department_breakdown=department_breakdown,
        recent_activity=recent_activity,
        recent_notifications=recent_notifications,
        unread_notifications=unread_notifications,
        recent_failed_logins=recent_failed_logins,
        voting_activity_labels=voting_activity_labels,
        voting_activity_values=voting_activity_values,
        election_status_data=election_status_data,
        allow_voter_results=bool(settings.allow_voter_results),
    )


# =====================================
# VOTER DASHBOARD
# =====================================

@app.route("/voter/dashboard")
def voter_home():

    if "student_id" not in session:

        return redirect(
            url_for(
                "auth.voter_login"
            )
        )

    student = Student.query.get(session.get("student_id"))

    if student is not None:
        session["voter_name"] = student.full_name
        session["voter_org_id"] = student.organization_id

    org_id = session.get("voter_org_id") or (
        student.organization_id if student else None
    )

    # A voter may only ever see elections published by their OWN organization.
    if org_id:
        elections = Election.query.filter_by(
            status="Active",
            organization_id=org_id
        ).all()
    else:
        elections = []

    return render_template(
        "voter_dashboard.html",
        elections=elections
    )


# =====================================
# HEALTH CHECK
# =====================================

# =====================================
# SERVE UPLOADED FILES
# =====================================

@app.route("/uploads/candidates/<filename>")
def serve_candidate_photo(filename):
    """Serve candidate photos from uploads folder"""
    from flask import send_from_directory
    uploads_dir = os.path.join(app.config["BASE_DIR"], "uploads", "candidates")
    return send_from_directory(uploads_dir, filename)


@app.route("/uploads/homepage_image/<filename>")
def serve_homepage_image(filename):
    """Serve homepage hero images from uploads folder.

    Only serves files with safe extensions (.jpg, .jpeg, .png, .webp)
    to prevent path traversal attacks.
    """
    from flask import send_from_directory, abort
    import os as _os
    safe_ext = {".jpg", ".jpeg", ".png", ".webp"}
    ext = _os.path.splitext(filename)[1].lower()
    if ext not in safe_ext:
        abort(404)
    uploads_dir = _os.path.join(app.config["BASE_DIR"], "uploads", "homepage_image")
    return send_from_directory(uploads_dir, filename)


# =====================================
# HEALTH CHECK
# =====================================

@app.route("/health")
def health():

    return "MyVoice System Running"


# =====================================
# PUBLIC SEO FILES
# =====================================

@app.route("/google65a4682dad9a0e59.html")
def google_site_verification():

    return Response(
        "google-site-verification: google65a4682dad9a0e59.html",
        mimetype="text/plain"
    )


@app.route("/robots.txt")
def robots_txt():

    return Response(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /voter\n"
        "Disallow: /voter/\n"
        "Disallow: /vote\n"
        "Disallow: /voting\n"
        "Disallow: /results\n"
        "Disallow: /api\n"
        "Disallow: /settings\n"
        "Disallow: /audit_logs\n"
        "Disallow: /archive\n"
        "Disallow: /notifications\n"
        "Sitemap: https://myvoice-voting-by-ithardweak.vercel.app/sitemap.xml\n",
        mimetype="text/plain"
    )


@app.route("/sitemap.xml")
def sitemap_xml():

    return Response(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        "  <url>\n"
        "    <loc>https://myvoice-voting-by-ithardweak.vercel.app/</loc>\n"
        "  </url>\n"
        "</urlset>\n",
        mimetype="application/xml"
    )


# =====================================
# ADMIN DISCOVERY ENDPOINT — DISABLED
# =====================================
# The previous /admin/show-admins endpoint rendered a public list of every
# administrator (including usernames and creation timestamps) without any
# access control beyond a logged-in admin. That information MUST NOT be
# exposed on the public web.
#
# If a future administrator-management module is built, it must:
#   1. require an active administrator session,
#   2. scope the listing to the caller's own organization, and
#   3. never include passwords, password hashes, security credentials,
#      or sensitive contact information.
#
# Until then, the route is removed to prevent credential enumeration.


# =====================================
# RESET ADMIN (BACKDOOR REMOVED)
# =====================================
# The previous /reset_admin endpoint relied on a hard-coded recovery code stored
# in the repository — a permanent hidden administrator backdoor. That is
# explicitly forbidden by the Developer Emergency Recovery design.
#
# Authorized administrator password recovery must go through the audited,
# developer-assisted emergency recovery flow instead:
#
#     /admin/forgot-password  ->  /admin/recovery  ->  /admin/reset-password


# =====================================
# ERROR HANDLER
# =====================================

@app.errorhandler(404)
def page_not_found(error):

    return "Page Not Found", 404


# =====================================
# RUN SYSTEM
# =====================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=5000,

        debug=True

    )