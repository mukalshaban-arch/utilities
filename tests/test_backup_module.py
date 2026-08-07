import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.backup import BackupError, create_backup, pg_dump_path


@pytest.fixture
def pg_app(app, tmp_path):
    """App configured as if it were pointing at PostgreSQL, with a temp backup dir."""
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://bob:pw@db.example:5433/utils"
    app.config["BACKUP_DIR"] = str(tmp_path)
    return app


def test_pg_dump_path_prefers_explicit_config(app):
    app.config["PG_DUMP"] = r"C:\custom\pg_dump.exe"
    assert pg_dump_path() == r"C:\custom\pg_dump.exe"


def test_pg_dump_path_falls_back_to_path_lookup(app):
    app.config["PG_DUMP"] = None
    with patch("app.backup.shutil.which", return_value="/usr/bin/pg_dump"):
        assert pg_dump_path() == "/usr/bin/pg_dump"


def test_pg_dump_path_raises_when_not_found(app):
    app.config["PG_DUMP"] = None
    with patch("app.backup.shutil.which", return_value=None), \
         patch("app.backup.Path.glob", return_value=iter([])):
        with pytest.raises(BackupError, match="pg_dump was not found"):
            pg_dump_path()


def test_create_backup_rejects_non_postgres_database(app, tmp_path):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["BACKUP_DIR"] = str(tmp_path)
    with pytest.raises(BackupError, match="only supported for PostgreSQL"):
        create_backup()


def test_create_backup_invokes_pg_dump_safely(pg_app):
    """Credentials go via the environment, never the command line."""
    with patch("app.backup.pg_dump_path", return_value="pg_dump"), \
         patch("app.backup.subprocess.run") as run:
        target = create_backup()

    command = run.call_args.args[0]
    env = run.call_args.kwargs["env"]

    assert command[0] == "pg_dump"
    assert "--dbname" in command and "utils" in command
    assert "db.example" in command and "5433" in command
    assert env["PGPASSWORD"] == "pw"          # password passed via env
    assert "pw" not in " ".join(command)      # and NOT on the command line
    assert run.call_args.kwargs["check"] is True
    assert target.name.startswith("utility_manager_")


def test_create_backup_reports_a_failed_dump(pg_app):
    failure = subprocess.CalledProcessError(1, "pg_dump", stderr=b"role does not exist")
    with patch("app.backup.pg_dump_path", return_value="pg_dump"), \
         patch("app.backup.subprocess.run", side_effect=failure):
        with pytest.raises(BackupError, match="role does not exist"):
            create_backup()


def test_create_backup_reports_a_timeout(pg_app):
    with patch("app.backup.pg_dump_path", return_value="pg_dump"), \
         patch("app.backup.subprocess.run", side_effect=subprocess.TimeoutExpired("pg_dump", 600)):
        with pytest.raises(BackupError, match="timed out"):
            create_backup()


def test_create_backup_reports_a_missing_executable(pg_app):
    with patch("app.backup.pg_dump_path", return_value="pg_dump"), \
         patch("app.backup.subprocess.run", side_effect=FileNotFoundError("no pg_dump")):
        with pytest.raises(BackupError, match="Could not run pg_dump"):
            create_backup()
