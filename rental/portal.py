"""The customer's own area. Every page here is scoped to the signed-in customer."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from sqlalchemy import func, select

from .admin.reservations import apply_change
from .auth import current_user, customer_required
from .clock import now
from .db import get_session
from .domain.lifecycle import TransitionError, cancel_reservation
from .forms import ProfileForm
from .models import Rental, Reservation, User, Vehicle

bp = Blueprint("portal", __name__, url_prefix="/my")


# An empty rule registers exactly "/my"; see admin/dashboard.py.
@bp.route("")
@customer_required
def dashboard():
    """The customer's own summary: what is on offer, and what they have booked.

    Every count is scoped to the signed-in customer. Reservation and rental
    figures are legitimately zero until phase 3 provides a way to create one.
    """
    db = get_session()
    user = current_user()

    available = db.scalar(
        select(func.count())
        .select_from(Vehicle)
        .where(Vehicle.is_active.is_(True))
        .where(Vehicle.status == "AVAILABLE")
    ) or 0
    my_reservations = db.scalar(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.user_id == user.id)
        .where(Reservation.status.in_(["PENDING", "CONFIRMED"]))
    ) or 0
    active_rental = db.scalar(
        select(func.count())
        .select_from(Rental)
        .where(Rental.customer_id == user.id)
        .where(Rental.status == "ACTIVE")
    ) or 0
    total_rentals = db.scalar(
        select(func.count()).select_from(Rental).where(Rental.customer_id == user.id)
    ) or 0

    return render_template(
        "customer/dashboard.html",
        available=available,
        my_reservations=my_reservations,
        active_rental=active_rental,
        total_rentals=total_rentals,
    )


def owned_reservation(reservation_id: int) -> tuple[Reservation, Vehicle]:
    """Load one of the signed-in customer's reservations, with its vehicle, or 404.

    The owner filter is part of the query rather than a check afterwards, so
    there is no path that loads someone else's row at all. A missing row and
    somebody else's row are both 404: a 403 would confirm the record exists.

    The vehicle is joined and returned alongside because the models declare no
    relationships; callers unpack the pair.
    """
    db = get_session()
    row = db.execute(
        select(Reservation, Vehicle)
        .join(Vehicle, Vehicle.id == Reservation.vehicle_id)
        .where(Reservation.id == reservation_id)
        .where(Reservation.user_id == current_user().id)
    ).first()
    if row is None:
        abort(404)
    return row[0], row[1]


@bp.route("/reservations")
@customer_required
def reservations():
    """Every reservation this customer has ever made, newest first."""
    db = get_session()
    rows = db.execute(
        select(Reservation, Vehicle)
        .join(Vehicle, Vehicle.id == Reservation.vehicle_id)
        .where(Reservation.user_id == current_user().id)
        .order_by(Reservation.created_at.desc(), Reservation.id.desc())
    ).all()
    return render_template("customer/reservations.html", reservations=rows)


@bp.route("/reservations/<int:reservation_id>")
@customer_required
def reservation_detail(reservation_id: int):
    """One reservation, with the quote exactly as it was booked."""
    reservation, vehicle = owned_reservation(reservation_id)
    return render_template(
        "customer/reservation_detail.html",
        reservation=reservation,
        vehicle=vehicle,
        can_cancel=can_cancel(reservation),
    )


def owned_rental(rental_id: int) -> tuple[Rental, Vehicle]:
    """Load one of the signed-in customer's rentals, with its vehicle, or 404.

    Copies `owned_reservation`'s shape: the owner filter is part of the query,
    not a check afterwards, and a missing row and somebody else's row are both
    404, never 403.

    Filters on `Rental.customer_id`, not `user_id` -- the rentals table names
    the column differently from the reservations table.
    """
    db = get_session()
    row = db.execute(
        select(Rental, Vehicle)
        .join(Vehicle, Vehicle.id == Rental.vehicle_id)
        .where(Rental.id == rental_id)
        .where(Rental.customer_id == current_user().id)
    ).first()
    if row is None:
        abort(404)
    return row[0], row[1]


@bp.route("/rentals")
@customer_required
def rentals():
    """Every rental this customer has had, newest first."""
    db = get_session()
    rows = db.execute(
        select(Rental, Vehicle)
        .join(Vehicle, Vehicle.id == Rental.vehicle_id)
        .where(Rental.customer_id == current_user().id)
        .order_by(Rental.actual_pickup.desc(), Rental.id.desc())
    ).all()
    return render_template("customer/rentals.html", rentals=rows)


@bp.route("/rentals/<int:rental_id>")
@customer_required
def rental_detail(rental_id: int):
    """One rental, with any late fee shown as its own line.

    A customer seeing a larger total than they booked is owed the reason.
    """
    rental, vehicle = owned_rental(rental_id)
    return render_template("customer/rental_detail.html", rental=rental, vehicle=vehicle)


CANNOT_CANCEL = "This booking can no longer be cancelled online. Please contact the office."


def handed_over(db, reservation: Reservation) -> Rental | None:
    """The rental this reservation's keys were handed over on, if there is one.

    `admin_reservations.start` will hand over a vehicle *before* the booked
    pickup time and leaves the reservation CONFIRMED, so "pickup is still in the
    future" does not mean "the car is still on the lot".
    """
    return db.scalars(select(Rental).where(Rental.reservation_id == reservation.id)).first()


def can_cancel(reservation: Reservation) -> bool:
    """A reservation may be called off before pickup, and only while it is unstarted.

    Cancelling a reservation whose vehicle is already out would be
    unrecoverable: `domain/lifecycle.py` permits no CANCELLED -> COMPLETED
    transition, so the rental could never be closed, no late fee could ever be
    charged, and the vehicle would read AVAILABLE while it was physically out.
    Only a manual database edit would clear it.
    """
    if reservation.status not in ("PENDING", "CONFIRMED"):
        return False
    if reservation.pickup_at <= now():
        return False
    return handed_over(get_session(), reservation) is None


@bp.route("/reservations/<int:reservation_id>/cancel", methods=["POST"])
@customer_required
def cancel(reservation_id: int):
    """Call off a booking and release the vehicle."""
    reservation, vehicle = owned_reservation(reservation_id)
    db = get_session()

    # The same lock `admin_reservations.start` takes, on the same row, so the
    # customer clicking Cancel and the admin clicking Start cannot both win.
    # `db.refresh` rather than a discarded `select(...).with_for_update()`: the
    # bare select locks the row but returns the identity-map instance untouched,
    # so the re-check below would read the pre-lock snapshot.
    # The assumed isolation level is READ COMMITTED -- Neon's default, but
    # nothing in this codebase or its config pins it, and this re-check depends
    # on it: once the lock is acquired, the handover query must see the admin's
    # committed Rental. On SQLite no FOR UPDATE is emitted at all, so no test
    # can exercise the concurrent case; this comment is all a future reader has.
    db.refresh(vehicle, with_for_update=True)
    db.refresh(reservation)

    if reservation.pickup_at <= now() or handed_over(db, reservation) is not None:
        db.rollback()
        flash(CANNOT_CANCEL, "warning")
        return redirect(url_for("portal.reservation_detail", reservation_id=reservation_id))

    try:
        change = cancel_reservation(reservation.status)
    except TransitionError as error:
        # A stale page, not a bug: the booking moved on while it was open.
        db.rollback()
        flash(str(error), "warning")
        return redirect(url_for("portal.reservation_detail", reservation_id=reservation_id))

    # Through `apply_change` rather than writing the two statuses inline: it is
    # the one place a StateChange becomes writes, which is also what keeps the
    # MAINTENANCE guard in a single location.
    apply_change(db, reservation, change)

    flash(f"Reservation {reservation.reservation_number} was cancelled.", "success")
    return redirect(url_for("portal.reservation_detail", reservation_id=reservation_id))


@bp.route("/profile", methods=["GET", "POST"])
@customer_required
def profile():
    """The customer's own contact details."""
    db = get_session()
    user = current_user()
    form = ProfileForm(obj=user)

    if form.validate_on_submit():
        taken = db.scalars(
            select(User).where(User.email == form.email.data).where(User.id != user.id)
        ).first()
        if taken is not None:
            form.email.errors.append("That email address is already in use.")
        else:
            user.full_name = form.full_name.data
            user.email = form.email.data
            user.phone = form.phone.data
            db.commit()
            flash("Your profile was updated.", "success")
            return redirect(url_for("portal.profile"))

    return render_template("customer/profile.html", form=form, user=user)
