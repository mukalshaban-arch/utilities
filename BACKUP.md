# Backups & Restore

Backups are PostgreSQL custom-format dumps (`pg_dump -Fc`): compressed, and restorable
with `pg_restore`. They land in the `backups/` folder (override with `BACKUP_DIR`).

A backup that has never been restored is not a backup. The procedure below is the one
used to verify this setup works — run it yourself once so you trust it.

---

## Taking a backup

**From the app:** Admin dashboard → **Backups** → **Back Up Now**. The file is listed
with its size, and can be downloaded.

**From the command line** (also what the scheduled task runs):

```
flask backup                 # keeps the newest 30 backups
flask backup --keep 7        # keep only a week's worth
```

> **Copy backups off this machine.** A backup sitting on the same disk as the database
> will not survive that disk failing. Download them, or point `BACKUP_DIR` at a network
> share / synced folder.

---

## Scheduling a daily backup (Windows Task Scheduler)

1. Create `backup.bat` in the project root:

   ```bat
   @echo off
   cd /d D:\qw
   set FLASK_APP=run.py
   venv\Scripts\python.exe -m flask backup --keep 30
   ```

2. Open **Task Scheduler** → **Create Task** (not "Basic Task").
   - **General:** name it `Utility Manager Backup`. Tick **Run whether user is logged on
     or not**, and **Run with highest privileges**.
   - **Triggers → New:** Daily, at e.g. `02:00`.
   - **Actions → New:** Program/script `D:\qw\backup.bat`, Start in `D:\qw`.
   - **Settings:** tick **Run task as soon as possible after a scheduled start is missed**
     (so a backup still happens if the machine was off overnight).

3. Right-click the task → **Run** once, then check that a new file appeared in `backups\`.

---

## Restoring

**Restoring overwrites data. Take a fresh backup of the current database first** — even
if you think it is broken, it is your only way back if the restore goes wrong.

Everything below uses the PostgreSQL tools at
`C:\Program Files\PostgreSQL\18\bin`. Set the password once per shell:

```
set PGPASSWORD=your_postgres_password
```

### Option A — Restore into a NEW database first (recommended)

Prove the backup is good before you touch the live one.

```
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE utility_check;"

"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U postgres ^
    -d utility_check backups\utility_manager_2026-07-12_184803.dump
```

Point the app at it by editing `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/utility_check
```

Start the app and check the data looks right. If it does, either keep using this database,
or proceed to Option B to restore over the real one.

### Option B — Restore over the live database

This **destroys** the current contents of `utility_manager`.

1. Stop the app (close it, or stop the service) so nothing is writing.
2. Recreate the database empty and restore into it:

```
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "DROP DATABASE utility_manager;"
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE utility_manager;"

"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U postgres ^
    -d utility_manager backups\utility_manager_2026-07-12_184803.dump
```

3. Start the app and log in.

> If `DROP DATABASE` complains that the database is in use, something is still connected —
> close the app, any `psql` sessions, and pgAdmin, then retry.

### Restoring a single table

Custom-format dumps allow selective restore, e.g. to recover only the beneficiary register:

```
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U postgres -d utility_manager ^
    --data-only --table=beneficiary backups\utility_manager_2026-07-12_184803.dump
```

---

## Checking a backup without restoring

List what a dump file contains:

```
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --list backups\utility_manager_2026-07-12_184803.dump
```

An empty or error-producing listing means the file is corrupt — do not rely on it.
