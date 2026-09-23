"""Shared test-database bootstrap for the multi-tenant test suite.

Sets MYVOICE_DATABASE to an isolated temp file *before* app/config are
imported so every test module starts from the same clean-schema baseline.
"""
import os
import tempfile
import uuid

_BASE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_BASE)

# Isolated DB per process — never touches the production database.db.
_TMP_DIR = tempfile.mkdtemp(prefix="myvoice_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_%s.db" % uuid.uuid4().hex)

os.environ["TESTING"] = "1"
os.environ["MYVOICE_DATABASE"] = _TMP_DB
os.environ["MYVOICE_SECURITY_EMAIL"] = "dev-security@example.com"

import sys as _sys  # noqa: E402
if _PARENT not in _sys.path:  # pragma: no cover
    _sys.path.insert(0, _PARENT)

from app import app  # noqa: E402
from modules.database import (  # noqa: E402
    db,
    Organization,
    Admin,
    Student,
    SystemSetting,
)
from werkzeug.security import generate_password_hash  # noqa: E402
from datetime import datetime  # noqa: E402


def _fresh_db():
    """Drop and recreate all tables, then seed a default org + owner admin.

    Returns (organization, admin) for the seeded tenant.
    """
    with app.app_context():
        db.drop_all()
        db.create_all()

        org = Organization(
            organization_uuid=uuid.uuid4().hex,
            organization_name="Test Organization",
            organization_type="School",
            status="Active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(org)
        db.session.flush()

        # Default settings row for the org.
        settings = SystemSetting(
            organization_id=org.id,
            system_name="MyVoice",
            school_name=org.organization_name,
            updated_at=datetime.utcnow(),
        )
        db.session.add(settings)

        admin = Admin(
            organization_id=org.id,
            full_name="Test Owner",
            email="owner@test.example",
            password=generate_password_hash("TestPass123!", method="pbkdf2:sha256"),
            role="owner",
            is_owner=True,
            status="Active",
            email_verified=True,
            created_at=datetime.utcnow(),
        )
        db.session.add(admin)
        db.session.commit()

        return org, admin


def _seed_secondary_org():
    """Create a second organization for cross-org isolation tests."""
    with app.app_context():
        org = Organization(
            organization_uuid=uuid.uuid4().hex,
            organization_name="Second Organization",
            organization_type="Company",
            status="Active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(org)
        db.session.flush()

        Admin(
            organization_id=org.id,
            full_name="Second Owner",
            email="owner2@test.example",
            password=generate_password_hash("TestPass456!", method="pbkdf2:sha256"),
            role="owner",
            is_owner=True,
            status="Active",
            email_verified=True,
            created_at=datetime.utcnow(),
        )
        db.session.commit()
        return org
