import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    send_file,
    abort,
    Response,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app.extensions import db
from app.decorators import role_required
from app.backup import list_backups, create_backup, BackupError
from app.models import (
    MAJOR_ACCOUNTS,
    POSITIONS,
    FACILITIES,
    DEPARTMENTS,
    User,
    UtilityType,
    Beneficiary,
    Meter,
    Allocation,
    Usage,
    QuarterBudget,
    ActivityLog,
    LoginLog,
    PasswordResetRequest,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_MINUTES,
    PASSKEY_EXPIRY_MINUTES,
    CARRYFORWARD_UTILITIES,
    is_carryforward_meter,
    log_activity,
)
from app.ledger import carry_in, meter_ledger
from app.pdf import table_pdf
from app.fiscal import current_period
from app.admin.forms import UserForm, UtilityTypeForm
from app.queries import (
    parse_filters,
    allocation_query,
    matching_utility_types,
    matching_beneficiaries,
    period_label,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@login_required
@role_required("admin")
def restrict_to_admin():
    pass


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


@admin_bp.route("/beneficiaries/search")
def search_beneficiaries():
    """Type-ahead lookup. Returns at most 10 matches so the register can grow freely."""
    term = (request.args.get("q") or "").strip()
    if not term:
        return jsonify([])

    matches = (
        Beneficiary.query.filter(Beneficiary.name.ilike(f"%{term}%"))
        .order_by(Beneficiary.name)
        .limit(10)
        .all()
    )
    return jsonify([{"id": b.id, "name": b.name, "label": b.label, "position": b.position} for b in matches])


@admin_bp.route("/beneficiaries/<int:beneficiary_id>/meters")
def beneficiary_meters(beneficiary_id):
    """The beneficiary's numbers, with any amount already allocated for the period."""
    beneficiary = Beneficiary.query.get_or_404(beneficiary_id)
    quarter = request.args.get("quarter", type=int)
    year = request.args.get("year", type=int)

    allocated = {}
    if quarter and year:
        allocated = {
            a.meter_id: str(a.amount)
            for a in Allocation.query.join(Meter)
            .filter(
                Meter.beneficiary_id == beneficiary.id,
                Allocation.quarter == quarter,
                Allocation.year == year,
            )
            .all()
        }

    meters = []
    for m in beneficiary.meters:
        # Carry-forward only applies to Major-Account water/power meters.
        carry = (
            str(carry_in(m.id, year, quarter)) if (quarter and year and is_carryforward_meter(m)) else None
        )
        meters.append(
            {
                "id": m.id,
                "utility": m.utility_type.name,
                "number": m.number,
                "amount": allocated.get(m.id, ""),
                "carry_forward": carry,
            }
        )
    return jsonify(meters)


def parse_meter_rows():
    """Read the repeating meter rows off a beneficiary form."""
    ids = request.form.getlist("meter_id")
    utilities = request.form.getlist("meter_utility")
    numbers = request.form.getlist("meter_number")

    rows = []
    # strict=False: these lists come straight from form data and may legitimately
    # be uneven if a row was only partially filled in.
    for meter_id, utility_type_id, number in zip(ids, utilities, numbers, strict=False):
        number = number.strip()
        if not number:
            continue
        rows.append(
            {
                "id": int(meter_id) if meter_id else None,
                "utility_type_id": int(utility_type_id),
                "number": number,
            }
        )
    return rows


def read_beneficiary_fields():
    """Validate the scalar beneficiary fields. Returns (values, error)."""
    name = request.form.get("name", "").strip()
    position = request.form.get("position", "")
    facility = request.form.get("facility") or None
    department = request.form.get("department") or None

    if not name:
        return None, "Name is required."
    if position not in POSITIONS:
        return None, "Select a valid position."

    # Major Accounts sit in a facility; everyone else sits in a department.
    if position == MAJOR_ACCOUNTS:
        if facility not in FACILITIES:
            return None, "Major Accounts must have a facility."
        department = None
    else:
        if department not in DEPARTMENTS:
            return None, "Select a department."
        facility = None

    return {
        "name": name,
        "position": position,
        "facility": facility,
        "department": department,
    }, None


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@admin_bp.route("/")
def dashboard():
    year, quarter = current_period()
    budget = quarter_budget_summary(year, quarter)

    allocated_year = (
        db.session.query(db.func.coalesce(db.func.sum(Allocation.amount), 0))
        .filter(Allocation.year == year)
        .scalar()
    )
    usage_year = (
        db.session.query(db.func.coalesce(db.func.sum(Usage.amount), 0)).filter(Usage.year == year).scalar()
    )

    # Current outstanding standing across Major-Account water/power meters.
    ma_groups = filter_major_account_groups()
    outstanding = sum((meter_ledger(m.id, year, 4)["balance"] for _, meters in ma_groups for m in meters), 0)

    # Allocation split by utility this year (for the doughnut).
    utility_split = (
        db.session.query(UtilityType.name, db.func.sum(Allocation.amount))
        .join(Meter, Allocation.meter_id == Meter.id)
        .join(UtilityType, Meter.utility_type_id == UtilityType.id)
        .filter(Allocation.year == year)
        .group_by(UtilityType.name)
        .order_by(UtilityType.name)
        .all()
    )
    # Allocation per quarter this year (for the trend bar).
    quarter_split = dict(
        db.session.query(Allocation.quarter, db.func.sum(Allocation.amount))
        .filter(Allocation.year == year)
        .group_by(Allocation.quarter)
        .all()
    )

    charts = {
        "utility": {
            "labels": [name for name, total in utility_split],
            "values": [float(total) for name, total in utility_split],
        },
        "quarters": {
            "labels": [f"Q{q}" for q in (1, 2, 3, 4)],
            "values": [float(quarter_split.get(q, 0)) for q in (1, 2, 3, 4)],
        },
    }

    recent = (
        ActivityLog.query.options(selectinload(ActivityLog.user))
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        year=year,
        quarter=quarter,
        quarter_budget=budget["budget"],
        quarter_balance=budget["balance"],
        beneficiary_count=Beneficiary.query.count(),
        major_account_count=Beneficiary.query.filter_by(position=MAJOR_ACCOUNTS).count(),
        allocation_count=Allocation.query.count(),
        allocated_year=allocated_year,
        usage_year=usage_year,
        outstanding=outstanding,
        pending_resets=PasswordResetRequest.query.filter_by(status="pending").count(),
        charts=charts,
        recent=recent,
    )


@admin_bp.route("/activity")
def activity():
    """Append-only system activity log, newest first."""
    name = (request.args.get("name") or "").strip()
    action = (request.args.get("action") or "").strip()

    query = ActivityLog.query.options(selectinload(ActivityLog.user))
    if name:
        query = query.filter(ActivityLog.beneficiary_name.ilike(f"%{name}%"))
    if action:
        query = query.filter(ActivityLog.action == action)

    pagination = query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=50, error_out=False
    )
    actions = [row[0] for row in db.session.query(ActivityLog.action).distinct().order_by(ActivityLog.action)]

    return render_template(
        "admin/activity.html",
        pagination=pagination,
        actions=actions,
        name=name,
        action=action,
    )


@admin_bp.route("/backups")
def backups():
    return render_template(
        "admin/backups.html",
        backups=list_backups(),
        backup_dir=current_app.config["BACKUP_DIR"],
    )


@admin_bp.route("/backups/create", methods=["POST"])
def create_backup_now():
    try:
        target = create_backup()
    except BackupError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.backups"))

    log_activity(current_user, "Created backup")
    db.session.commit()

    size_mb = target.stat().st_size / 1024 / 1024
    flash(f"Backup created: {target.name} ({size_mb:.2f} MB).", "success")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/<name>/download")
def download_backup(name):
    # Resolve inside the backup directory so a crafted name cannot escape it.
    directory = Path(current_app.config["BACKUP_DIR"]).resolve()
    target = (directory / secure_filename(name)).resolve()
    if target.parent != directory or not target.is_file():
        abort(404)

    log_activity(current_user, "Downloaded backup")
    db.session.commit()
    return send_file(target, as_attachment=True, download_name=target.name)


@admin_bp.route("/password-resets")
def password_resets():
    requests_ = (
        PasswordResetRequest.query.options(selectinload(PasswordResetRequest.user))
        .order_by(PasswordResetRequest.requested_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "admin/password_resets.html",
        requests=requests_,
        expiry_minutes=PASSKEY_EXPIRY_MINUTES,
    )


@admin_bp.route("/password-resets/<int:request_id>/issue", methods=["POST"])
def issue_passkey(request_id):
    reset = PasswordResetRequest.query.get_or_404(request_id)
    if reset.status == "used":
        flash("That request has already been used.", "danger")
        return redirect(url_for("admin.password_resets"))

    passkey = reset.issue(current_user)
    log_activity(current_user, "Issued reset passkey")
    db.session.commit()

    # Shown once. Only the hash is stored, so it cannot be looked up again.
    flash(
        f"Passkey for {reset.user.name} ({reset.user.email}): {passkey} — "
        f"give this to them directly. It expires in {PASSKEY_EXPIRY_MINUTES} minutes "
        f"and is shown only once.",
        "success",
    )
    return redirect(url_for("admin.password_resets"))


@admin_bp.route("/password-resets/<int:request_id>/cancel", methods=["POST"])
def cancel_passkey(request_id):
    reset = PasswordResetRequest.query.get_or_404(request_id)
    reset.status = "cancelled"
    log_activity(current_user, "Cancelled reset request")
    db.session.commit()
    flash("Request cancelled.", "info")
    return redirect(url_for("admin.password_resets"))


@admin_bp.route("/logins")
def logins():
    """Sign-in audit: who got in, who failed, and how many tries it took."""
    email = (request.args.get("email") or "").strip()
    result = (request.args.get("result") or "").strip()

    query = LoginLog.query.options(selectinload(LoginLog.user))
    if email:
        query = query.filter(LoginLog.email.ilike(f"%{email}%"))
    if result == "success":
        query = query.filter(LoginLog.success.is_(True))
    elif result == "failed":
        query = query.filter(LoginLog.success.is_(False), LoginLog.blocked.is_(False))
    elif result == "blocked":
        query = query.filter(LoginLog.blocked.is_(True))

    pagination = query.order_by(LoginLog.created_at.desc(), LoginLog.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=50, error_out=False
    )

    return render_template(
        "admin/logins.html",
        pagination=pagination,
        email=email,
        result=result,
        max_attempts=MAX_LOGIN_ATTEMPTS,
        lockout_minutes=LOCKOUT_MINUTES,
        successes=LoginLog.query.filter_by(success=True).count(),
        failures=LoginLog.query.filter_by(success=False, blocked=False).count(),
        lockouts=LoginLog.query.filter_by(blocked=True).count(),
    )


@admin_bp.route("/beneficiaries")
def beneficiaries():
    """Paginated register - there may be hundreds, so never load them all at once."""
    name = (request.args.get("name") or "").strip()
    position = (request.args.get("position") or "").strip()
    facility = (request.args.get("facility") or "").strip()
    department = (request.args.get("department") or "").strip()

    query = Beneficiary.query.options(selectinload(Beneficiary.meters).selectinload(Meter.utility_type))
    if name:
        query = query.filter(Beneficiary.name.ilike(f"%{name}%"))
    if position:
        query = query.filter(Beneficiary.position == position)
    if facility:
        query = query.filter(Beneficiary.facility == facility)
    if department:
        query = query.filter(Beneficiary.department == department)

    pagination = query.order_by(Beneficiary.name).paginate(
        page=request.args.get("page", 1, type=int), per_page=50, error_out=False
    )

    return render_template(
        "admin/beneficiaries.html",
        pagination=pagination,
        positions=POSITIONS,
        facilities=FACILITIES,
        departments=DEPARTMENTS,
        name=name,
        position=position,
        facility=facility,
        department=department,
    )


# --------------------------------------------------------------------------
# Beneficiary register
# --------------------------------------------------------------------------


@admin_bp.route("/beneficiaries/new", methods=["GET", "POST"])
def new_beneficiary():
    utility_types = UtilityType.query.order_by(UtilityType.name).all()

    if request.method == "POST":
        values, error = read_beneficiary_fields()
        if error:
            flash(error, "danger")
        elif Beneficiary.query.filter_by(name=values["name"]).first():
            flash("A beneficiary with that name is already registered.", "danger")
        else:
            beneficiary = Beneficiary(**values)
            for row in parse_meter_rows():
                beneficiary.meters.append(Meter(utility_type_id=row["utility_type_id"], number=row["number"]))
            db.session.add(beneficiary)
            db.session.flush()
            log_activity(current_user, "Registered beneficiary", beneficiary)
            try:
                db.session.commit()
                flash(f"{beneficiary.name} registered.", "success")
                return redirect(url_for("admin.edit_beneficiary", beneficiary_id=beneficiary.id))
            except IntegrityError:
                db.session.rollback()
                flash("One of those meter numbers is already registered.", "danger")

    return render_template(
        "admin/beneficiary_form.html",
        beneficiary=None,
        utility_types=utility_types,
        positions=POSITIONS,
        facilities=FACILITIES,
        departments=DEPARTMENTS,
        major_accounts=MAJOR_ACCOUNTS,
    )


@admin_bp.route("/beneficiaries/<int:beneficiary_id>", methods=["GET", "POST"])
def edit_beneficiary(beneficiary_id):
    beneficiary = Beneficiary.query.get_or_404(beneficiary_id)
    utility_types = UtilityType.query.order_by(UtilityType.name).all()

    if request.method == "POST":
        values, error = read_beneficiary_fields()
        clash = Beneficiary.query.filter(
            Beneficiary.name == (values or {}).get("name"), Beneficiary.id != beneficiary.id
        ).first()

        if error:
            flash(error, "danger")
        elif clash:
            flash("Another beneficiary already has that name.", "danger")
        else:
            beneficiary.name = values["name"]
            beneficiary.position = values["position"]
            beneficiary.facility = values["facility"]
            beneficiary.department = values["department"]

            rows = parse_meter_rows()
            kept = {row["id"] for row in rows if row["id"]}

            # Meters dropped from the form are removed, unless they carry history.
            for meter in list(beneficiary.meters):
                if meter.id not in kept:
                    if meter_in_use(meter.id):
                        flash(
                            f"Meter {meter.number} has allocations or expenses and was kept.",
                            "warning",
                        )
                        continue
                    db.session.delete(meter)

            existing = {m.id: m for m in beneficiary.meters}
            for row in rows:
                if row["id"] and row["id"] in existing:
                    meter = existing[row["id"]]
                    meter.number = row["number"]
                    meter.utility_type_id = row["utility_type_id"]
                else:
                    beneficiary.meters.append(
                        Meter(utility_type_id=row["utility_type_id"], number=row["number"])
                    )

            log_activity(current_user, "Updated beneficiary", beneficiary)
            try:
                db.session.commit()
                flash("Beneficiary updated.", "success")
                return redirect(url_for("admin.edit_beneficiary", beneficiary_id=beneficiary.id))
            except IntegrityError:
                db.session.rollback()
                flash("One of those meter numbers is already registered.", "danger")

    return render_template(
        "admin/beneficiary_form.html",
        beneficiary=beneficiary,
        utility_types=utility_types,
        positions=POSITIONS,
        facilities=FACILITIES,
        departments=DEPARTMENTS,
        major_accounts=MAJOR_ACCOUNTS,
    )


def meter_in_use(meter_id):
    return bool(Allocation.query.filter_by(meter_id=meter_id).first())


# --------------------------------------------------------------------------
# Quarter budget: the pool the admin allocates from
# --------------------------------------------------------------------------


def quarter_allocated(year, quarter):
    """Total allocated across all meters for a quarter."""
    return (
        db.session.query(db.func.coalesce(db.func.sum(Allocation.amount), 0))
        .filter(Allocation.year == year, Allocation.quarter == quarter)
        .scalar()
    )


def quarter_budget_summary(year, quarter):
    """Budget, allocated, and remaining balance for one quarter."""
    budget = QuarterBudget.query.filter_by(year=year, quarter=quarter).first()
    amount = budget.amount if budget else 0
    allocated = quarter_allocated(year, quarter)
    return {"budget": amount, "allocated": allocated, "balance": amount - allocated}


@admin_bp.route("/budget-remaining")
def budget_remaining():
    """Live budget figures for the allocation form (display only, never blocks)."""
    year = request.args.get("year", type=int)
    quarter = request.args.get("quarter", type=int)
    if not year or quarter not in (1, 2, 3, 4):
        return jsonify({"has_budget": False, "budget": 0, "allocated": 0, "remaining": 0})

    summary = quarter_budget_summary(year, quarter)
    has_budget = QuarterBudget.query.filter_by(year=year, quarter=quarter).first() is not None
    return jsonify(
        {
            "has_budget": has_budget,
            "budget": float(summary["budget"]),
            "allocated": float(summary["allocated"]),
            "remaining": float(summary["balance"]),
        }
    )


@admin_bp.route("/budgets", methods=["GET", "POST"])
def budgets():
    if request.method == "POST":
        year = request.form.get("year", type=int)
    else:
        year = request.args.get("year", current_period()[0], type=int)

    if request.method == "POST":
        if not year:
            flash("Select a valid year.", "danger")
        else:
            saved, error = save_budgets(year)
            if error:
                flash(error, "danger")
            elif saved:
                flash(f"Saved {saved} quarter budget(s) for {year}.", "success")
            else:
                flash("No budgets were changed.", "info")
            return redirect(url_for("admin.budgets", year=year))

    rows = []
    for quarter in (1, 2, 3, 4):
        summary = quarter_budget_summary(year, quarter)
        rows.append({"quarter": quarter, **summary})

    return render_template(
        "admin/budgets.html",
        year=year,
        rows=rows,
        total_budget=sum((r["budget"] for r in rows), 0),
        total_allocated=sum((r["allocated"] for r in rows), 0),
        total_balance=sum((r["balance"] for r in rows), 0),
    )


def save_budgets(year):
    """Upsert one budget figure per quarter. Blank leaves it unchanged."""
    changed = 0
    for quarter in (1, 2, 3, 4):
        raw = request.form.get(f"budget_{quarter}", "").strip()
        if raw == "":
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return 0, f"'{raw}' is not a valid amount."
        if amount < 0:
            return 0, "Budget cannot be negative."

        budget = QuarterBudget.query.filter_by(year=year, quarter=quarter).first()
        if budget is None:
            db.session.add(
                QuarterBudget(year=year, quarter=quarter, amount=amount, created_by_id=current_user.id)
            )
            log_activity(current_user, "Set quarter budget", quarter=quarter, year=year, amount=amount)
            changed += 1
        elif budget.amount != amount:
            previous = budget.amount
            budget.amount = amount
            log_activity(
                current_user,
                "Updated quarter budget",
                quarter=quarter,
                year=year,
                amount=amount,
                previous_amount=previous,
            )
            changed += 1

    if changed:
        db.session.commit()
    return changed, None


# --------------------------------------------------------------------------
# Major Accounts: usage & carry-forward ledger (water/power only)
# --------------------------------------------------------------------------


def eligible_major_account_meters():
    """Water/power meters belonging to Major Accounts, grouped by beneficiary."""
    beneficiaries = (
        Beneficiary.query.filter_by(position=MAJOR_ACCOUNTS)
        .options(selectinload(Beneficiary.meters).selectinload(Meter.utility_type))
        .order_by(Beneficiary.name)
        .all()
    )
    groups = []
    for beneficiary in beneficiaries:
        meters = [m for m in beneficiary.meters if is_carryforward_meter(m)]
        if meters:
            groups.append((beneficiary, meters))
    return groups


def filter_major_account_groups(account_id=None, utility=None):
    """Eligible meters narrowed to one account and/or one utility."""
    groups = []
    for beneficiary, meters in eligible_major_account_meters():
        if account_id and beneficiary.id != account_id:
            continue
        meters = [m for m in meters if not utility or m.utility_type.name == utility]
        if meters:
            groups.append((beneficiary, meters))
    return groups


def read_ledger_filters():
    fy_year, fy_quarter = current_period()
    return {
        "year": request.values.get("year", fy_year, type=int),
        "quarter": request.values.get("quarter", fy_quarter, type=int),
        "account": request.values.get("account", type=int) or 0,
        "utility": (request.values.get("utility") or "").strip(),
    }


def report_quarters(filters):
    """The quarter(s) a report spans: all four when quarter is 0 ('All')."""
    return [1, 2, 3, 4] if filters["quarter"] == 0 else [filters["quarter"]]


def ledger_lines_for_meter(meter, filters):
    """One ledger line per requested quarter; empty quarters skipped in All mode."""
    lines = []
    for quarter in report_quarters(filters):
        ledger = meter_ledger(meter.id, filters["year"], quarter)
        if filters["quarter"] == 0 and not any(
            ledger[key] for key in ("carry_in", "allocation", "usage", "balance")
        ):
            continue
        lines.append({"meter": meter, "quarter": quarter, **ledger})
    return lines


@admin_bp.route("/major-accounts", methods=["GET", "POST"])
def major_accounts():
    filters = read_ledger_filters()
    groups = filter_major_account_groups(filters["account"], filters["utility"])

    if request.method == "POST":
        if filters["quarter"] not in (1, 2, 3, 4) or not filters["year"]:
            flash("Pick a single quarter to record usage against.", "danger")
        else:
            saved, error = save_usage(groups, filters["quarter"], filters["year"])
            if error:
                flash(error, "danger")
            elif saved:
                flash(
                    f"Saved {saved} usage figure(s) for Q{filters['quarter']} {filters['year']}.", "success"
                )
            else:
                flash("No usage figures were changed.", "info")
            return redirect(url_for("admin.major_accounts", **filters))

    all_quarters = filters["quarter"] == 0
    rows = []
    for beneficiary, meters in groups:
        lines = [line for meter in meters for line in ledger_lines_for_meter(meter, filters)]
        if all_quarters:
            # Current standing = each meter's year-end balance (not a sum across quarters).
            total_balance = sum((meter_ledger(m.id, filters["year"], 4)["balance"] for m in meters), 0)
        else:
            total_balance = sum((line["balance"] for line in lines), 0)
        rows.append(
            {
                "beneficiary": beneficiary,
                "lines": lines,
                "total_allocation": sum((line["allocation"] for line in lines), 0),
                "total_usage": sum((line["usage"] for line in lines), 0),
                "total_balance": total_balance,
            }
        )

    return render_template(
        "admin/major_accounts.html",
        rows=rows,
        filters=filters,
        all_quarters=all_quarters,
        accounts=[(b.id, b.label) for b, _ in eligible_major_account_meters()],
        utilities=CARRYFORWARD_UTILITIES,
        charts=ledger_charts(groups, filters["year"]),
        total_allocation=sum((r["total_allocation"] for r in rows), 0),
        total_usage=sum((r["total_usage"] for r in rows), 0),
        total_balance=sum((r["total_balance"] for r in rows), 0),
    )


def ledger_charts(groups, year):
    """Full-year quarterly trend and usage-by-utility, for the filtered meters.

    The trend always spans Q1-Q4 (that's the point of visualising carry-forward),
    scoped by whatever account/utility filter produced `groups`.
    """
    meters = [meter for _, meters in groups for meter in meters]

    allocation, usage, balance = [], [], []
    for quarter in (1, 2, 3, 4):
        ledgers = [meter_ledger(m.id, year, quarter) for m in meters]
        allocation.append(float(sum((line["allocation"] for line in ledgers), 0)))
        usage.append(float(sum((line["usage"] for line in ledgers), 0)))
        balance.append(float(sum((line["balance"] for line in ledgers), 0)))

    usage_by_utility = {}
    for meter in meters:
        total = sum((meter_ledger(meter.id, year, q)["usage"] for q in (1, 2, 3, 4)), 0)
        name = meter.utility_type.name
        usage_by_utility[name] = usage_by_utility.get(name, 0) + float(total)

    return {
        "trend": {
            "labels": [f"Q{q} {year}" for q in (1, 2, 3, 4)],
            "allocation": allocation,
            "usage": usage,
            "balance": balance,
        },
        "utility_usage": {
            "labels": list(usage_by_utility.keys()),
            "values": list(usage_by_utility.values()),
        },
    }


def ledger_report_lines(filters):
    """Flat ledger lines for export, honouring the account/utility/quarter filter."""
    lines = []
    for beneficiary, meters in filter_major_account_groups(filters["account"], filters["utility"]):
        for meter in meters:
            for line in ledger_lines_for_meter(meter, filters):
                lines.append(
                    {
                        "beneficiary": beneficiary.label,
                        "utility": meter.utility_type.name,
                        "number": meter.number,
                        **line,
                    }
                )
    return lines


def ledger_report_totals(filters, lines):
    """Column totals for a ledger report.

    Allocation and usage are summed across the shown rows. Balance is the current
    standing — each meter's year-end balance — not a sum of per-quarter balances
    (which would double-count the running figure).
    """
    total_allocation = sum((line["allocation"] for line in lines), 0)
    total_usage = sum((line["usage"] for line in lines), 0)

    if filters["quarter"] == 0:
        total_balance = sum(
            (
                meter_ledger(meter.id, filters["year"], 4)["balance"]
                for _, meters in filter_major_account_groups(filters["account"], filters["utility"])
                for meter in meters
            ),
            0,
        )
    else:
        total_balance = sum((line["balance"] for line in lines), 0)

    return total_allocation, total_usage, total_balance


def ledger_report_scope(filters):
    account = Beneficiary.query.get(filters["account"]) if filters["account"] else None
    scope = account.label if account else "All Major Accounts"
    if filters["utility"]:
        scope += f" — {filters['utility']}"
    return scope


def ledger_period_label(filters):
    return (
        f"{filters['year']} (all quarters)"
        if filters["quarter"] == 0
        else f"{filters['year']} Q{filters['quarter']}"
    )


def ledger_download_name(filters):
    quarter = "all-quarters" if filters["quarter"] == 0 else f"Q{filters['quarter']}"
    parts = ["ledger", str(filters["year"]), quarter]
    if filters["account"]:
        parts.append(f"acct{filters['account']}")
    if filters["utility"]:
        parts.append(filters["utility"].lower())
    return "_".join(parts)


@admin_bp.route("/major-accounts/report.csv")
def major_accounts_csv():
    filters = read_ledger_filters()
    lines = ledger_report_lines(filters)

    log_activity(
        current_user,
        "Generated ledger CSV report",
        quarter=filters["quarter"],
        year=filters["year"],
        utility=filters["utility"] or None,
    )
    db.session.commit()

    total_allocation, total_usage, total_balance = ledger_report_totals(filters, lines)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Beneficiary",
            "Utility",
            "Number",
            "Quarter",
            "Carried In",
            "Allocation",
            "Pool",
            "Usage",
            "Balance",
        ]
    )
    for line in lines:
        writer.writerow(
            [
                line["beneficiary"],
                line["utility"],
                line["number"],
                f"Q{line['quarter']} {filters['year']}",
                line["carry_in"],
                line["allocation"],
                line["pool"],
                line["usage"],
                line["balance"],
            ]
        )
    writer.writerow(["Total", "", "", "", "", total_allocation, "", total_usage, total_balance])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={ledger_download_name(filters)}.csv"},
    )


@admin_bp.route("/major-accounts/report.pdf")
def major_accounts_pdf():
    filters = read_ledger_filters()
    lines = ledger_report_lines(filters)

    log_activity(
        current_user,
        "Generated ledger PDF report",
        quarter=filters["quarter"],
        year=filters["year"],
        utility=filters["utility"] or None,
    )
    db.session.commit()

    def money(value):
        return f"UGX {value or 0:,.0f}"

    rows = [
        [
            line["beneficiary"],
            line["utility"],
            line["number"],
            f"Q{line['quarter']} {filters['year']}",
            money(line["carry_in"]),
            money(line["allocation"]),
            money(line["pool"]),
            money(line["usage"]),
            money(line["balance"]),
        ]
        for line in lines
    ]
    if lines:
        total_allocation, total_usage, total_balance = ledger_report_totals(filters, lines)
        rows.append(
            ["Total", "", "", "", "", money(total_allocation), "", money(total_usage), money(total_balance)]
        )

    pdf = table_pdf(
        title="Major Accounts Ledger",
        subtitle=f"{ledger_report_scope(filters)} — {ledger_period_label(filters)}",
        meta_lines=[f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}"],
        headers=[
            "Beneficiary",
            "Utility",
            "Number",
            "Quarter",
            "Carried In",
            "Allocation",
            "Pool",
            "Usage",
            "Balance",
        ],
        rows=rows,
        right_align_from=4,
        bold_last_row=bool(lines),
    )
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={ledger_download_name(filters)}.pdf"},
    )


def save_usage(groups, quarter, year):
    """Upsert one usage figure per eligible meter. Blank leaves it unchanged."""
    eligible_ids = {meter.id for _, meters in groups for meter in meters}
    changed = 0

    for meter_id in eligible_ids:
        raw = request.form.get(f"usage_{meter_id}", "").strip()
        if raw == "":
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return 0, f"'{raw}' is not a valid amount."
        if amount < 0:
            return 0, "Usage cannot be negative."

        meter = Meter.query.get(meter_id)
        usage = Usage.query.filter_by(meter_id=meter_id, quarter=quarter, year=year).first()

        if usage is None:
            db.session.add(
                Usage(
                    meter_id=meter_id,
                    quarter=quarter,
                    year=year,
                    amount=amount,
                    created_by_id=current_user.id,
                )
            )
            log_activity(
                current_user,
                "Recorded usage",
                meter.beneficiary,
                meter=meter,
                quarter=quarter,
                year=year,
                amount=amount,
            )
            changed += 1
        elif usage.amount != amount:
            previous = usage.amount
            usage.amount = amount
            log_activity(
                current_user,
                "Updated usage",
                meter.beneficiary,
                meter=meter,
                quarter=quarter,
                year=year,
                amount=amount,
                previous_amount=previous,
            )
            changed += 1

    if changed:
        db.session.commit()
    return changed, None


# --------------------------------------------------------------------------
# Allocations
# --------------------------------------------------------------------------


@admin_bp.route("/allocations/new", methods=["GET", "POST"])
def new_allocation():
    if request.method == "POST":
        beneficiary_id = request.form.get("beneficiary_id", type=int)
        beneficiary = Beneficiary.query.get(beneficiary_id) if beneficiary_id else None
        quarter = request.form.get("quarter", type=int)
        year = request.form.get("year", type=int)

        if not beneficiary:
            flash("Pick a registered beneficiary from the suggestions.", "danger")
        elif quarter not in (1, 2, 3, 4) or not year:
            flash("Select a valid quarter and year.", "danger")
        else:
            changed, error = save_allocations(beneficiary, quarter, year)
            if error:
                flash(error, "danger")
            elif changed:
                flash(
                    f"Saved {changed} change(s) for {beneficiary.label} — Q{quarter} {year}.",
                    "success",
                )
                return redirect(url_for("admin.dashboard"))
            else:
                flash("No figures were changed, so nothing was logged.", "info")
                return redirect(url_for("admin.dashboard"))

    fy_year, fy_quarter = current_period()
    return render_template(
        "admin/new_allocation.html",
        year=fy_year,
        quarter=fy_quarter,
    )


def save_allocations(beneficiary, quarter, year):
    """Upsert one allocation per meter that has an amount. Blank means 'leave alone'.

    Only meters whose amount actually changed are logged, so re-saving the form
    without touching a figure does not litter the audit trail with no-op entries.
    """
    changed = 0
    for meter in beneficiary.meters:
        raw = request.form.get(f"amount_{meter.id}", "").strip()
        if raw == "":
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return 0, f"'{raw}' is not a valid amount."
        if amount < 0:
            return 0, "Amounts cannot be negative."

        allocation = Allocation.query.filter_by(meter_id=meter.id, quarter=quarter, year=year).first()

        if allocation is None:
            db.session.add(
                Allocation(
                    meter_id=meter.id,
                    quarter=quarter,
                    year=year,
                    amount=amount,
                    created_by_id=current_user.id,
                )
            )
            log_activity(
                current_user,
                "Allocated",
                beneficiary,
                meter=meter,
                quarter=quarter,
                year=year,
                amount=amount,
            )
            changed += 1

        elif allocation.amount != amount:
            previous = allocation.amount
            allocation.amount = amount
            log_activity(
                current_user,
                "Updated allocation",
                beneficiary,
                meter=meter,
                quarter=quarter,
                year=year,
                amount=amount,
                previous_amount=previous,
            )
            changed += 1
        # else: figure is unchanged - nothing happened, so nothing to log

    if changed:
        db.session.commit()
    return changed, None


# --------------------------------------------------------------------------
# Users / utility types
# --------------------------------------------------------------------------


@admin_bp.route("/users/new", methods=["GET", "POST"])
def new_user():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("A user with that email already exists.", "danger")
        else:
            user = User(name=form.name.data, email=form.email.data, role=form.role.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash(f"User {user.name} created.", "success")
            return redirect(url_for("admin.dashboard"))
    return render_template("admin/new_user.html", form=form)


@admin_bp.route("/utility-types/new", methods=["GET", "POST"])
def new_utility_type():
    form = UtilityTypeForm()
    if form.validate_on_submit():
        if UtilityType.query.filter_by(name=form.name.data).first():
            flash("That utility type already exists.", "danger")
        else:
            db.session.add(UtilityType(name=form.name.data))
            db.session.commit()
            flash("Utility type added.", "success")
            return redirect(url_for("admin.dashboard"))
    return render_template("admin/new_utility_type.html", form=form)


# --------------------------------------------------------------------------
# Quarter summary
# --------------------------------------------------------------------------


def build_quarter_summary(filters):
    """Totals for the filtered allocations, grouped by utility and by beneficiary."""
    totals = {}
    for allocation in allocation_query(filters).all():
        meter = allocation.meter
        totals.setdefault("utility", {}).setdefault(meter.utility_type_id, 0)
        totals.setdefault("beneficiary", {}).setdefault(meter.beneficiary_id, 0)
        totals["utility"][meter.utility_type_id] += allocation.amount
        totals["beneficiary"][meter.beneficiary_id] += allocation.amount

    by_utility_totals = totals.get("utility", {})
    by_beneficiary_totals = totals.get("beneficiary", {})
    total_allocated = sum(by_utility_totals.values(), 0)

    def share(amount):
        return float(amount) / float(total_allocated) * 100 if total_allocated else 0

    by_utility = [
        {
            "name": utility_type.name,
            "allocated": by_utility_totals.get(utility_type.id, 0),
            "share": share(by_utility_totals.get(utility_type.id, 0)),
        }
        for utility_type in matching_utility_types(filters)
    ]

    by_beneficiary = [
        {
            "name": beneficiary.label,
            "position": beneficiary.position,
            "allocated": by_beneficiary_totals.get(beneficiary.id, 0),
            "share": share(by_beneficiary_totals.get(beneficiary.id, 0)),
        }
        for beneficiary in matching_beneficiaries(filters)
    ]

    reverse = filters["direction"] == "desc"
    if filters["sort"] in ("allocated", "utility"):
        key = "allocated" if filters["sort"] == "allocated" else "name"
        by_utility.sort(key=lambda row: row[key], reverse=reverse)
    if filters["sort"] in ("allocated", "beneficiary", "position"):
        key = {"beneficiary": "name", "position": "position"}.get(filters["sort"], "allocated")
        by_beneficiary.sort(key=lambda row: row[key], reverse=reverse)

    return {
        "total_allocated": total_allocated,
        "beneficiary_count": sum(1 for row in by_beneficiary if row["allocated"]),
        "by_utility": by_utility,
        "by_beneficiary": by_beneficiary,
    }


@admin_bp.route("/summary")
def summary():
    filters = parse_filters()
    data = build_quarter_summary(filters)

    utility_rows = [r for r in data["by_utility"] if r["allocated"]]
    top_beneficiaries = sorted(
        (r for r in data["by_beneficiary"] if r["allocated"]),
        key=lambda r: r["allocated"],
        reverse=True,
    )[:10]
    charts = {
        "utility": {
            "labels": [r["name"] for r in utility_rows],
            "values": [float(r["allocated"]) for r in utility_rows],
        },
        "beneficiary": {
            "labels": [r["name"] for r in top_beneficiaries],
            "values": [float(r["allocated"]) for r in top_beneficiaries],
        },
    }

    return render_template(
        "admin/summary.html",
        filters=filters,
        period=period_label(filters),
        utility_types=UtilityType.query.order_by(UtilityType.name).all(),
        positions=POSITIONS,
        charts=charts,
        **data,
    )
