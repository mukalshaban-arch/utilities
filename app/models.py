import secrets
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

ROLES = ("admin",)

MAJOR_ACCOUNTS = "Major Accounts"

POSITIONS = (
    MAJOR_ACCOUNTS,
    "Director",
    "Deputy Director",
    "Section Head",
    "Other",
)

# Facilities only apply to Major Accounts beneficiaries.
FACILITIES = (
    "HQ",
    "Rubaga House",
    "Defence",
    "Signal",
    "Katonga",
    "Jumbo",
    "Mbarara",
    "Kabale",
    "Arua",
    "DG",
    "DDG",
)

# Departments apply to staff, i.e. every position except Major Accounts.
DEPARTMENTS = (
    "DAF",
    "DIC",
    "DIA",
    "DDI",
    "DTI",
    "DLP",
)

# Usage tracking with quarter-to-quarter carry-forward applies ONLY to these
# utilities, and only for Major Accounts.
CARRYFORWARD_UTILITIES = ("Power", "Water")


def is_carryforward_meter(meter):
    return (
        meter.beneficiary.position == MAJOR_ACCOUNTS
        and meter.utility_type.name in CARRYFORWARD_UTILITIES
    )


class User(UserMixin, db.Model):
    """Login account. Beneficiaries are a separate register (see Beneficiary)."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class UtilityType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    def __repr__(self):
        return f"<UtilityType {self.name}>"


class Beneficiary(db.Model):
    """A person or major account entitled to utility money."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    position = db.Column(db.String(40), nullable=False)
    facility = db.Column(db.String(40))  # set only when position is Major Accounts
    department = db.Column(db.String(40))  # set for every other position

    meters = db.relationship("Meter", back_populates="beneficiary", order_by="Meter.id")

    @property
    def label(self):
        return f"{self.name} - {self.facility}" if self.facility else self.name

    @property
    def unit(self):
        """Where the beneficiary sits: a facility for major accounts, else a department."""
        return self.facility or self.department or "—"

    def __repr__(self):
        return f"<Beneficiary {self.name}>"


class Meter(db.Model):
    """A single meter / phone / account number belonging to a beneficiary.

    A beneficiary may hold several per utility (e.g. 2 power meters, 5 phone numbers).
    """

    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    utility_type_id = db.Column(db.Integer, db.ForeignKey("utility_type.id"), nullable=False)
    number = db.Column(db.String(60), nullable=False)

    beneficiary = db.relationship("Beneficiary", back_populates="meters")
    utility_type = db.relationship("UtilityType")

    __table_args__ = (db.UniqueConstraint("utility_type_id", "number", name="uq_meter_number"),)

    def __repr__(self):
        return f"<Meter {self.number}>"


class Allocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meter_id = db.Column(db.Integer, db.ForeignKey("meter.id"), nullable=False)
    quarter = db.Column(db.Integer, nullable=False)  # 1-4
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    meter = db.relationship("Meter")

    __table_args__ = (
        db.UniqueConstraint("meter_id", "quarter", "year", name="uq_allocation_period"),
    )


class QuarterBudget(db.Model):
    """The total pool the admin was given for utility allocation in a quarter.

    Allocations draw this down: balance = amount - sum of that quarter's allocations.
    One figure per quarter per year.
    """

    id = db.Column(db.Integer, primary_key=True)
    quarter = db.Column(db.Integer, nullable=False)  # 1-4
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("quarter", "year", name="uq_quarter_budget"),
    )


class Usage(db.Model):
    """Actual bill/usage recorded against a meter for a quarter.

    One figure per meter per quarter. Only used for Major-Account water/power
    meters (see is_carryforward_meter); other meters never get usage rows.
    """

    id = db.Column(db.Integer, primary_key=True)
    meter_id = db.Column(db.Integer, db.ForeignKey("meter.id"), nullable=False)
    quarter = db.Column(db.Integer, nullable=False)  # 1-4
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    meter = db.relationship("Meter")

    __table_args__ = (
        db.UniqueConstraint("meter_id", "quarter", "year", name="uq_usage_period"),
    )


class ActivityLog(db.Model):
    """Append-only record of who did what, when.

    Details are snapshotted as text rather than joined, so an entry still reads
    correctly after a beneficiary is renamed or a meter number is changed.
    """

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action = db.Column(db.String(40), nullable=False)

    beneficiary_name = db.Column(db.String(120))  # absent for system-wide actions e.g. reports
    unit = db.Column(db.String(40))  # department, or facility for major accounts
    utility = db.Column(db.String(80))
    number = db.Column(db.String(60))
    quarter = db.Column(db.Integer)
    year = db.Column(db.Integer)
    amount = db.Column(db.Numeric(12, 2))
    previous_amount = db.Column(db.Numeric(12, 2))  # set when an allocation was changed

    user = db.relationship("User")


MAX_LOGIN_ATTEMPTS = 4
LOCKOUT_MINUTES = 10

PASSKEY_EXPIRY_MINUTES = 60
# Ambiguous characters (0/O, 1/I/L) are left out: the passkey is read aloud or
# written down when the admin passes it to the user.
PASSKEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class PasswordResetRequest(db.Model):
    """A user asks the admin for a temporary passkey so they can set a new password."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/issued/used/cancelled

    passkey_hash = db.Column(db.String(255))  # only the hash is kept
    issued_at = db.Column(db.DateTime)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    expires_at = db.Column(db.DateTime)
    used_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])
    issued_by = db.relationship("User", foreign_keys=[issued_by_id])

    def issue(self, admin):
        """Generate a fresh passkey, store only its hash, and return the plain text once."""
        passkey = "".join(secrets.choice(PASSKEY_ALPHABET) for _ in range(8))
        self.passkey_hash = generate_password_hash(passkey)
        self.status = "issued"
        self.issued_at = datetime.utcnow()
        self.issued_by_id = admin.id
        self.expires_at = self.issued_at + timedelta(minutes=PASSKEY_EXPIRY_MINUTES)
        return passkey

    @property
    def is_expired(self):
        return bool(self.expires_at and datetime.utcnow() > self.expires_at)

    def verify(self, passkey):
        return (
            self.status == "issued"
            and not self.is_expired
            and self.passkey_hash
            and check_password_hash(self.passkey_hash, passkey)
        )


class LoginLog(db.Model):
    """Every sign-in attempt, successful or not.

    The email is stored as typed, because a failed attempt may not match any user.
    """

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    email = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # null if no such account
    success = db.Column(db.Boolean, nullable=False)
    ip_address = db.Column(db.String(45))
    # Attempt number within the current run of tries: on a success row this is how
    # many attempts it took to get in.
    attempts = db.Column(db.Integer, nullable=False, default=1)
    # Turned away because the account was already locked. Recorded for visibility but
    # NOT counted as a failure, so hammering a locked account cannot extend the lockout.
    blocked = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User")


def _recent_failures(email):
    """Failed attempts inside the lockout window, newest first."""
    window_start = datetime.utcnow() - timedelta(minutes=LOCKOUT_MINUTES)

    last_success = (
        db.session.query(db.func.max(LoginLog.created_at))
        .filter(LoginLog.email == email, LoginLog.success.is_(True))
        .scalar()
    )
    if last_success and last_success > window_start:
        window_start = last_success  # a success wipes the slate

    # A completed password reset also wipes the slate, so a user who has just been
    # given a new password is not still locked out by their old failed attempts.
    last_reset = (
        db.session.query(db.func.max(PasswordResetRequest.used_at))
        .join(User, PasswordResetRequest.user_id == User.id)
        .filter(User.email == email)
        .scalar()
    )
    if last_reset and last_reset > window_start:
        window_start = last_reset

    return (
        LoginLog.query.filter(
            LoginLog.email == email,
            LoginLog.success.is_(False),
            LoginLog.blocked.is_(False),
            LoginLog.created_at > window_start,
        )
        .order_by(LoginLog.created_at.desc())
        .all()
    )


def lockout_seconds_remaining(email):
    """0 if the account may attempt a login, else seconds until it may try again."""
    failures = _recent_failures(email)
    if len(failures) < MAX_LOGIN_ATTEMPTS:
        return 0

    unlock_at = failures[0].created_at + timedelta(minutes=LOCKOUT_MINUTES)
    return max(0, (unlock_at - datetime.utcnow()).total_seconds())


def record_login(email, user, success, ip_address=None, blocked=False):
    entry = LoginLog(
        email=email,
        user_id=user.id if user else None,
        success=success,
        ip_address=ip_address,
        blocked=blocked,
        attempts=len(_recent_failures(email)) + 1,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def log_activity(
    user,
    action,
    beneficiary=None,
    meter=None,
    quarter=None,
    year=None,
    amount=None,
    previous_amount=None,
    utility=None,
):
    """Record one action. `beneficiary` is None for system-wide actions such as reports."""
    entry = ActivityLog(
        user_id=user.id,
        action=action,
        beneficiary_name=beneficiary.name if beneficiary else None,
        unit=(beneficiary.facility or beneficiary.department) if beneficiary else None,
        utility=meter.utility_type.name if meter else utility,
        number=meter.number if meter else None,
        quarter=quarter,
        year=year,
        amount=amount,
        previous_amount=previous_amount,
    )
    db.session.add(entry)
    return entry
