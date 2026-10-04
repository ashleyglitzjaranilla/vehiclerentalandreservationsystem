"""Turning a chosen window into a reservation.

Every price on every page in this flow comes from `scheduling.quote_for`, and
every verdict from `scheduling.availability_for`. Nothing here re-derives a
figure, which is what keeps the live preview, the review page and the committed
reservation in agreement.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from . import scheduling
from .auth import current_role, current_user, customer_required
from .db import get_session
from .models import Reservation, Vehicle

bp = Blueprint("booking", __name__)


def wants(name: str) -> bool:
    """Read a checkbox from the query string or the form.

    A checkbox that is off is simply absent, so presence is the whole test.
    """
    return request.values.get(name) not in (None, "", "0", "false")


def visible_vehicle(vehicle_id: int) -> Vehicle:
    """Load a vehicle a customer is allowed to see, or 404.

    Matches `public.vehicle_detail`: a disabled vehicle is not part of the
    fleet on offer, but stays reachable for an admin.
    """
    vehicle = get_session().get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    if not vehicle.is_active and current_role() != "admin":
        abort(404)
    return vehicle


@bp.route("/api/quote")
def api_quote():
    """Price one window, as JSON, for the live preview.

    Public on purpose: it prices published rates against a published fleet and
    reveals nothing the detail page does not already show. It reads no session
    and writes nothing.
    """
    vehicle = visible_vehicle(request.args.get("vehicle", type=int) or 0)
    interval = scheduling.parse_window(
        request.args.get("pickup"), request.args.get("return")
    )
    if interval is None:
        return (
            jsonify(
                available=False,
                reason="window",
                message="Choose a pickup date and a return date after it.",
                total=None,
                lines=[],
            ),
            400,
        )

    db = get_session()
    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        return jsonify(
            available=False,
            reason=verdict.reason,
            message=verdict.message,
            total=None,
            lines=[],
        )

    result = scheduling.quote_for(
        db,
        vehicle,
        interval,
        want_additional_driver=wants("driver"),
        want_insurance=wants("insurance"),
    )
    return jsonify(
        available=True,
        reason=None,
        message=None,
        total=str(result.total_amount),
        lines=[[label, detail, str(amount)] for label, detail, amount in result.lines],
    )


def window_from_request(vehicle_id: int):
    """The chosen window, or a redirect back to the vehicle explaining why not."""
    interval = scheduling.parse_window(
        request.values.get("pickup"), request.values.get("return")
    )
    if interval is None:
        flash("Choose a pickup time and a return time after the pickup.", "warning")
        return None, redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))
    return interval, None


def review_url(vehicle_id: int) -> str:
    """The review page for the window currently in the request."""
    return url_for(
        "booking.review",
        vehicle_id=vehicle_id,
        pickup=request.values.get("pickup", ""),
        **{"return": request.values.get("return", "")},
        driver="1" if wants("driver") else "",
        insurance="1" if wants("insurance") else "",
    )


@bp.route("/book/<int:vehicle_id>", methods=["POST"])
def start(vehicle_id: int):
    """Validate the chosen window and send the customer on to review it.

    A signed-out visitor is sent to log in with `next` pointing at the review
    page, so the dates they picked survive the round trip rather than being
    retyped.
    """
    visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    target = review_url(vehicle_id)
    if current_user() is None:
        return redirect(url_for("auth.login", next=target))
    return redirect(target)


@bp.route("/book/<int:vehicle_id>/review")
@customer_required
def review(vehicle_id: int):
    """The itemised quote and the Confirm button. Nothing is written here."""
    vehicle = visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    db = get_session()
    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        flash(verdict.message, "warning")
        return redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))

    return render_template(
        "booking/review.html",
        vehicle=vehicle,
        interval=interval,
        quote=scheduling.quote_for(
            db,
            vehicle,
            interval,
            want_additional_driver=wants("driver"),
            want_insurance=wants("insurance"),
        ),
        pickup=request.args.get("pickup", ""),
        return_=request.args.get("return", ""),
        driver=wants("driver"),
        insurance=wants("insurance"),
    )


@bp.route("/book/<int:vehicle_id>/confirm", methods=["POST"])
@customer_required
def confirm(vehicle_id: int):
    """Create the PENDING reservation, if the window is still free.

    The availability shown on the review page was already stale when the
    customer clicked. Re-checking here, inside the transaction that writes the
    row, under a lock on the vehicle, is what makes "first request holds the
    slot" true rather than merely likely.
    """
    vehicle = visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    db = get_session()
    # Serialises booking attempts for this one vehicle. Postgres honours the
    # lock; SQLite ignores the clause and gets the same guarantee from being
    # single-writer -- which also means no test can exercise any of this.
    #
    # `db.refresh` rather than a discarded `select(...).with_for_update()`: the
    # bare select does lock the row, but it returns the identity-map instance
    # without `populate_existing`, so `availability_for` would go on reading
    # `vehicle.status` and `vehicle.is_active` from the pre-lock snapshot. Same
    # lock, attributes repopulated.
    #
    # The assumed isolation level is READ COMMITTED -- Neon's default, but
    # nothing in this codebase or its config pins it, and the re-check below
    # depends on it: a waiter that acquires the lock must then see the
    # competitor's committed reservation. Under REPEATABLE READ this would raise
    # a serialization failure instead.
    db.refresh(vehicle, with_for_update=True)

    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        db.rollback()
        flash("That vehicle was just booked for those dates. Please pick another window.", "warning")
        return redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))

    driver = wants("driver")
    insurance = wants("insurance")
    # Recomputed here rather than trusted from the form: a posted total is a
    # number the customer controls.
    priced = scheduling.quote_for(
        db, vehicle, interval, want_additional_driver=driver, want_insurance=insurance
    )

    reservation = Reservation(
        user_id=current_user().id,
        vehicle_id=vehicle.id,
        pickup_at=interval.start,
        return_at=interval.end,
        pickup_location=request.form.get("pickup_location", "").strip() or None,
        return_location=request.form.get("return_location", "").strip() or None,
        want_additional_driver=driver,
        want_insurance=insurance,
        rental_hours=priced.duration.hours,
        rental_days=priced.duration.billable_days,
        daily_rate=priced.daily_rate,
        hourly_rate=priced.hourly_rate,
        base_amount=priced.base_amount,
        additional_fees=priced.additional_fees,
        total_amount=priced.total_amount,
        status="PENDING",
    )
    db.add(reservation)
    # flush assigns the id that the reference number is built from.
    db.flush()
    reservation.assign_number()
    db.commit()

    flash(f"Reservation {reservation.reservation_number} was requested.", "success")
    return redirect(url_for("portal.reservation_detail", reservation_id=reservation.id))
