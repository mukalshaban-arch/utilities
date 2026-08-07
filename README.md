# Utility Manager

[![Tests](https://github.com/mukalshaban-arch/utilities/actions/workflows/tests.yml/badge.svg)](https://github.com/mukalshaban-arch/utilities/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/badge/coverage-report-informational)](https://github.com/mukalshaban-arch/utilities/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-unlicensed-lightgrey)](#)

A quarterly utility-allocation and budget-tracking system for an organisation that distributes
money to individuals and facilities to cover utilities — power, water, mobile airtime, office
phone airtime, and fax.

---

## What it does

- **Tracks allocations.** Each financial quarter, money is set aside per meter/phone number for
  a named beneficiary (staff or a "Major Account" facility like HQ or a regional office).
- **Tracks usage and carry-forward** for Major-Account water and power meters — unspent balance
  rolls into the next quarter, and a deficit carries forward too.
- **Tracks the overall budget.** The admin records what they were given each quarter; the
  balance draws down automatically as allocations are made (display-only — it never blocks).
- **Reports and exports.** Filterable, sortable reports and dashboards with charts, exportable
  as CSV and PDF.
- **Keeps an audit trail.** Every allocation, budget change, and login attempt is logged.

Financial quarters follow **1 July – 30 June** (Q1 = Jul–Sep … Q4 = Apr–Jun), not the calendar
year.

## Key features

| Area | What's there |
|---|---|
| Beneficiary register | People and facilities, each with any number of meters/phone numbers |
| Allocations | Type-ahead beneficiary search, per-meter amounts, live remaining-budget readout |
| Major Accounts ledger | Carry-forward balance per meter, usage entry, quarterly trend charts |
| Quarter budgets | Set the pool given per quarter; balance tracked automatically |
| Reports | Quarterly allocation report — filter by quarter/utility/position/name, CSV & PDF export |
| Dashboard | Stat cards, allocation charts, recent-activity feed |
| Security | Login lockout after failed attempts, 5-minute inactivity timeout, CSRF protection, hashed passwords, admin-mediated password reset |
| Audit | Append-only activity log and login log |
| Backups | On-demand and scheduled PostgreSQL backups (`pg_dump`), with a documented restore procedure |
| UI | Retractable sidebar, light/dark mode, charts (Chart.js, vendored — works offline) |

## Tech stack

Python 3.11 · Flask (application factory + blueprints) · PostgreSQL · SQLAlchemy · Flask-Migrate
(Alembic) · Flask-Login · Flask-WTF (CSRF) · Jinja2 · Bootstrap 5 · Chart.js · ReportLab (PDF) ·
pytest (115 tests, in-memory SQLite).

See **[SYSTEM.md](SYSTEM.md)** for full architecture, the data model, and a complete API/route
reference — the right place to start if you're a developer picking this up.

## Getting started

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt      # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

# create a .env file (see .env.example) with SECRET_KEY and DATABASE_URL

flask db upgrade
flask seed                 # creates the first admin: admin@example.com / admin123
python run.py               # http://127.0.0.1:5000
```

## Running the tests

```bash
pytest -q
```

115 tests, no external services required (they run against an in-memory SQLite database).
Tests run automatically on every push and pull request via GitHub Actions
(`.github/workflows/tests.yml`).

## Documentation

| Document | Contents |
|---|---|
| [SYSTEM.md](SYSTEM.md) | Architecture, data model, business rules, full route/API reference |
| [BACKUP.md](BACKUP.md) | Backup scheduling and restore procedures |

## Project status

Actively developed. Before production deployment, review the security-hardening checklist in
`SYSTEM.md` (production WSGI server, HTTPS, security headers) — the current build is configured
for development.
