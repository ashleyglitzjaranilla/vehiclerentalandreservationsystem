"""Application factory for the Vehicle Rental and Reservation System."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from . import auth, booking, cli, db, portal, public, reports
from .admin import dashboard as admin_dashboard
from .admin import fleet as admin_fleet
from .admin import rates as admin_rates
from .admin import rentals as admin_rentals
from .admin import reservations as admin_reservations
from .forms import max_year
from .models import (
    FUEL_TYPES,
    STATUS_BADGES,
    TRANSMISSIONS,
    VEHICLE_STATUSES,
    VEHICLE_TYPES,
)

# Load .env for local development. On Vercel the variables are already in the
# environment, and load_dotenv simply finds no file and does nothing.
load_dotenv()


def create_app(config: dict | None = None) -> Flask:
    """Build and configure the Flask application.

    ``config`` lets the tests override settings (an in-memory database, CSRF
    switched off) without touching the environment. No tables are created here:
    that is what ``flask init-db`` is for.
    """
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["DATABASE_URL"] = db.get_database_url()
    if config:
        app.config.update(config)

    # Protects every POST in the app and makes csrf_token() available in templates.
    CSRFProtect(app)

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(public.bp)
    app.register_blueprint(booking.bp)
    app.register_blueprint(portal.bp)
    app.register_blueprint(admin_dashboard.bp)
    app.register_blueprint(admin_fleet.bp)
    app.register_blueprint(admin_rates.bp)
    app.register_blueprint(admin_reservations.bp)
    app.register_blueprint(admin_rentals.bp)
    app.register_blueprint(reports.bp)
    cli.register_cli(app)
    register_template_globals(app)
    register_error_handlers(app)
    register_password_change_gate(app)

    return app


def register_password_change_gate(app: Flask) -> None:
    """Hold anyone carrying a temporary password on the change-password page."""

    @app.before_request
    def force_password_change():
        user = auth.current_user()
        if user is None or not user.must_change_password:
            return None
        # Without the `static` exemption the change-password page would render
        # with no stylesheet, because the request for output.css would itself
        # be redirected.
        if request.endpoint in ("auth.change_password", "auth.logout", "static"):
            return None
        return redirect(url_for("auth.change_password"))


def register_template_globals(app: Flask) -> None:
    """Make the shared option lists and the current user available to every template."""

    @app.context_processor
    def inject_globals():
        user = auth.current_user()
        role = user.role if user else None
        return {
            "VEHICLE_STATUSES": VEHICLE_STATUSES,
            "VEHICLE_TYPES": VEHICLE_TYPES,
            "TRANSMISSIONS": TRANSMISSIONS,
            "FUEL_TYPES": FUEL_TYPES,
            "STATUS_BADGES": STATUS_BADGES,
            "current_user": user,
            "current_username": user.username if user else None,
            "current_role": role,
            "is_admin": role == "admin",
            "is_customer": role == "customer",
            "max_year": max_year(),
        }


def register_error_handlers(app: Flask) -> None:
    """Show friendly pages instead of Flask's default error output."""

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        """Handle an expired or missing CSRF token with a message instead of a bare 400.

        This happens when a page has been left open long enough for the session
        cookie to expire. Sending the visitor to the public landing page --
        which is reachable by everyone, signed in or not -- is friendlier than
        Flask-WTF's default error page.
        """
        flash("Your session expired. Please try that again.", "warning")
        return redirect(url_for("public.landing"))

    @app.errorhandler(403)
    def forbidden(error):
        """Explain that this page belongs to a different kind of account.

        Reached when a signed-in account asks for a page its role does not
        cover, either by typing the URL or by following a stale link.
        """
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        # The session may be in a broken state after a database error.
        db.close_session()
        return render_template("500.html"), 500
