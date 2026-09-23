from flask_sqlalchemy import SQLAlchemy

from datetime import datetime
import secrets


db = SQLAlchemy()




# =====================================
# ORGANIZATION TABLE (MULTI-TENANCY)
# =====================================

class Organization(db.Model):

    __tablename__ = "organization"

    id = db.Column(db.Integer, primary_key=True)

    # Public-facing identifier. Never use the numeric id as a security boundary.
    organization_uuid = db.Column(
        db.String(64),
        unique=True,
        nullable=False
    )

    organization_name = db.Column(
        db.String(150),
        nullable=False
    )

    # School | University | Company | Church | NGO | Government Institution |
    # Community Organization | Other
    organization_type = db.Column(
        db.String(50),
        default="Other"
    )

    status = db.Column(
        db.String(20),
        default="Active"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def __repr__(self):
        return "<Organization %s>" % (self.organization_name or self.organization_uuid)


# =====================================
# PASSWORD RESET TOKEN TABLE
# =====================================
# Only the SHA-256 hash of the random token is ever stored. A token is
# single-use and expires automatically (see modules/auth.py).

class PasswordResetToken(db.Model):

    __tablename__ = "password_reset_token"

    id = db.Column(db.Integer, primary_key=True)

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )

    # SHA-256 hex digest of the plaintext token. The plaintext token is sent to
    # the account holder's email and is NEVER stored in the database.
    token_hash = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    # "admin" or "voter"
    account_type = db.Column(
        db.String(10),
        nullable=False
    )

    account_id = db.Column(
        db.Integer,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=False
    )

    used_at = db.Column(
        db.DateTime,
        nullable=True
    )

    consumed = db.Column(
        db.Boolean,
        default=False
    )


# =====================================
# ADMIN TABLE
# =====================================
# The administrator is always linked to exactly one organization through
# organization_id. The account that creates the organization becomes the
# organization owner (role="owner", is_owner=True).

class Admin(db.Model):

    __tablename__ = "admin"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )

    full_name = db.Column(
        db.String(150),
        nullable=False
    )

    email = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    # owner | administrator | election_manager | viewer
    role = db.Column(
        db.String(30),
        default="owner"
    )

    is_owner = db.Column(
        db.Boolean,
        default=False
    )

    status = db.Column(
        db.String(20),
        default="Active"
    )

    email_verified = db.Column(
        db.Boolean,
        default=False
    )

    last_login = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    organization = db.relationship(
        "Organization",
        backref="administrators"
    )



# =====================================
# RECOVERY REQUEST TABLE
# =====================================

class RecoveryRequest(db.Model):
    __tablename__ = "recovery_request"

    id = db.Column(db.Integer, primary_key=True)

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )
    # Public-facing identifier shared with the developer (never a secret/password).
    request_id = db.Column(db.String(100), unique=True, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"), nullable=False)
    # Legacy one-time-key column. The current design uses the long-lived
    # Developer Recovery Credential instead, so this is only retained for
    # schema compatibility and never holds a secret credential.
    key_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    approved_at = db.Column(db.DateTime, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    failed_attempts = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=5)
    # Lifecycle: PENDING -> APPROVED -> COMPLETED | REJECTED | EXPIRED | LOCKED
    status = db.Column(db.String(20), default="PENDING")
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))

    admin = db.relationship("Admin", backref="recovery_requests")




# =====================================
# STUDENT / VOTER TABLE
# =====================================

class Student(db.Model):

    __tablename__ = "student"

    # Student ID / username uniqueness is scoped PER ORGANIZATION. Two different
    # organizations may both have a voter with student_id "001".
    __table_args__ = (
        db.UniqueConstraint(
            "organization_id",
            "student_id",
            name="uq_student_org_student_id"
        ),
        db.UniqueConstraint(
            "organization_id",
            "username",
            name="uq_student_org_username"
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )

    student_id = db.Column(
        db.String(100),
        nullable=False
    )


    full_name = db.Column(
        db.String(150),
        nullable=False
    )


    class_name = db.Column(
        db.String(100)
    )


    department = db.Column(
        db.String(100)
    )


    username = db.Column(
        db.String(100)
    )

    email = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )


    password = db.Column(
        db.String(255),
        nullable=False
    )


    status = db.Column(
        db.String(50),
        default="Active"
    )


    vote_status = db.Column(
        db.String(50),
        default="Not Voted"
    )


    voted_at = db.Column(
        db.DateTime,
        nullable=True
    )


    last_election = db.Column(
        db.Integer,
        nullable=True
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    organization = db.relationship(
        "Organization",
        backref="students"
    )




# =====================================
# ELECTION TABLE
# =====================================

class Election(db.Model):

    __tablename__ = "election"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    title = db.Column(
        db.String(150),
        nullable=False
    )


    description = db.Column(
        db.Text
    )


    election_year = db.Column(
        db.String(20)
    )


    status = db.Column(
        db.String(50),
        default="Active"
    )


    visibility = db.Column(
        db.String(20),
        default="Visible"
    )


    allow_student_login_before_election = db.Column(
        db.Boolean,
        default=True
    )


    show_live_results = db.Column(
        db.Boolean,
        default=False
    )


    auto_close = db.Column(
        db.Boolean,
        default=True
    )


    auto_archive = db.Column(
        db.Boolean,
        default=True
    )


    enable_candidate_photos = db.Column(
        db.Boolean,
        default=True
    )


    enable_candidate_manifestos = db.Column(
        db.Boolean,
        default=True
    )


    allow_blank_votes = db.Column(
        db.Boolean,
        default=False
    )


    enable_vote_confirmation = db.Column(
        db.Boolean,
        default=True
    )


    enable_vote_receipts = db.Column(
        db.Boolean,
        default=False
    )


    max_votes_per_position = db.Column(
        db.Integer,
        default=1
    )


    theme_color = db.Column(
        db.String(20),
        default="#2563eb"
    )


    timezone = db.Column(
        db.String(50),
        default="UTC"
    )


    default_language = db.Column(
        db.String(20),
        default="en"
    )


    require_final_confirmation = db.Column(
        db.Boolean,
        default=True
    )


    start_date = db.Column(
        db.DateTime,
        nullable=True
    )


    end_date = db.Column(
        db.DateTime,
        nullable=True
    )


    instructions = db.Column(
        db.Text
    )


    welcome_message = db.Column(
        db.Text
    )


    help_information = db.Column(
        db.Text
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    def __repr__(self):
        return "<Election %s>" % (self.title or self.id)




# =====================================
# ELECTION_CATEGORY TABLE
# =====================================

class ElectionCategory(db.Model):

    __tablename__ = "election_category"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )

    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id"),
        nullable=True,
        index=True
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    description = db.Column(
        db.Text
    )

    display_order = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(20),
        default="Active"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def __repr__(self):
        return "<ElectionCategory %s>" % (self.name or self.id)



# =====================================
# RESULTS_VISIBILITY TABLE
# =====================================
# Tracks per-category publication state. When is_published is False the
# category results are hidden from all voters. When True, results are
# broadcast to every registered student (voters and non-voters alike).

class ResultsVisibility(db.Model):

    __tablename__ = "results_visibility"

    category_id = db.Column(
        db.Integer,
        db.ForeignKey("election_category.id"),
        primary_key=True
    )

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )

    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id"),
        nullable=True,
        index=True
    )

    is_published = db.Column(
        db.Boolean,
        default=False
    )

    broadcasted_at = db.Column(
        db.DateTime,
        nullable=True
    )

    def __repr__(self):
        return "<ResultsVisibility category=%s published=%s>" % (
            self.category_id,
            self.is_published,
        )




# =====================================
# POSITION TABLE
# =====================================

class Position(db.Model):

    __tablename__ = "position"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    name = db.Column(
        db.String(100),
        nullable=False
    )


    position_code = db.Column(
        db.String(50)
    )


    description = db.Column(
        db.Text
    )


    display_order = db.Column(
        db.Integer,
        default=0
    )


    maximum_winners = db.Column(
        db.Integer,
        default=1
    )


    category_id = db.Column(
        db.Integer,
        db.ForeignKey("election_category.id"),
        nullable=True,
        index=True
    )


    status = db.Column(
        db.String(20),
        default="Active"
    )


    created_by = db.Column(
        db.String(100)
    )


    updated_by = db.Column(
        db.String(100)
    )


    election_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "election.id"
        )
    )


    election = db.relationship(
        "Election",
        backref="positions"
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# CANDIDATE TABLE
# =====================================

class Candidate(db.Model):

    __tablename__ = "candidate"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    name = db.Column(
        db.String(150),
        nullable=False,
        default="Candidate"
    )


    full_name = db.Column(
        db.String(150)
    )


    election_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "election.id"
        )
    )


    election = db.relationship(
        "Election",
        backref="candidates"
    )


    position_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "position.id"
        )
    )


    position = db.relationship(
        "Position",
        backref="candidates"
    )


    student_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "student.id"
        )
    )


    student = db.relationship(
        "Student",
        backref="candidates"
    )


    photo = db.Column(
        db.String(255)
    )


    biography = db.Column(
        db.Text
    )


    manifesto = db.Column(
        db.Text
    )


    slogan = db.Column(
        db.String(150)
    )


    display_order = db.Column(
        db.Integer,
        default=0
    )


    status = db.Column(
        db.String(50),
        default="Draft"
    )


    created_by = db.Column(
        db.String(100)
    )


    updated_by = db.Column(
        db.String(100)
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# VOTE TABLE
# =====================================

class Vote(db.Model):

    __tablename__ = "vote"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    student_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "student.id"
        )
    )


    candidate_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "candidate.id"
        )
    )


    election_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "election.id"
        )
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# SYSTEM SETTINGS TABLE
# FEATURE 1
# =====================================

class SystemSetting(db.Model):

    __tablename__ = "system_setting"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    system_name = db.Column(
        db.String(150)
    )


    school_name = db.Column(
        db.String(150)
    )


    school_motto = db.Column(
        db.String(255)
    )


    school_logo = db.Column(
        db.String(255)
    )


    home_image = db.Column(
        db.String(255)
    )


    admin_image = db.Column(
        db.String(255)
    )


    voter_image = db.Column(
        db.String(255)
    )


    dashboard_image = db.Column(
        db.String(255)
    )


    theme = db.Column(
        db.String(50)
    )


    primary_color = db.Column(
        db.String(50)
    )


    secondary_color = db.Column(
        db.String(50)
    )


    accent_color = db.Column(
        db.String(50)
    )


    election_year = db.Column(
        db.String(20)
    )


    default_student_password = db.Column(
        db.String(255)
    )


    allow_voter_results = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )


    footer_text = db.Column(
        db.String(255)
    )

    home_hero_images = db.Column(
        db.Text,
        default="[]"
    )

    # =============================
    # DEVELOPER EMERGENCY RECOVERY
    # -----------------------------
    # NOTE: Only the credential HASH is ever stored. The plaintext
    # Developer Recovery Credential is generated once, delivered to the
    # developer's security email, and is NEVER persisted anywhere.
    # =============================

    developer_recovery_hash = db.Column(
        db.String(255)
    )


    developer_security_email = db.Column(
        db.String(150)
    )


    recovery_generated_at = db.Column(
        db.DateTime,
        nullable=True
    )


    recovery_last_at = db.Column(
        db.DateTime,
        nullable=True
    )


    recovery_events_count = db.Column(
        db.Integer,
        default=0
    )


    # Brute-force / lockout state for the emergency recovery endpoint.
    # These counters and timestamps are intentionally NOT the plaintext
    # credential — only the hash in developer_recovery_hash is ever stored.
    recovery_failed_attempts = db.Column(
        db.Integer,
        default=0
    )


    recovery_locked_until = db.Column(
        db.DateTime,
        nullable=True
    )


    recovery_lockout_count = db.Column(
        db.Integer,
        default=0
    )


    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# ARCHIVE TABLE
# =====================================

class Archive(db.Model):

    __tablename__ = "archive"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    election_name = db.Column(
        db.String(150)
    )


    results = db.Column(
        db.Text
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# NOTIFICATION TABLE
# =====================================

class Notification(db.Model):

    __tablename__ = "notification"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    message = db.Column(
        db.Text
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )




# =====================================
# AUDIT LOG TABLE
# =====================================

class AuditLog(db.Model):

    __tablename__ = "audit_log"


    id = db.Column(
        db.Integer,
        primary_key=True
    )


    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=True,
        index=True
    )


    event_id = db.Column(
        db.String(100),
        unique=True
    )


    user = db.Column(
        db.String(100)
    )


    user_id = db.Column(
        db.String(100)
    )


    username = db.Column(
        db.String(100)
    )


    full_name = db.Column(
        db.String(150)
    )


    role = db.Column(
        db.String(50),
        default="System"
    )


    action = db.Column(
        db.String(150)
    )


    module = db.Column(
        db.String(100),
        default="System"
    )


    description = db.Column(
        db.Text
    )


    severity = db.Column(
        db.String(20),
        default="Info"
    )


    status = db.Column(
        db.String(20),
        default="Success"
    )


    ip_address = db.Column(
        db.String(50)
    )


    browser = db.Column(
        db.String(100)
    )


    operating_system = db.Column(
        db.String(100)
    )


    device_type = db.Column(
        db.String(50)
    )


    session_id = db.Column(
        db.String(100)
    )


    request_url = db.Column(
        db.String(255)
    )


    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
# =====================================
# SMART EDUCATIONAL LIBRARY SYSTEM
# =====================================

class BookCategory(db.Model):

    __tablename__ = "book_category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(50), unique=True)
    description = db.Column(db.Text)
    educational_level = db.Column(db.String(50), default="All")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    books = db.relationship("Book", backref="category", lazy="dynamic")


class LibraryShelf(db.Model):

    __tablename__ = "library_shelf"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(50), unique=True)
    location = db.Column(db.String(150))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    copies = db.relationship("BookCopy", backref="shelf", lazy="dynamic")


class Book(db.Model):

    __tablename__ = "book"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    authors = db.Column(db.String(255))
    isbn = db.Column(db.String(50))
    publisher = db.Column(db.String(150))
    description = db.Column(db.Text)
    educational_level = db.Column(db.String(50), default="All")
    category_id = db.Column(db.Integer, db.ForeignKey("book_category.id"))
    total_copies = db.Column(db.Integer, default=0)
    available_copies = db.Column(db.Integer, default=0)
    cover_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    copies = db.relationship("BookCopy", backref="book", lazy="dynamic")


class BookCopy(db.Model):

    __tablename__ = "book_copy"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("book.id"), nullable=False)
    barcode = db.Column(db.String(50), unique=True)
    shelf_id = db.Column(db.Integer, db.ForeignKey("library_shelf.id"))
    condition = db.Column(db.String(50), default="Good")
    status = db.Column(db.String(50), default="Available")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    borrows = db.relationship("LibraryBorrow", backref="copy", lazy="dynamic")


class LibraryMember(db.Model):

    __tablename__ = "library_member"

    id = db.Column(db.Integer, primary_key=True)
    member_code = db.Column(db.String(50), unique=True)
    full_name = db.Column(db.String(150), nullable=False)
    member_type = db.Column(db.String(50), default="Student")
    student_id = db.Column(db.String(100))
    class_name = db.Column(db.String(100))
    department = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    status = db.Column(db.String(50), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    borrows = db.relationship("LibraryBorrow", backref="member", lazy="dynamic")


class LibraryBorrow(db.Model):

    __tablename__ = "library_borrow"

    id = db.Column(db.Integer, primary_key=True)
    borrow_code = db.Column(db.String(50), unique=True)
    member_id = db.Column(db.Integer, db.ForeignKey("library_member.id"), nullable=False)
    copy_id = db.Column(db.Integer, db.ForeignKey("book_copy.id"), nullable=False)
    borrowed_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    status = db.Column(db.String(50), default="Borrowed")
    fine_amount = db.Column(db.Float, default=0.0)
    fine_paid = db.Column(db.Boolean, default=False)
    issued_by = db.Column(db.String(100))
    return_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SeatReservation(db.Model):

    __tablename__ = "seat_reservation"

    id = db.Column(db.Integer, primary_key=True)
    seat_code = db.Column(db.String(50), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("library_member.id"))
    reservation_date = db.Column(db.Date)
    start_time = db.Column(db.String(20))
    end_time = db.Column(db.String(20))
    status = db.Column(db.String(50), default="Reserved")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)