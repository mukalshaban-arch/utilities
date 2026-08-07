from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required

from datetime import datetime
from math import ceil

from app.extensions import db
from app.models import (
    User,
    PasswordResetRequest,
    record_login,
    lockout_seconds_remaining,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_MINUTES,
)
from app.auth.forms import LoginForm, ForgotPasswordForm, PasskeyForm, NewPasswordForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        user = User.query.filter_by(email=email).first()
        locked_for = lockout_seconds_remaining(email)

        if locked_for:
            # Refuse without even checking the password.
            record_login(email, user, success=False, ip_address=request.remote_addr, blocked=True)
            minutes = ceil(locked_for / 60)
            flash(
                f"Too many failed attempts. This account is locked for another "
                f"{minutes} minute{'s' if minutes != 1 else ''}. "
                f"Please try again later or contact your administrator.",
                "danger",
            )
            return render_template("auth/login.html", form=form)

        if user and user.check_password(form.password.data):
            record_login(email, user, success=True, ip_address=request.remote_addr)
            login_user(user)
            return redirect(url_for("index"))

        # Log the attempt whether or not the email matches an account, but do not
        # reveal to the visitor which of the two was wrong.
        entry = record_login(email, user, success=False, ip_address=request.remote_addr)
        remaining = MAX_LOGIN_ATTEMPTS - entry.attempts

        if remaining > 0:
            flash(
                f"Invalid email or password. "
                f"{remaining} attempt{'s' if remaining != 1 else ''} remaining before "
                f"this account is locked.",
                "danger",
            )
        else:
            flash(
                f"Invalid email or password. This account is now locked for "
                f"{LOCKOUT_MINUTES} minutes. "
                f"Please try again later or contact your administrator.",
                "danger",
            )

    return render_template("auth/login.html", form=form)


@auth_bp.route("/ping")
@login_required
def ping():
    """Keepalive: touching any endpoint refreshes the sliding session cookie.

    The client calls this while the user is active (moving the mouse but not
    navigating), so an active session is not expired server-side by mistake.
    """
    return "", 204


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    """Raise an alert for the admin, who will hand the user a temporary passkey."""
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user:
            pending = PasswordResetRequest.query.filter_by(
                user_id=user.id, status="pending"
            ).first()
            if not pending:
                db.session.add(PasswordResetRequest(user_id=user.id))
                db.session.commit()

        # Say the same thing either way, so this cannot be used to discover
        # which email addresses have accounts.
        flash(
            "If that email is registered, your administrator has been alerted. "
            "They will give you a temporary passkey - enter it below once you have it.",
            "info",
        )
        return redirect(url_for("auth.reset_password"))

    return render_template("auth/forgot.html", form=form)


@auth_bp.route("/reset", methods=["GET", "POST"])
def reset_password():
    """Step 1: the user proves they hold the passkey the admin gave them."""
    form = PasskeyForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        reset = None
        if user:
            reset = (
                PasswordResetRequest.query.filter_by(user_id=user.id, status="issued")
                .order_by(PasswordResetRequest.issued_at.desc())
                .first()
            )

        if reset and reset.verify(form.passkey.data.strip().upper()):
            # Remember only the id; the new password is set on the next step.
            session["reset_request_id"] = reset.id
            return redirect(url_for("auth.new_password"))

        if reset and reset.is_expired:
            flash("That passkey has expired. Ask your administrator for a new one.", "danger")
        else:
            flash("That passkey is not valid. Check it with your administrator.", "danger")

    return render_template("auth/reset.html", form=form)


@auth_bp.route("/reset/password", methods=["GET", "POST"])
def new_password():
    """Step 2: having proved the passkey, the user chooses a new password."""
    reset = PasswordResetRequest.query.get(session.get("reset_request_id", 0))
    if not reset or reset.status != "issued" or reset.is_expired:
        session.pop("reset_request_id", None)
        flash("Start again - your passkey is no longer valid.", "danger")
        return redirect(url_for("auth.reset_password"))

    form = NewPasswordForm()
    if form.validate_on_submit():
        reset.user.set_password(form.password.data)
        reset.status = "used"
        reset.used_at = datetime.utcnow()
        db.session.commit()
        session.pop("reset_request_id", None)

        flash("Your password has been changed. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/new_password.html", form=form, email=reset.user.email)
