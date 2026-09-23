import os
import secrets
import shutil
import tempfile

# Load configuration from a .env file (if present) so that secrets such as SMTP
# credentials and the developer security email are never hard-coded in source.
try:
    from dotenv import load_dotenv

    load_dotenv(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".env"
        ),
        override=False
    )
except ImportError:
    # python-dotenv is optional; environment variables still work when set directly.
    pass


class Config:

    # =========================
    # SECURITY KEY
    # =========================
    # Production must provide MYVOICE_SECRET_KEY. Local development and tests
    # receive a random process-local key when the variable is absent.
    SECRET_KEY = os.environ.get("MYVOICE_SECRET_KEY") or secrets.token_urlsafe(32)

    # =========================
    # EMAIL / SMTP (optional)
    # =========================
    # SMTP delivery is configured exclusively through environment variables:
    #   MYVOICE_SMTP_HOST / MYVOICE_SMTP_PORT / MYVOICE_SMTP_USER
    #   MYVOICE_SMTP_PASSWORD / MYVOICE_SMTP_FROM / MYVOICE_SECURITY_EMAIL
    # See modules/emailer.py for the delivery implementation. If no SMTP host
    # is set, emails fall back to the secure server log (development only) and
    # the UI clearly indicates that email delivery is not configured.

    # =========================
    # DATABASE
    # SQLite
    # =========================

    BASE_DIR = os.path.abspath(
        os.path.dirname(__file__)
    )


    # The database path can be overridden through MYVOICE_DATABASE so tests
    # and backups never touch the live database.db file.
    def _resolve_database_path():
        default_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            "database.db"
        )
        appdata_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir()
        fallback_dir = os.path.join(appdata_dir, "MyVoice")
        os.makedirs(fallback_dir, exist_ok=True)
        fallback_path = os.path.join(fallback_dir, "database.db")

        def is_usable(path):
            try:
                directory = os.path.dirname(path) or "."
                os.makedirs(directory, exist_ok=True)
                writable = os.access(directory, os.W_OK)
                free_space = shutil.disk_usage(directory).free if os.path.isdir(directory) else 0
                return writable and free_space > 1024 * 1024
            except Exception:
                return False

        env_path = os.environ.get("MYVOICE_DATABASE")
        if env_path and is_usable(env_path):
            return env_path

        if is_usable(default_path):
            return default_path

        return fallback_path

    DATABASE_PATH = _resolve_database_path()

    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///"
        + DATABASE_PATH
    )


    SQLALCHEMY_TRACK_MODIFICATIONS = False


    # =========================
    # SESSION SETTINGS
    # =========================

    SESSION_COOKIE_HTTPONLY = True

    SESSION_COOKIE_SAMESITE = "Lax"

    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours


    # =========================
    # UPLOAD SETTINGS
    # =========================

    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads"
    )


    MAX_CONTENT_LENGTH = (
        16 * 1024 * 1024
    )