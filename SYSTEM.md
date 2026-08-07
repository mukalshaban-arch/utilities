# Utility Manager — System Documentation

**A quarterly utility-allocation and budget-tracking system for an organisation that
distributes money to individuals and facilities to cover utilities (power, water, mobile
airtime, office-phone airtime, fax).**

| | |
|---|---|
| Document type | System / technical reference |
| Application | Utility Manager |
| Platform | Web application (Flask + PostgreSQL) |
| Audience | Administrators, maintainers, and technical stakeholders |
| Status | Living document — update when the system materially changes |

---

## 1. Purpose & Scope

Utility Manager tracks **allocations** — money set aside each financial quarter for named
beneficiaries to cover their utility bills — and, for major facility accounts, the **actual
usage** against those allocations with a running carry-forward balance. It also tracks the
**overall budget** the administrator was given each quarter, drawing it down as allocations
are made.

The system answers questions such as:

- How much was allocated to each person/facility this quarter, and for which utility?
- How much of our quarterly budget is left?
- For a major account's water or power meter, how much was used, and what balance carries
  into the next quarter?
- Who changed what, and when? Who logged in (or failed to)?

**Out of scope:** it is not an accounting/ledger system of record for the wider organisation,
it does not process payments, and it does not integrate with utility providers.

---

## 2. Core Concepts (read this first)

Understanding five ideas makes the rest of the system obvious.

1. **Beneficiary vs. User.** A **Beneficiary** is a person or facility entitled to utility
   money (e.g. a Director, or the "HQ" major account). A **User** is a login account for
   staff who operate the system. These are deliberately separate: most beneficiaries never
   log in, and facilities (HQ, Defence, Signal…) are not people at all.

2. **Meters.** Every allocation is made against a specific **Meter** — a single meter /
   phone / account number belonging to a beneficiary. A beneficiary can hold many meters,
   even several of the same utility (e.g. two power meters, four phone numbers).

3. **Financial quarters.** The financial year runs **1 July – 30 June**:
   Q1 = Jul–Sep, Q2 = Oct–Dec, Q3 = Jan–Mar, Q4 = Apr–Jun. A financial year is labelled by
   the calendar year in which it starts (Jul 2026 – Jun 2027 is "2026"). All periods are
   stored as an explicit `(year, quarter)` pair.

4. **The carry-forward ledger (major accounts only).** For **Major-Account water and power
   meters only**, actual usage is recorded each quarter and any unspent balance carries into
   the next quarter:

   > `pool = balance carried in + this quarter's allocation`
   > `balance = pool − usage` → becomes next quarter's carry-in.

   A deficit carries as a negative balance. Ordinary staff and non-water/power utilities have
   no usage tracking and no carry-forward.

5. **The quarter budget.** The administrator records the total pool they were **given** for a
   quarter. As allocations are made, `balance = budget − total allocated` reduces. This is
   tracked and displayed but never blocks allocation.

---

## 3. User Roles & Access

The system currently has a **single login role**:

| Role | Capabilities |
|---|---|
| **admin** | Full access to every screen and action. |

- Every application page requires login; unauthenticated requests are redirected to the login
  page. Access control is enforced server-side by a `login_required` + `role_required("admin")`
  guard on the admin blueprint, so knowing a URL does not grant access.
- Beneficiaries (staff/facilities receiving money) are **not** login accounts and never sign in.
- The role model is intentionally simple; the `role_required` decorator and `ROLES` tuple make
  adding roles (e.g. a read-only "approver") straightforward later.

---

## 4. Technology Stack

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.11 |
| Web framework | Flask (application-factory pattern, blueprints) |
| ORM / DB toolkit | Flask-SQLAlchemy |
| Migrations | Flask-Migrate (Alembic) |
| Auth / sessions | Flask-Login (session cookies) |
| Forms / CSRF | Flask-WTF (global CSRF protection) |
| Database | PostgreSQL (SQLite in-memory for tests) |
| Templating | Jinja2 (server-rendered HTML) |
| Styling | Bootstrap 5.3 (CDN) + custom `app.css` |
| Charts | Chart.js (vendored locally, offline-safe) |
| PDF generation | ReportLab |
| Backups | `pg_dump` (custom/compressed format) |
| Timezone | `zoneinfo` (+ `tzdata` on Windows) |
| Tests | pytest (115 tests) |

**Design intent:** lightweight, self-contained, and deployable offline (no external CDNs or
services are required at runtime — Chart.js is vendored; Bootstrap is the only remaining CDN
asset and can be vendored the same way if needed).

---

## 5. Architecture

### 5.1 Application factory & blueprints

`create_app()` (in `app/__init__.py`) builds the Flask app, initialises extensions
(SQLAlchemy, Login, Migrate, CSRF), registers Jinja filters (`ugx`, `localtime`, `qmonths`),
a `before_request` hook that makes sessions permanent (for the idle timeout), and three
blueprints:

| Blueprint | Prefix | Responsibility |
|---|---|---|
| `auth` | `/auth` | Login, logout, keepalive ping, forgot-password / passkey reset |
| `admin` | `/admin` | Everything else — the operational core |
| `reports` | `/reports` | Quarterly allocation report (screen, CSV, PDF) |

The root path `/` requires login and redirects to the admin dashboard.

### 5.2 Request lifecycle (typical page)

1. Browser requests a page. `before_request` marks the session permanent (sliding 5-minute
   expiry).
2. `login_required` / `role_required` verify the session and role; otherwise redirect/deny.
3. The view queries the database via SQLAlchemy, computes any derived figures (ledger,
   budget balance, chart data), and renders a Jinja template extending `base.html`.
4. `base.html` provides the retractable sidebar, top bar, theme, inactivity timer, and a
   `scripts` block for page-specific JavaScript (charts read data from a JSON `<script>` tag).

### 5.3 Directory structure

```
app/
  __init__.py        create_app(), Jinja filters, CLI commands (seed, backup)
  extensions.py      db, login_manager, migrate, csrf singletons
  models.py          all 10 database models + helpers
  fiscal.py          financial-year quarter logic
  ledger.py          major-account carry-forward calculations
  queries.py         shared filter/sort logic for reports & summary
  backup.py          pg_dump wrapper (create/list/prune)
  pdf.py             reusable ReportLab table-to-PDF helper
  decorators.py      role_required
  auth/              login, logout, password reset  (routes.py, forms.py)
  admin/             the operational core            (routes.py, forms.py)
  reports/           quarterly report + exports       (routes.py)
  templates/         Jinja templates (base, _icons, _filters, admin/, auth/, reports/)
  static/            app.css, charts.js, chart.umd.min.js
config.py            configuration (env-driven)
run.py               dev entry point
migrations/          Alembic migration history (13 revisions)
tests/               pytest suite (17 files, 115 tests)
backups/             pg_dump output (gitignored)
BACKUP.md            backup & restore procedures
SYSTEM.md            this document
```

### 5.4 API / Route Reference

All routes are server-rendered or JSON endpoints on the same Flask app (there is no separate
REST API service). Endpoint names for `url_for()` are `blueprint.function`
(e.g. `admin.dashboard`, `reports.quarterly`, `auth.login`).

**Access:** every `/admin/*` and `/reports/*` route requires an authenticated **admin** session
(enforced by a blueprint-level `login_required` + `role_required("admin")` guard). Under `/auth`,
only `logout` and `ping` require login; the rest are public. Unauthenticated requests to guarded
routes redirect to the login page.

**Authentication — `auth` blueprint (`/auth`)**

| Method | Path | Function | Purpose | Returns |
|---|---|---|---|---|
| GET, POST | `/auth/login` | `login` | Sign in (with lockout + login logging) | HTML / redirect |
| GET | `/auth/logout` | `logout` | End the session | Redirect to login |
| GET | `/auth/ping` | `ping` | Session keepalive for active users | `204 No Content` |
| GET, POST | `/auth/forgot` | `forgot_password` | Request a reset (alerts the admin) | HTML / redirect |
| GET, POST | `/auth/reset` | `reset_password` | Enter the admin-issued passkey | HTML / redirect |
| GET, POST | `/auth/reset/password` | `new_password` | Set a new password after the passkey | HTML / redirect |

**Operational core — `admin` blueprint (`/admin`, admin login required)**

*Pages*

| Method | Path | Function | Purpose |
|---|---|---|---|
| GET | `/admin/` | `dashboard` | Metrics dashboard (cards, charts, recent activity) |
| GET | `/admin/beneficiaries` | `beneficiaries` | Paginated, searchable beneficiary register |
| GET, POST | `/admin/beneficiaries/new` | `new_beneficiary` | Register a beneficiary and their meters |
| GET, POST | `/admin/beneficiaries/<int:id>` | `edit_beneficiary` | Edit a beneficiary / add-remove meters |
| GET, POST | `/admin/allocations/new` | `new_allocation` | Allocate money per meter for a quarter |
| GET, POST | `/admin/budgets` | `budgets` | Set the quarter budget pool |
| GET, POST | `/admin/major-accounts` | `major_accounts` | Carry-forward ledger + record usage |
| GET | `/admin/summary` | `summary` | Allocation totals + distribution charts |
| GET | `/admin/activity` | `activity` | Activity (audit) log |
| GET | `/admin/logins` | `logins` | Login log |
| GET | `/admin/password-resets` | `password_resets` | Password-reset request queue |
| GET, POST | `/admin/users/new` | `new_user` | Create a login user |
| GET, POST | `/admin/utility-types/new` | `new_utility_type` | Add a utility type |
| GET | `/admin/backups` | `backups` | Backup list + "Back Up Now" |

*Actions (POST) & file downloads*

| Method | Path | Function | Purpose | Returns |
|---|---|---|---|---|
| POST | `/admin/backups/create` | `create_backup_now` | Run a backup immediately | Redirect |
| GET | `/admin/backups/<name>/download` | `download_backup` | Download a backup (path-traversal safe) | File |
| POST | `/admin/password-resets/<int:id>/issue` | `issue_passkey` | Issue a one-time passkey | Redirect |
| POST | `/admin/password-resets/<int:id>/cancel` | `cancel_passkey` | Cancel a reset request | Redirect |

*Data / AJAX endpoints (JSON) — used by the allocation form*

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/admin/beneficiaries/search` | `q` | Up to 10 matches: `[{id, name, label, position}]` |
| GET | `/admin/beneficiaries/<int:id>/meters` | `quarter, year` | `[{id, utility, number, amount, carry_forward}]` |
| GET | `/admin/budget-remaining` | `quarter, year` | `{has_budget, budget, allocated, remaining}` |

*Ledger exports*

| Method | Path | Function | Returns |
|---|---|---|---|
| GET | `/admin/major-accounts/report.csv` | `major_accounts_csv` | `text/csv` |
| GET | `/admin/major-accounts/report.pdf` | `major_accounts_pdf` | `application/pdf` |

**Reports — `reports` blueprint (`/reports`, login required)**

| Method | Path | Function | Returns |
|---|---|---|---|
| GET | `/reports/quarterly` | `quarterly` | HTML report |
| GET | `/reports/quarterly.csv` | `quarterly_csv` | `text/csv` |
| GET | `/reports/quarterly.pdf` | `quarterly_pdf` | `application/pdf` |

**Common filter query parameters** (reports, summary, and ledger pages/exports):

| Param | Applies to | Meaning |
|---|---|---|
| `year` | all | Financial year (see §2). |
| `quarter` | all | 1–4; on reports/ledger `0` means **all quarters**. |
| `utility_type_id` | reports, summary | Filter to one utility type. |
| `utility` | ledger | Filter to a utility by name (Power/Water). |
| `account` | ledger | Filter to one major-account beneficiary id. |
| `position` | reports, summary | Filter by beneficiary position. |
| `name` | reports, summary, register | Case-insensitive name search. |
| `sort`, `direction` | reports, summary | Column key + `asc`/`desc`. |
| `page` | register, activity, logins | Pagination (50 rows/page). |

All state-changing requests (POST) require a valid **CSRF token** (Flask-WTF); forms include it
automatically and the AJAX GET endpoints above are read-only.

---

## 6. Data Model

Ten tables. Money is stored as `Numeric` (exact decimal), timestamps as naive UTC.

### 6.1 Entities

**User** — a login account.
`id, name, email (unique), password_hash, role`. Passwords are hashed (Werkzeug PBKDF2);
plaintext is never stored.

**Beneficiary** — a person or facility entitled to utility money.
`id, name (unique), position, facility, department`.
- `position` ∈ {Major Accounts, Director, Deputy Director, Section Head, Other}.
- **Major Accounts** carry a `facility` (HQ, Rubaga House, Defence, Signal, Katonga, Jumbo,
  Mbarara, Kabale, Arua, DG, DDG); all other positions carry a `department`
  (DAF, DIC, DIA, DDI, DTI, DLP). The two are mutually exclusive.

**Meter** — one meter / phone / account number belonging to a beneficiary.
`id, beneficiary_id, utility_type_id, number`. Unique on `(utility_type_id, number)`.

**UtilityType** — the kinds of utility. Seeded: Power, Water, Mobile Airtime,
Office Phone Airtime, Fax. Admin can add more.

**Allocation** — money allocated to a meter for a period.
`id, meter_id, quarter, year, amount, created_by_id`. Unique on `(meter_id, quarter, year)` —
one allocation per meter per quarter; re-saving updates it.

**Usage** — actual bill recorded against a meter for a period (major-account water/power only).
`id, meter_id, quarter, year, amount, created_by_id`. Unique on `(meter_id, quarter, year)`.

**QuarterBudget** — the total pool given to the admin for a quarter.
`id, quarter, year, amount, created_by_id, updated_at`. Unique on `(quarter, year)`.

**ActivityLog** — append-only audit of operational actions.
`id, created_at, user_id, action, beneficiary_name, unit, utility, number, quarter, year,
amount, previous_amount`. Details are **snapshotted as text** so an entry still reads correctly
after a beneficiary is renamed or a meter number changes.

**LoginLog** — every sign-in attempt.
`id, created_at, email, user_id (nullable), success, ip_address, attempts, blocked`.

**PasswordResetRequest** — an admin-mediated password reset.
`id, user_id, status, requested_at, passkey_hash, issued_at, issued_by_id, expires_at, used_at`.
Only the **hash** of the temporary passkey is stored.

### 6.2 Relationships (text ERD)

```
User 1───* Allocation.created_by / Usage.created_by / ActivityLog / LoginLog / PasswordResetRequest
Beneficiary 1───* Meter
UtilityType 1───* Meter
Meter 1───* Allocation
Meter 1───* Usage
(QuarterBudget stands alone, keyed by quarter+year)
```

The register (Beneficiary/Meter) is separate from login (User) — see §2.

---

## 7. Functional Modules

### 7.1 Authentication & session (`auth`)
- **Login** with email + password. Generic error messages (no account enumeration).
- **Account lockout**: 4 failed attempts locks the account for 10 minutes; blocked attempts
  are logged but do not extend the lockout; a success resets the counter.
- **Login log** records who got in, who failed, attempt counts, and IP.
- **Inactivity timeout**: 5 minutes idle → automatic logout and redirect to login (client
  timer + server-side sliding session expiry + a keepalive `/auth/ping` for active users).
- **Password reset** is admin-mediated: the user requests a reset → the admin is alerted and
  issues a one-time **passkey** (shown once, only its hash stored, 60-minute expiry) → the user
  enters the passkey and sets a new password.

### 7.2 Beneficiary register (`admin`)
- **Register / edit** beneficiaries with position, facility/department, and any number of
  meters (add, rename, or remove numbers; meters with allocations are protected from deletion).
- **Paginated, searchable list** (50/page) filterable by name, position, and facility —
  designed to scale to hundreds of beneficiaries.
- **Type-ahead search endpoints** power the allocation form without embedding the whole
  register in the page.

### 7.3 Allocations (`admin`)
- **New Allocation** form: type a beneficiary name → pick from suggestions → their registered
  meters auto-populate, each with an amount field (pre-filled with any existing allocation for
  the chosen quarter/year). Blank means "leave unchanged".
- For **major-account water/power** meters, the form shows the **carried-forward balance** and
  a live **new total pool**.
- A **live remaining-budget** banner shows `budget − allocated` for the selected quarter and
  draws down as amounts are typed. It is **display-only and never blocks** allocation
  (over-budget shows red).
- Only figures that actually change are written and logged.

### 7.4 Quarter budgets (`admin`)
- **Budgets page**: enter the total given for each quarter of a year; see Budget / Allocated /
  Balance per quarter with a yearly total. Blank leaves a quarter unchanged; changes are logged.
- Two **dashboard cards** show the current quarter's budget and balance.

### 7.5 Major Accounts ledger (`admin`)
- **Record usage** (one figure per meter per quarter) for major-account water/power meters.
- View the full ledger per meter: **carried-in, allocation, pool, usage, balance**.
- **Quarter selector** including an **"All"** mode that shows the Q1–Q4 progression for a year.
- **Charts**: a quarterly trend (allocation/usage/balance) and usage-by-utility.
- **Report exports** (CSV & PDF) honouring account/utility/quarter filters, with allocation,
  usage, and current-standing balance totals.

### 7.6 Reports & summary (`reports`, `admin`)
- **Quarterly allocation report** (`/reports/quarterly`): one row per allocated meter, filter
  by quarter/year/utility/position/name, sortable columns, **CSV & PDF export**. "All quarters"
  spans the year.
- **Allocation summary** (`/admin/summary`): totals and distribution by utility and by
  beneficiary, with **charts**, respecting the same filters.

### 7.7 Dashboard (`admin`)
Decision-maker landing page: stat cards (quarter budget, budget balance, beneficiaries,
allocated-this-year, usage-this-year, outstanding carry-forward standing), an allocation-by-
utility doughnut, an allocation-by-quarter bar, and a recent-activity feed.

### 7.8 Audit & administration (`admin`)
- **Activity log**: append-only, searchable/filterable record of allocations, usage, budget
  changes, beneficiary edits, and report generation — with before→after amounts.
- **Login log**: sign-in audit (see §7.1).
- **Password resets**: queue of requests; issue or cancel passkeys.
- **Backups**: create/download database backups; scheduled backups via CLI.
- **User & utility-type creation**.

---

## 8. Key Business Rules

| Rule | Detail |
|---|---|
| Financial quarters | Q1 Jul–Sep, Q2 Oct–Dec, Q3 Jan–Mar, Q4 Apr–Jun; FY labelled by start year. (`app/fiscal.py`) |
| One allocation per meter/quarter | Re-saving updates the amount; the change (with previous value) is logged. |
| Carry-forward (MA water/power) | `pool = carry_in + allocation`; `balance = pool − usage`; balance carries forward, deficits included. Computed live from history — never stored — so figures cannot drift. (`app/ledger.py`) |
| Budget balance | `balance = quarter budget − sum of that quarter's allocations`. Tracked, displayed, non-blocking. |
| Usage scope | Only Major-Account meters whose utility is Power or Water. Everything else is allocation-only. |
| Lockout | 4 fails → 10-minute lock; success resets; blocked attempts don't extend it. |
| Session | 5-minute idle timeout (configurable via `SESSION_TIMEOUT_MINUTES`). |
| Money | Exact `Numeric`; displayed as `UGX 1,234,567` (whole shillings). |
| Time | Stored UTC; displayed in `TIMEZONE` (default Africa/Kampala). |

---

## 9. Security

**Implemented controls** (verified in a security review against the OWASP Top 10):

- Access control on every admin page (login + role).
- Parameterised ORM queries (no SQL injection) and Jinja auto-escaping (no stored XSS).
- Global CSRF protection on all forms (Flask-WTF).
- Passwords and reset passkeys hashed (Werkzeug PBKDF2); only hashes stored.
- Brute-force lockout; no account enumeration; login attempts logged.
- Session cookie is HttpOnly; 5-minute idle expiry (client + server).
- Backup downloads are admin-only and path-traversal-safe.
- Append-only activity and login audit trails.
- No SSRF/command-injection vectors (backup uses an argument list, password via environment).
- Credential fields set `autocomplete="off"`.

**Known hardening items for production** (from the security assessment — see
`Security_Assessment_Report.pdf`):

- Run under a production WSGI server with **debug off** (do not use `run.py`/the dev server in
  production).
- Set a strong random `SECRET_KEY`; serve over **HTTPS** with Secure/SameSite cookies + HSTS.
- Add HTTP security headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy).
- Enforce a password-strength policy on admin-created accounts.
- Keep dependencies patched (Flask, python-dotenv, tooling).

---

## 10. Configuration

All configuration is environment-driven (`config.py`), typically via a `.env` file:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev` | Session signing key — **must** be set to a strong random value in production. |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/utility_manager` | PostgreSQL connection string. |
| `TIMEZONE` | `Africa/Kampala` | Display timezone (storage is UTC). |
| `SESSION_TIMEOUT_MINUTES` | `5` | Idle logout period. |
| `BACKUP_DIR` | `./backups` | Where `pg_dump` writes backups. |
| `PG_DUMP` | auto-detected | Path to `pg_dump.exe` if not on PATH. |

`TestConfig` overrides the database to in-memory SQLite and disables CSRF for the test suite.

---

## 11. Database & Migrations

- Schema changes are managed with **Flask-Migrate / Alembic** (13 revisions to date).
- Apply migrations with `flask db upgrade`; generate new ones with `flask db migrate -m "…"`
  (always review the generated file before applying).
- The `flask seed` CLI command seeds the standard utility types and a first admin user.
- **Always take a backup before running a migration** (see §12).

---

## 12. Backup & Restore

- **On demand:** Admin → Backups → "Back Up Now" (downloadable), or `flask backup`.
- **Scheduled:** `flask backup --keep 30` via Windows Task Scheduler (`launch.bat` / see
  `BACKUP.md`), which writes a dated dump and prunes old ones.
- Backups use `pg_dump` custom format (compressed, selectively restorable with `pg_restore`).
- **Restore:** documented in `BACKUP.md`. The recommended path is to restore into a **new**
  database first and verify before overwriting production. Restore is intentionally **not** a
  web action (too destructive).
- **Store backups off the machine** — a backup on the same disk as the database does not
  survive that disk failing.

---

## 13. Running the System

**Development**
```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
# create .env with SECRET_KEY and DATABASE_URL
flask db upgrade
flask seed                 # first admin: admin@example.com / admin123
python run.py              # http://127.0.0.1:5000
```

**Kiosk/clean window** (hide the browser address bar): `launch.bat` opens the app in Chrome/
Edge app mode. See §9 for production-server guidance before real deployment.

---

## 14. Testing

- **115 automated tests** across 17 files (`tests/`), run with `pytest`.
- Coverage spans authentication/lockout, session timeout, the beneficiary register, allocations,
  budgets, the carry-forward ledger, financial-quarter logic, reports/exports, filtering/sorting,
  audit and login logging, password reset, and backups.
- Tests run against in-memory SQLite for speed and isolation.
- **Run before every change:** `venv\Scripts\python -m pytest -q`.

---

## 15. Operational Notes & Known Limitations

- **Single admin role** — no separation of duties yet; every operator can do everything.
- **Budget is tracking-only** — the system warns but never prevents over-allocation.
- **Editing history re-flows the ledger.** Because carry-forward is computed live, correcting an
  old quarter's usage automatically changes every later quarter's balance — usually desired, but
  be aware.
- **Financial-year label is the start year** (2026 = Jul 2026–Jun 2027). If the organisation
  labels years differently, this is a one-line change in `app/fiscal.py`.
- **Deployment hardening is pending** (see §9) — the current build is developer-configured.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| Allocation | Money assigned to a meter for a quarter. |
| Beneficiary | A person or facility entitled to utility money (not a login). |
| Carry-forward | Unspent (or overspent) balance moved to the next quarter, for MA water/power. |
| Financial quarter | Q1 Jul–Sep, Q2 Oct–Dec, Q3 Jan–Mar, Q4 Apr–Jun. |
| Major Account | A facility-type beneficiary (HQ, Defence…) with a facility instead of a department. |
| Meter | A single meter / phone / account number belonging to a beneficiary. |
| Pool | Carried-in balance + this quarter's allocation (spendable amount for a meter). |
| Quarter budget | The total the admin was given to allocate in a quarter. |
| Usage | Actual bill recorded against a major-account water/power meter. |

---

*End of document. This reflects the system as built; regenerate the routes/models/migration/test
figures if the codebase changes materially.*
