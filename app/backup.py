"""Database backups via pg_dump.

Backups use pg_dump's custom format (-Fc): compressed, and restorable with
pg_restore. See BACKUP.md for the restore procedure.
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from flask import current_app
from sqlalchemy.engine import make_url

BACKUP_SUFFIX = ".dump"
BACKUP_PREFIX = "utility_manager_"


class BackupError(RuntimeError):
    pass


def pg_dump_path():
    """Locate pg_dump: an explicit config wins, else PATH, else a standard install."""
    configured = current_app.config.get("PG_DUMP")
    if configured:
        return configured

    found = shutil.which("pg_dump")
    if found:
        return found

    for candidate in sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin/pg_dump.exe"), reverse=True):
        return str(candidate)

    raise BackupError(
        "pg_dump was not found. Install the PostgreSQL client tools, or set PG_DUMP "
        "to the full path of pg_dump.exe."
    )


def backup_dir():
    directory = Path(current_app.config["BACKUP_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def list_backups():
    """Existing backups, newest first."""
    files = [
        {
            "name": path.name,
            "size_mb": path.stat().st_size / 1024 / 1024,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime),
        }
        for path in backup_dir().glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
    ]
    return sorted(files, key=lambda f: f["created_at"], reverse=True)


def create_backup():
    """Run pg_dump and return the path of the new backup file."""
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if not url.drivername.startswith("postgresql"):
        raise BackupError("Backups are only supported for PostgreSQL databases.")

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = backup_dir() / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"

    command = [
        pg_dump_path(),
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "postgres",
        "--dbname",
        url.database,
        "--format",
        "custom",  # compressed, and pg_restore can restore it selectively
        "--file",
        str(target),
    ]

    # The password goes in the environment, never on the command line, where it
    # would be visible to anyone listing running processes.
    env = {**os.environ}
    if url.password:
        env["PGPASSWORD"] = url.password

    try:
        subprocess.run(command, check=True, capture_output=True, env=env, timeout=600)
    except FileNotFoundError as exc:
        raise BackupError(f"Could not run pg_dump: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise BackupError("pg_dump timed out after 10 minutes.") from exc
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {exc.stderr.decode(errors='replace').strip()}") from exc

    return target


def prune_backups(keep):
    """Delete all but the newest `keep` backups. Returns the names removed."""
    removed = []
    for old in list_backups()[keep:]:
        (backup_dir() / old["name"]).unlink(missing_ok=True)
        removed.append(old["name"])
    return removed
