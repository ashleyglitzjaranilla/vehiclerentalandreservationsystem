"""The Rental Management Dashboard: what the fleet is doing right now."""

from __future__ import annotations

from datetime import datetime, time

from flask import Blueprint, render_template
from sqlalchemy import func, select

from ..auth import admin_required
from ..clock import today
from ..db import get_session
from ..models import VEHICLE_STATUSES, Rental, Reservation, Vehicle

bp = Blueprint("admin_dashboard", __name__, url_prefix="/admin")


# An empty rule registers exactly "/admin". @bp.route("/") would register
# "/admin/", and a request for "/admin" would then answer 308 rather than 200.
@bp.route("")
@admin_required
def dashboard():
    """Fleet counts by status, plus today's operational numbers and revenue.

    Every figure is a real query. Reservation and rental counts are legitimately
    zero until phase 3 gives the system a way to create one; these are the final
    queries and start reporting the moment it does.
    """
    db = get_session()

    total = db.scalar(select(func.count()).select_from(Vehicle)) or 0
    grouped = db.execute(
        select(Vehicle.status, func.count(Vehicle.id)).group_by(Vehicle.status)
    ).all()
    counts = {status: 0 for status in VEHICLE_STATUSES}
    for status, count in grouped:
        counts[status] = count

    today_start = datetime.combine(today(), time.min)
    today_end = datetime.combine(today(), time.max)

    pending = db.scalar(
        select(func.count()).select_from(Reservation).where(Reservation.status == "PENDING")
    ) or 0
    pickups_today = db.scalar(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.status == "CONFIRMED")
        .where(Reservation.pickup_at.between(today_start, today_end))
    ) or 0
    returns_today = db.scalar(
        select(func.count())
        .select_from(Rental)
        .where(Rental.status == "ACTIVE")
        .where(Rental.expected_return.between(today_start, today_end))
    ) or 0
    revenue = db.scalar(
        select(func.coalesce(func.sum(Rental.total_amount), 0)).where(Rental.status == "COMPLETED")
    ) or 0

    return render_template(
        "admin/dashboard.html",
        total=total,
        counts=counts,
        pending=pending,
        pickups_today=pickups_today,
        returns_today=returns_today,
        revenue=revenue,
    )
