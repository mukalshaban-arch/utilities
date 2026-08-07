from pathlib import Path

import pytest

from app.backup import list_backups, prune_backups, BACKUP_PREFIX, BACKUP_SUFFIX
from app.models import ActivityLog
from tests.conftest import make_user, login


@pytest.fixture
def backup_dir(app, tmp_path):
    app.config["BACKUP_DIR"] = str(tmp_path)
    return tmp_path


def write_fake_backup(directory, name, mtime):
    path = Path(directory) / f"{BACKUP_PREFIX}{name}{BACKUP_SUFFIX}"
    path.write_bytes(b"PGDMP-fake")
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_backups_are_listed_newest_first(app, backup_dir):
    write_fake_backup(backup_dir, "2026-01-01_000000", mtime=1_000_000)
    write_fake_backup(backup_dir, "2026-03-01_000000", mtime=3_000_000)
    write_fake_backup(backup_dir, "2026-02-01_000000", mtime=2_000_000)

    names = [b["name"] for b in list_backups()]

    assert names[0].endswith("2026-03-01_000000.dump")
    assert names[-1].endswith("2026-01-01_000000.dump")


def test_prune_keeps_only_the_newest(app, backup_dir):
    for index in range(5):
        write_fake_backup(backup_dir, f"2026-01-0{index + 1}_000000", mtime=1_000_000 * (index + 1))

    removed = prune_backups(keep=2)

    assert len(removed) == 3
    assert len(list_backups()) == 2
    assert list_backups()[0]["name"].endswith("2026-01-05_000000.dump")


def test_backup_page_lists_files(client, db, backup_dir):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    write_fake_backup(backup_dir, "2026-05-05_120000", mtime=5_000_000)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/backups").data.decode()

    assert "utility_manager_2026-05-05_120000.dump" in body
    assert "Back Up Now" in body


def test_download_is_logged(client, db, backup_dir):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    write_fake_backup(backup_dir, "2026-05-05_120000", mtime=5_000_000)
    login(client, "ada@example.com", "pw")

    resp = client.get("/admin/backups/utility_manager_2026-05-05_120000.dump/download")

    assert resp.status_code == 200
    assert resp.data == b"PGDMP-fake"
    assert ActivityLog.query.filter_by(action="Downloaded backup").count() == 1


def test_download_cannot_escape_the_backup_directory(client, db, backup_dir):
    """A crafted name must not be able to read files elsewhere on disk."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    secret = Path(backup_dir).parent / "secret.env"
    secret.write_text("DATABASE_URL=postgresql://postgres:hunter2@localhost/db")
    login(client, "ada@example.com", "pw")

    for attempt in ("../secret.env", "..%2Fsecret.env", "....//secret.env"):
        resp = client.get(f"/admin/backups/{attempt}/download")
        assert resp.status_code == 404
        assert b"hunter2" not in resp.data


def test_backup_pages_require_login(client, db, backup_dir):
    assert b"Log In" in client.get("/admin/backups", follow_redirects=True).data
