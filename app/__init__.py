from datetime import timezone
from zoneinfo import ZoneInfo

import click
from flask import Flask, redirect, url_for, session
from flask_login import login_required

from config import Config
from app.extensions import db, login_manager, migrate, csrf


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"

    @app.before_request
    def make_session_permanent():
        # Opt every session into the sliding inactivity lifetime set in config.
        session.permanent = True

    @app.template_filter("ugx")
    def format_ugx(value):
        return f"UGX {value or 0:,.0f}"

    @app.template_filter("qmonths")
    def format_qmonths(quarter):
        from app.fiscal import quarter_span

        return quarter_span(quarter)

    @app.template_filter("localtime")
    def format_localtime(value):
        """Render a naive-UTC timestamp in the configured local zone."""
        if value is None:
            return "—"
        local = value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(app.config["TIMEZONE"]))
        return local.strftime("%d %b %Y %H:%M")

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp
    from app.reports.routes import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)

    @app.route("/")
    @login_required
    def index():
        return redirect(url_for("admin.dashboard"))

    register_cli(app)

    return app


def register_cli(app):
    @app.cli.command("backup")
    @click.option("--keep", default=30, show_default=True, help="How many backups to retain.")
    def backup(keep):
        """Write a database backup, then prune old ones. Intended for a scheduled task."""
        from app.backup import create_backup, prune_backups, BackupError

        try:
            target = create_backup()
        except BackupError as exc:
            raise SystemExit(f"Backup failed: {exc}") from exc

        size_mb = target.stat().st_size / 1024 / 1024
        click.echo(f"Backup written: {target} ({size_mb:.2f} MB)")

        for removed in prune_backups(keep):
            click.echo(f"Pruned old backup: {removed}")

    @app.cli.command("seed")
    @click.option("--admin-email", default="admin@example.com")
    @click.option("--admin-password", default="admin123")
    def seed(admin_email, admin_password):
        """Seed utility types and create the first admin user."""
        from app.models import User, UtilityType

        for name in ("Power", "Water", "Mobile Airtime", "Office Phone Airtime", "Fax"):
            if not UtilityType.query.filter_by(name=name).first():
                db.session.add(UtilityType(name=name))

        if not User.query.filter_by(email=admin_email).first():
            admin = User(name="Admin", email=admin_email, role="admin")
            admin.set_password(admin_password)
            db.session.add(admin)

        db.session.commit()
        click.echo(f"Seeded utility types and admin user ({admin_email}).")
