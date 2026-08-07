import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/utility_manager"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Timestamps are stored in UTC and displayed in this zone.
    TIMEZONE = os.environ.get("TIMEZONE", "Africa/Kampala")

    # Log the user out after this much inactivity. The cookie's signed timestamp is
    # refreshed on every request (sliding window), so an idle session expires server-side.
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.environ.get("SESSION_TIMEOUT_MINUTES", 5))
    )
    SESSION_REFRESH_EACH_REQUEST = True

    # Where pg_dump writes backups, and (optionally) where pg_dump itself lives.
    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(basedir, "backups"))
    PG_DUMP = os.environ.get("PG_DUMP")  # auto-detected when unset


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
