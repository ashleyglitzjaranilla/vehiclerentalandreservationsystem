"""Vehicles that are out, and taking them back.

The return is requirement 18's five-part close: the rental finishes, the
reservation finishes, the vehicle comes back to AVAILABLE, the actual return
time is recorded, and any late fee is charged. `complete_rental` returns all of
those statuses as one value and `apply_change` writes them in one transaction,
so no route can do four of the five.
"""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from sqlalchemy import select

from .. import scheduling
from ..auth import admin_required
from ..clock import now
from ..db import get_session
from ..domain.lifecycle import TransitionError, complete_rental
from ..domain.pricing import late_charge, money
from ..models import Rental, Reservation, User, Vehicle
from .reservations import apply_change

bp = Blueprint("admin_rentals", __name__, url_prefix="/admin/rentals")


# An empty rule registers exactly "/admin/rentals"; see admin/dashboard.py.
@bp.route("")
@admin_required
def index():
    """Every rental, the ones still out first.

    Neither `Rental.vehicle` nor `Rental.customer` is a relationship -- the
    models declare none -- so both are joined explicitly and selected alongside
    the rental, and the template unpacks the (Rental, User, Vehicle) triple
    instead of walking an attribute.
    """
    db = get_session()
    rows = db.execute(
        select(Rental, User, Vehicle)
        .join(User, User.id == Rental.customer_id)
        .join(Vehicle, Vehicle.id == Rental.vehicle_id)
        .order_by(Rental.actual_pickup.desc(), Rental.id.desc())
    ).all()
    return render_template(
        "admin/rentals.html",
        active=[row for row in rows if row[0].status == "ACTIVE"],
        finished=[row for row in rows if row[0].status != "ACTIVE"],
    )


@bp.route("/<int:rental_id>/return", methods=["POST"])
@admin_required
def mark_returned(rental_id: int):
    """The vehicle comes back. Records the time and charges for any overrun."""
    db = get_session()
    rental = db.get(Rental, rental_id)
    if rental is None:
        abort(404)
    reservation = db.get(Reservation, rental.reservation_id)

    try:
        change = complete_rental(reservation.status, rental.status)
    except TransitionError as error:
        db.rollback()
        flash(str(error), "warning")
        return redirect(url_for("admin_rentals.index"))

    returned_at = now()
    late_hours, fee = late_charge(
        rental.expected_return, returned_at, scheduling.current_rates(db).late_fee_per_day
    )

    rental.actual_return = returned_at
    rental.late_hours = late_hours
    rental.late_fee = fee
    rental.total_amount = money(rental.base_amount + rental.additional_fees + fee)
    apply_change(db, reservation, change, rental=rental)

    if fee:
        flash(
            f"Rental {rental.rental_number} was returned {late_hours} hour(s) late. "
            f"A late fee of PHP {fee:,.2f} was added.",
            "warning",
        )
    else:
        flash(f"Rental {rental.rental_number} was returned on time.", "success")
    return redirect(url_for("admin_rentals.index"))
