"""Whether a vehicle can be booked for a date range.

Every case here is a date-range question. A vehicle's `status` describes it now;
bookability is a different question, and conflating them is the mistake the
requirements' own worked example is designed to catch.
"""

from __future__ import annotations

from datetime import datetime

from rental.domain.availability import (
    CONFLICT,
    INACTIVE,
    MAINTENANCE,
    Interval,
    check,
    overlaps,
)


def span(d1: int, d2: int) -> Interval:
    """An interval over days in October 2026, at 09:00."""
    return Interval(datetime(2026, 10, d1, 9, 0), datetime(2026, 10, d2, 9, 0))


def ask(requested: Interval, *, is_active=True, status="AVAILABLE", blocked=()):
    return check(requested, is_active=is_active, status=status, blocked=blocked)


# -- the overlap predicate itself ------------------------------------------

def test_the_requirements_worked_example_conflicts():
    """Existing 28 Sep - 2 Oct; new 29 Sep - 1 Oct. Sits inside it."""
    existing = Interval(datetime(2026, 9, 28, 9, 0), datetime(2026, 10, 2, 9, 0))
    new = Interval(datetime(2026, 9, 29, 9, 0), datetime(2026, 10, 1, 9, 0))
    assert overlaps(new, existing) is True


def test_the_requirements_worked_example_does_not_conflict():
    """Same existing booking; new 3 - 6 Oct. Clear of it."""
    existing = Interval(datetime(2026, 9, 28, 9, 0), datetime(2026, 10, 2, 9, 0))
    assert overlaps(span(3, 6), existing) is False


def test_touching_endpoints_do_not_conflict():
    """A rental returning at 10:00 leaves the vehicle bookable from 10:00.

    No turnaround buffer by design -- an admin needing cleaning time confirms
    the next reservation for a later slot.
    """
    assert overlaps(span(3, 6), span(1, 3)) is False   # new starts as old ends
    assert overlaps(span(1, 3), span(3, 6)) is False   # old starts as new ends


def test_containment_conflicts_both_ways():
    assert overlaps(span(2, 3), span(1, 5)) is True    # new inside existing
    assert overlaps(span(1, 5), span(2, 3)) is True    # existing inside new


def test_identical_intervals_conflict():
    assert overlaps(span(1, 3), span(1, 3)) is True


def test_a_one_hour_sliver_of_overlap_conflicts():
    a = Interval(datetime(2026, 10, 1, 9, 0), datetime(2026, 10, 3, 10, 0))
    b = Interval(datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 6, 9, 0))
    assert overlaps(a, b) is True


# -- the check, and its precedence -----------------------------------------

def test_a_clear_vehicle_is_available():
    result = ask(span(3, 6))
    assert result.ok is True
    assert result.reason is None
    assert result.conflicts == ()


def test_no_blocked_intervals_at_all():
    assert ask(span(3, 6), blocked=()).ok is True


def test_a_disabled_vehicle_is_refused_whatever_the_dates():
    result = ask(span(3, 6), is_active=False)
    assert result.ok is False
    assert result.reason == INACTIVE


def test_a_vehicle_under_maintenance_is_refused_whatever_the_dates():
    result = ask(span(3, 6), status="MAINTENANCE")
    assert result.ok is False
    assert result.reason == MAINTENANCE
    assert "maintenance" in result.message.lower()


def test_an_overlapping_booking_is_refused_and_names_the_conflict():
    result = ask(span(2, 4), blocked=[span(1, 3)])
    assert result.ok is False
    assert result.reason == CONFLICT
    assert result.conflicts == (span(1, 3),)


def test_every_overlapping_interval_is_reported():
    result = ask(span(1, 10), blocked=[span(2, 3), span(20, 21), span(5, 6)])
    assert result.conflicts == (span(2, 3), span(5, 6))


def test_a_rented_vehicle_is_still_bookable_outside_its_dates():
    """The heart of the status-versus-availability split.

    A vehicle rented this week is bookable next month. A blanket refusal on
    status would make the requirements' own second worked example fail.
    """
    result = ask(span(20, 22), status="RENTED", blocked=[span(1, 3)])
    assert result.ok is True


def test_inactive_takes_precedence_over_a_date_conflict():
    """The most specific true reason, so the message is not misleading."""
    result = ask(span(2, 4), is_active=False, status="MAINTENANCE", blocked=[span(1, 3)])
    assert result.reason == INACTIVE


def test_maintenance_takes_precedence_over_a_date_conflict():
    result = ask(span(2, 4), status="MAINTENANCE", blocked=[span(1, 3)])
    assert result.reason == MAINTENANCE


def test_every_refusal_carries_a_message_a_customer_can_read():
    for kwargs in ({"is_active": False}, {"status": "MAINTENANCE"}, {"blocked": [span(1, 3)]}):
        result = ask(span(2, 4), **kwargs)
        assert result.ok is False
        assert result.message and result.message[0].isupper()
