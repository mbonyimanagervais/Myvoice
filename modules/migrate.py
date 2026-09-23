"""
MYVOICE — SAFE DATABASE MIGRATION FOR MULTI-ORGANIZATION SUPPORT
================================================================

This migration UPGRADES the existing MyVoice database in place. It never deletes
database.db and never recreates it from scratch. Instead it:

  1. Creates a timestamped backup of the existing database.
  2. Runs db.create_all() so any brand-new tables (organization,
     password_reset_token) are created on a fresh database.
  3. Ensures a safe default "MyVoice Default Organization" exists.
  4. Rebuilds the `admin` and `student` tables so that:
       - every row is linked to the default organization,
       - the new columns (email, role, is_owner, status, ...) exist,
       - uniqueness of student_id / username is scoped PER ORGANIZATION
         (removing the old global UNIQUE constraints).
  5. Adds organization_id to every remaining tenanted table and links the
     legacy rows to the default organization.

Existing records (administrators, voters, elections, candidates, votes,
results, settings, notifications, audit logs, archives) are all preserved and
attached to the default organization. No record is lost or duplicated.

The function run_migrations() is idempotent and safe to call on every startup.
"""

from datetime import datetime
import os
import shutil

from sqlalchemy import inspect, text

from modules.database import db, Organization


LEGACY_ORG_NAME = "MyVoice Default Organization"
LEGACY_ORG_TYPE = "Other"


def _database_path():
    database = getattr(db.engine.url, "database", None)
    if not database:
        return None
    return database


def _backup_database():
    """Copy the live sqlite file to backups/ with a timestamp.

    Backups are important but must never block application startup. If the disk
    is full or the backup cannot be created for any filesystem reason, we skip
    the backup and continue with migration so the app remains usable.
    """
    path = _database_path()
    if not path or not os.path.exists(path):
        return None

    backup_dir = os.path.join(
        os.path.dirname(os.path.abspath(path)),
        "backups",
    )
    os.makedirs(backup_dir, exist_ok=True)

    try:
        free_bytes = shutil.disk_usage(backup_dir).free
        db_size = os.path.getsize(path)
        if free_bytes < (db_size + (1024 * 1024)):
            print(
                "[MYVOICE] Skipping database backup because the backup drive is low on space."
            )
            return None
    except Exception:
        pass

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, "database_backup_%s.db" % stamp)

    try:
        shutil.copy2(path, target)
        return target
    except OSError as exc:
        print(
            "[MYVOICE] Skipping database backup because the filesystem rejected it: %s"
            % exc
        )
        return None
    except Exception as exc:
        print("[MYVOICE] Skipping database backup due to an unexpected error: %s" % exc)
        return None


def _has_column(inspector, table, column):
    try:
        cols = [c["name"] for c in inspector.get_columns(table)]
    except Exception:
        cols = []
    return column in cols


def _ensure_legacy_organization():
    """Return the id of the legacy default organization, creating it if missing."""
    org = Organization.query.filter_by(
        organization_uuid="legacy-default-organization"
    ).first()
    if org is not None:
        return org.id
    org = Organization(
        organization_uuid="legacy-default-organization",
        organization_name=LEGACY_ORG_NAME,
        organization_type=LEGACY_ORG_TYPE,
        status="Active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(org)
    db.session.commit()
    return org.id


def _rebuild_admin(legacy_org_id):
    """Rebuild `admin` so the old global full_name UNIQUE is dropped and the
    multi-tenant + email columns are present. Legacy rows -> default org."""
    inspector = inspect(db.engine)
    if not inspector.has_table("admin"):
        return
    if _has_column(inspector, "admin", "email"):
        # Already on the new schema; just link any orphaned legacy rows.
        db.session.execute(
            text("UPDATE admin SET organization_id = :o WHERE organization_id IS NULL"),
            {"o": legacy_org_id},
        )
        db.session.commit()
        return

    db.session.execute(text(
        """
        CREATE TABLE admin_new (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER,
            full_name VARCHAR(150) NOT NULL,
            email VARCHAR(255),
            password VARCHAR(255) NOT NULL,
            role VARCHAR(30) DEFAULT 'owner',
            is_owner BOOLEAN DEFAULT 0,
            status VARCHAR(20) DEFAULT 'Active',
            email_verified BOOLEAN DEFAULT 0,
            last_login DATETIME,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    ))
    db.session.execute(
        text(
            """
            INSERT INTO admin_new
                (id, organization_id, full_name, email, password, role, is_owner,
                 status, email_verified, created_at, updated_at)
            SELECT id, :o, full_name, NULL, password, 'owner', 1, 'Active', 0,
                   COALESCE(created_at, :now), CURRENT_TIMESTAMP
            FROM admin
            """
        ),
        {"o": legacy_org_id, "now": datetime.utcnow()},
    )
    db.session.execute(text("DROP TABLE admin"))
    db.session.execute(text("ALTER TABLE admin_new RENAME TO admin"))
    db.session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_email ON admin (email) "
        "WHERE email IS NOT NULL AND email <> ''"
    ))
    db.session.commit()


def _rebuild_student(legacy_org_id):
    """Rebuild `student` so student_id / username uniqueness is scoped per
    organization and the new email + organization_id columns exist."""
    inspector = inspect(db.engine)
    if not inspector.has_table("student"):
        return
    if _has_column(inspector, "student", "email") and _has_column(
        inspector, "student", "organization_id"
    ):
        db.session.execute(
            text("UPDATE student SET organization_id = :o WHERE organization_id IS NULL"),
            {"o": legacy_org_id},
        )
        db.session.commit()
        return

    db.session.execute(text(
        """
        CREATE TABLE student_new (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER,
            student_id VARCHAR(100) NOT NULL,
            full_name VARCHAR(150) NOT NULL,
            class_name VARCHAR(100),
            department VARCHAR(100),
            username VARCHAR(100),
            email VARCHAR(255),
            password VARCHAR(255) NOT NULL,
            status VARCHAR(50) DEFAULT 'Active',
            vote_status VARCHAR(50) DEFAULT 'Not Voted',
            voted_at DATETIME,
            last_election INTEGER,
            created_at DATETIME
        )
        """
    ))
    db.session.execute(
        text(
            """
            INSERT INTO student_new
                (id, organization_id, student_id, full_name, class_name,
                 department, username, email, password, status, vote_status,
                 voted_at, last_election, created_at)
            SELECT id, :o, student_id, full_name, class_name, department,
                   username, NULL, password, status, vote_status, voted_at,
                   last_election, COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM student
            """
        ),
        {"o": legacy_org_id},
    )
    db.session.execute(text("DROP TABLE student"))
    db.session.execute(text("ALTER TABLE student_new RENAME TO student"))
    db.session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_student_org_student_id "
        "ON student (organization_id, student_id)"
    ))
    db.session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_student_org_username "
        "ON student (organization_id, username)"
    ))
    db.session.commit()


def _add_organization_column_to_tables(legacy_org_id):
    """Add organization_id to all remaining tenanted tables and link legacy rows."""
    inspector = inspect(db.engine)
    tables = [
        "recovery_request",
        "election",
        "position",
        "candidate",
        "vote",
        "system_setting",
        "notification",
        "audit_log",
        "archive",
    ]
    for table in tables:
        if not inspector.has_table(table):
            continue
        if not _has_column(inspector, table, "organization_id"):
            try:
                db.session.execute(
                    text('ALTER TABLE "%s" ADD COLUMN organization_id INTEGER' % table)
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
        try:
            db.session.execute(
                text(
                    'UPDATE "%s" SET organization_id = :o WHERE organization_id IS NULL'
                    % table
                ),
                {"o": legacy_org_id},
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def run_migrations():
    """Idempotent, safe migration for multi-organization support. Runs on startup."""
    _backup_database()

    # Create brand-new tables on a fresh database (no-op for existing tables).
    db.create_all()

    legacy_org_id = _ensure_legacy_organization()

    # Rebuild admin & student (drop old global UNIQUE constraints, add columns).
    _rebuild_admin(legacy_org_id)
    _rebuild_student(legacy_org_id)

    # Attach every other tenanted table to the default organization.
    _add_organization_column_to_tables(legacy_org_id)

    db.session.commit()
    return legacy_org_id