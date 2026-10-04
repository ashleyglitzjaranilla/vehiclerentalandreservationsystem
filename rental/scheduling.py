"""Where database rows meet the pure domain functions.

`rental/domain/` takes plain values and returns plain values; it imports
neither Flask nor SQLAlchemy, and `scripts/check-domain-purity.py` keeps it
that way. Something has to turn rows into those values, and this is it.

Routes call this module. They never import `rental.domain` directly -- which is
what makes the live preview, the review page and the commit three callers of
one calculation rather than three implementations that drift apart.

This module takes a session and plain arguments, so it can be tested without an
app context. It must not import Flask.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import select

from .domain.availability import Availability, Interval, check
from .domain.pricing import Quote, Rates, quote
from .models import Maintenance, Rental, RentalRates, Reservation, Vehicle

#: A reservation in one of these states holds the slot. "First request holds it"
#: is the reason PENDING is here: an unconfirmed request still blocks others.
BLOCKING_RESERVATION_STATUSES: tuple[str, ...] = ("PENDING", "CONFIRMED")

#: A vehicle that is out on an ACTIVE rental is not available, whatever its
#: reservation says.
BLOCKING_RENTAL_STATUSES: tuple[str, ...] = ("ACTIVE",)

#: What an <input type="datetime-local"> submits.
WINDOW_FORMAT = "%Y-%m-%dT%H:%M"


def parse_window(pickup: str | None, return_: str | None) -> Interval | None:
    """Turn two form values into an Interval, or None when they are unusable.

    Returning None rather than raising is deliberate: a half-filled or
    nonsensical date pair is the normal state of the browse page before the
    customer has chosen anything, not an error to report.
    """
    if not pickup or not return_:
        return None
    try:
        start = datetime.strptime(pickup, WINDOW_FORMAT)
        end = datetime.strptime(return_, WINDOW_FORMAT)
    except ValueError:
        return None
    if end <= start:
        return None
    return Interval(start, end)


def blocked_intervals(
    db, vehicle: Vehicle, *, exclude_reservation_id: int | None = None
) -> list[Interval]:
    """Every window this vehicle is already spoken for.

    Reservations that hold the slot, rentals that are out, and open maintenance
    windows -- which is what `rental/models.py` has always said availability is
    computed from.

    `exclude_reservation_id` leaves out the reservation being re-examined, so a
    booking is never found to conflict with itself. It does not apply to
    maintenance: a workshop window belongs to no reservation.
    """
    reservations = select(Reservation).where(
        Reservation.vehicle_id == vehicle.id,
        Reservation.status.in_(BLOCKING_RESERVATION_STATUSES),
    )
    if exclude_reservation_id is not None:
        reservations = reservations.where(Reservation.id != exclude_reservation_id)

    rentals = select(Rental).where(
        Rental.vehicle_id == vehicle.id,
        Rental.status.in_(BLOCKING_RENTAL_STATUSES),
    )
    if exclude_reservation_id is not None:
        rentals = rentals.where(Rental.reservation_id != exclude_reservation_id)

    blocked = [
        Interval(row.pickup_at, row.return_at) for row in db.scalars(reservations).all()
    ]
    blocked += [
        Interval(row.actual_pickup, row.actual_return or row.expected_return)
        for row in db.scalars(rentals).all()
    ]
    blocked += maintenance_intervals(db, vehicle)
    return blocked


def maintenance_intervals(db, vehicle: Vehicle) -> list[Interval]:
    """Every window this vehicle is off the road for maintenance.

    `Maintenance.blocks_booking` is the definition of "still takes the vehicle
    off the road", so the rows are filtered on that property in Python rather
    than by repeating its rule as a SQL predicate. A vehicle has a handful of
    maintenance records, not a table's worth.

    `Maintenance` stores dates while `Interval` holds datetimes, so the
    conversion is deliberate: **both end dates are inclusive**, meaning the
    whole of the last day is off the road. `Interval` is half-open (start
    inclusive, end exclusive), so the end date is converted to midnight at the
    start of the *following* day. `actual_end_date` wins when it is set -- the
    vehicle came back when it came back, not when it was expected to.
    """
    rows = db.scalars(select(Maintenance).where(Maintenance.vehicle_id == vehicle.id)).all()
    intervals = []
    for row in rows:
        if not row.blocks_booking:
            continue
        last_day = row.actual_end_date or row.expected_end_date
        intervals.append(
            Interval(
                datetime.combine(row.start_date, time.min),
                datetime.combine(last_day + timedelta(days=1), time.min),
            )
        )
    return intervals


def current_rates(db) -> Rates:
    """The one RentalRates row, as the domain's plain-value Rates."""
    row = RentalRates.current(db)
    return Rates(
        additional_driver_fee_per_day=row.additional_driver_fee_per_day,
        insurance_fee_per_day=row.insurance_fee_per_day,
        late_fee_per_day=row.late_fee_per_day,
    )


def availability_for(db, vehicle: Vehicle, interval: Interval) -> Availability:
    """Can this vehicle be booked for this window?

    `vehicle.status` describes the vehicle *right now*. Only MAINTENANCE blocks
    a future window; RESERVED and RENTED are answered by date overlap instead,
    which is why they are normalised away here.

    The status check is now belt-and-braces rather than the only defence: open
    `Maintenance` rows reach `blocked_intervals` as ordinary blocked windows, so
    a workshop vehicle is refused on its dates even if this column were wrong.
    """
    status = vehicle.status if vehicle.status == "MAINTENANCE" else "AVAILABLE"
    return check(
        interval,
        is_active=vehicle.is_active,
        status=status,
        blocked=blocked_intervals(db, vehicle),
    )


def quote_for(
    db,
    vehicle: Vehicle,
    interval: Interval,
    *,
    want_additional_driver: bool,
    want_insurance: bool,
) -> Quote:
    """What this vehicle costs for this window, itemised."""
    return quote(
        interval.start,
        interval.end,
        daily_rate=vehicle.daily_rate,
        hourly_rate=vehicle.hourly_rate,
        rates=current_rates(db),
        want_additional_driver=want_additional_driver,
        want_insurance=want_insurance,
    )
