"""The three domain modules, exercised together.

Each module is unit-tested in isolation. This walks the requirements' own demo
scenario end to end -- browse, check, price, confirm, collect, return late --
using only the domain, to prove the pieces compose before phase 3 wires them to
routes. Still no app and no database.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from rental.domain.availability import CONFLICT, Interval, check
from rental.domain.lifecycle import (
    TransitionError,
    complete_rental,
    confirm_reservation,
    start_rental,
)
from rental.domain.pricing import Rates, late_charge, quote

RATES = Rates(
    additional_driver_fee_per_day=Decimal("500.00"),
    insurance_fee_per_day=Decimal("300.00"),
    late_fee_per_day=Decimal("800.00"),
)

# The requirements' scenario: a Toyota Vios at P1,500/day, 28 Sep to 1 Oct.
PICKUP = datetime(2026, 9, 28, 9, 0)
RETURN = datetime(2026, 10, 1, 9, 0)


def test_the_demo_scenario_end_to_end():
    requested = Interval(PICKUP, RETURN)

    # 1. The vehicle is free for those dates.
    availability = check(requested, is_active=True, status="AVAILABLE", blocked=[])
    assert availability.ok is True

    # 2. It prices at exactly what the requirements say.
    priced = quote(PICKUP, RETURN, daily_rate=Decimal("1500.00"), rates=RATES)
    assert priced.duration.billable_days == 3
    assert priced.total_amount == Decimal("4500.00")

    # 3. An admin confirms it; the vehicle is spoken for.
    confirmed = confirm_reservation("PENDING")
    assert confirmed.vehicle_status == "RESERVED"

    # 4. The customer collects it.
    collected = start_rental(confirmed.reservation_status)
    assert collected.vehicle_status == "RENTED"
    assert collected.rental_status == "ACTIVE"

    # 5. They bring it back two days late.
    actual_return = RETURN + timedelta(days=2)
    late_hours, fee = late_charge(RETURN, actual_return, RATES.late_fee_per_day)
    assert (late_hours, fee) == (48, Decimal("1600.00"))

    # 6. Everything closes and the vehicle goes back on the fleet.
    closed = complete_rental(collected.reservation_status, collected.rental_status)
    assert closed.reservation_status == "COMPLETED"
    assert closed.rental_status == "COMPLETED"
    assert closed.vehicle_status == "AVAILABLE"

    # The customer owes the rental plus the late days.
    assert priced.total_amount + fee == Decimal("6100.00")


def test_a_second_customer_is_refused_the_same_dates():
    """The conflict the first booking creates."""
    taken = Interval(PICKUP, RETURN)
    overlapping = Interval(datetime(2026, 9, 29, 9, 0), datetime(2026, 10, 1, 9, 0))

    result = check(overlapping, is_active=True, status="RENTED", blocked=[taken])
    assert result.ok is False
    assert result.reason == CONFLICT
    assert result.conflicts == (taken,)


def test_a_second_customer_may_book_after_it_comes_back():
    """Requirement 9's second worked example, through the real modules."""
    taken = Interval(PICKUP, RETURN)
    later = Interval(datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 6, 9, 0))

    result = check(later, is_active=True, status="RENTED", blocked=[taken])
    assert result.ok is True


def test_the_workflow_cannot_be_skipped():
    """A vehicle cannot be collected against a reservation nobody confirmed."""
    with pytest.raises(TransitionError):
        start_rental("PENDING")


def test_late_charge_rounds_a_partial_day_up_not_down():
    """25 hours late is two late days, not one.

    The demo scenario's own 48-hours-late figure lands exactly on a day
    boundary, so ceil and floor division agree there and the rounding rule
    itself goes unexercised. This picks a return that is late by a partial
    day on top of a whole one, where the two disagree, and states the
    expected peso figure as a literal worked out from late_charge's own
    rules -- not by calling the function under test:

        late_hours = ceil(25 * 3600 / 3600) = 25
        late_days  = ceil(25 / 24) = 2          (floor would give 1)
        fee        = 800.00 x 2 = 1,600.00
    """
    actual_return = RETURN + timedelta(hours=25)
    late_hours, fee = late_charge(RETURN, actual_return, RATES.late_fee_per_day)
    assert late_hours == 25
    assert fee == Decimal("1600.00")
