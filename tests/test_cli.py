from pathlib import Path
from unittest.mock import patch

from app.backup import BackupError
from app.models import User, UtilityType


def test_seed_creates_utility_types_and_admin(app, db):
    result = app.test_cli_runner().invoke(args=["seed"])

    assert result.exit_code == 0
    assert "Seeded utility types and admin user" in result.output
    names = {t.name for t in UtilityType.query.all()}
    assert names == {"Power", "Water", "Mobile Airtime", "Office Phone Airtime", "Fax"}
    admin = User.query.filter_by(email="admin@example.com").one()
    assert admin.role == "admin"
    assert admin.check_password("admin123")


def test_seed_is_idempotent(app, db):
    runner = app.test_cli_runner()
    runner.invoke(args=["seed"])
    runner.invoke(args=["seed"])

    assert UtilityType.query.count() == 5          # not duplicated
    assert User.query.filter_by(email="admin@example.com").count() == 1


def test_seed_accepts_custom_admin_credentials(app, db):
    app.test_cli_runner().invoke(
        args=["seed", "--admin-email", "boss@example.com", "--admin-password", "s3cret-pass"]
    )

    admin = User.query.filter_by(email="boss@example.com").one()
    assert admin.check_password("s3cret-pass")


def test_backup_command_reports_written_file_and_prunes(app, db, tmp_path):
    target = tmp_path / "utility_manager_2026-01-01_000000.dump"
    target.write_bytes(b"PGDMP" * 300)

    with patch("app.backup.create_backup", return_value=target), \
         patch("app.backup.prune_backups", return_value=["old_one.dump"]):
        result = app.test_cli_runner().invoke(args=["backup", "--keep", "5"])

    assert result.exit_code == 0
    assert "Backup written" in result.output
    assert "Pruned old backup: old_one.dump" in result.output


def test_backup_command_exits_with_an_error_message(app, db):
    with patch("app.backup.create_backup", side_effect=BackupError("pg_dump not found")):
        result = app.test_cli_runner().invoke(args=["backup"])

    assert result.exit_code != 0
    assert "pg_dump not found" in str(result.exception)
