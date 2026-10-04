"""The bridge between database rows and phase 2's pure domain functions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental import scheduling
from rental.db import get_session
from rental.domain.availability import CONFLICT, INACTIVE, MAINTENANCE, Interval
from rental.models import Maintenance, Rental, RentalRates, Reservation, User, Vehicle


def make_vehicle(db, **overrides) -> Vehicle:
    fields = dict(
        plate_number="XYZ 9999",
        brand="Mitsubishi",
        model="Mirage",
        year=2022,
        vehicle_type="Sedan",
        status="AVAILABLE",
        seats=5,
        transmission="Automatic",
        fuel_type="Gasoline",
        daily_rate=Decimal("1300.00"),
        hourly_rate=Decimal("200.00"),
        date_acquired=date(2022, 1, 1),
    )
    fields.update(overrides)
    vehicle = Vehicle(**fields)
    db.add(vehicle)
    db.commit()
    return vehicle


def make_reservation(db, vehicle, user, start, end, status) -> Reservation:
    reservation = Reservation(
        user_id=user.id,
        vehicle_id=vehicle.id,
        pickup_at=start,
        return_at=end,
        pickup_location="Main office",
        return_location="Main office",
        daily_rate=vehicle.daily_rate,
        base_amount=Decimal("0.00"),
        additional_fees=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        status=status,
    )
    db.add(reservation)
    db.commit()
    return reservation


JAN10 = datetime(2026, 1, 10, 9, 0)
JAN12 = datetime(2026, 1, 12, 9, 0)
JAN20 = datetime(2026, 1, 20, 9, 0)
JAN22 = datetime(2026, 1, 22, 9, 0)


@pytest.fixture
def seeded(app):
    """A vehicle, a customer, and a live session, inside an app context."""
    with app.app_context():
        db = get_session()
        customer = db.query(User).filter_by(username="maria").one()
        vehicle = make_vehicle(db)
        yield db, vehicle, customer


def test_parse_window_reads_the_datetime_local_format(app):
    interval = scheduling.parse_window("2026-01-10T09:00", "2026-01-12T09:00")
    assert interval == Interval(JAN10, JAN12)


def test_parse_window_returns_none_when_either_side_is_missing_or_junk(app):
    assert scheduling.parse_window(None, "2026-01-12T09:00") is None
    assert scheduling.parse_window("2026-01-10T09:00", None) is None
    assert scheduling.parse_window("", "") is None
    assert scheduling.parse_window("not-a-date", "2026-01-12T09:00") is None


def test_parse_window_returns_none_when_return_is_not_after_pickup(app):
    assert scheduling.parse_window("2026-01-12T09:00", "2026-01-10T09:00") is None
    assert scheduling.parse_window("2026-01-10T09:00", "2026-01-10T09:00") is None


def test_blocked_intervals_includes_pending_and_confirmed(seeded):
    db, vehicle, customer = seeded
    make_reservation(db, vehicle, customer, JAN10, JAN12, "PENDING")
    make_reservation(db, vehicle, customer, JAN20, JAN22, "CONFIRMED")

    assert sorted(scheduling.blocked_intervals(db, vehicle)) == [
        Interval(JAN10, JAN12),
        Interval(JAN20, JAN22),
    ]


def test_blocked_intervals_ignores_cancelled_rejected_and_completed(seeded):
    db, vehicle, customer = seeded
    for status in ("CANCELLED", "REJECTED", "COMPLETED"):
        make_reservation(db, vehicle, customer, JAN10, JAN12, status)

    assert scheduling.blocked_intervals(db, vehicle) == []


def test_blocked_intervals_includes_an_active_rental(seeded):
    db, vehicle, customer = seeded
    reservation = make_reservation(db, vehicle, customer, JAN10, JAN12, "CONFIRMED")
    db.add(
        Rental(
            reservation_id=reservation.id,
            vehicle_id=vehicle.id,
            customer_id=customer.id,
            actual_pickup=JAN10,
            expected_return=JAN12,
            base_amount=Decimal("0.00"),
            late_fee=Decimal("0.00"),
            additional_fees=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            status="ACTIVE",
        )
    )
    db.commit()

    # The reservation and its rental cover the same window, so the vehicle is
    # blocked once for the reservation and once for the rental.
    assert scheduling.blocked_intervals(db, vehicle).count(Interval(JAN10, JAN12)) == 2


def test_blocked_intervals_ignores_a_completed_rental(seeded):
    db, vehicle, customer = seeded
    reservation = make_reservation(db, vehicle, customer, JAN10, JAN12, "COMPLETED")
    db.add(
        Rental(
            reservation_id=reservation.id,
            vehicle_id=vehicle.id,
            customer_id=customer.id,
            actual_pickup=JAN10,
            expected_return=JAN12,
            actual_return=JAN12,
            base_amount=Decimal("0.00"),
            late_fee=Decimal("0.00"),
            additional_fees=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            status="COMPLETED",
        )
    )
    db.commit()

    assert scheduling.blocked_intervals(db, vehicle) == []


def test_blocked_intervals_includes_an_open_maintenance_window(seeded):
    """Dates, inclusive of the last maintenance day, become one blocked Interval."""
    db, vehicle, customer = seeded
    db.add(
        Maintenance(
            vehicle_id=vehicle.id,
            description="Brake overhaul",
            start_date=date(2026, 1, 10),
            expected_end_date=date(2026, 1, 11),
            status="SCHEDULED",
        )
    )
    db.commit()

    # 10 Jan 00:00 up to but not including 12 Jan 00:00: the whole of the 11th
    # is off the road.
    assert scheduling.blocked_intervals(db, vehicle) == [
        Interval(datetime(2026, 1, 10), datetime(2026, 1, 12))
    ]


def test_blocked_intervals_prefers_the_actual_end_date_and_ignores_a_completed_record(seeded):
    db, vehicle, customer = seeded
    db.add(
        Maintenance(
            vehicle_id=vehicle.id,
            description="Came back early",
            start_date=date(2026, 1, 10),
            expected_end_date=date(2026, 1, 20),
            actual_end_date=date(2026, 1, 11),
            status="IN_PROGRESS",
        )
    )
    db.add(
        Maintenance(
            vehicle_id=vehicle.id,
            description="Last year's service",
            start_date=date(2026, 1, 20),
            expected_end_date=date(2026, 1, 22),
            status="COMPLETED",
        )
    )
    db.commit()

    assert scheduling.blocked_intervals(db, vehicle) == [
        Interval(datetime(2026, 1, 10), datetime(2026, 1, 12))
    ]


def test_exclude_reservation_id_drops_only_that_reservation(seeded):
    db, vehicle, customer = seeded
    mine = make_reservation(db, vehicle, customer, JAN10, JAN12, "PENDING")
    make_reservation(db, vehicle, customer, JAN20, JAN22, "PENDING")

    assert scheduling.blocked_intervals(db, vehicle, exclude_reservation_id=mine.id) == [
        Interval(JAN20, JAN22)
    ]


def test_current_rates_maps_the_row_onto_the_domain_value(seeded):
    db, vehicle, customer = seeded
    row = RentalRates.current(db)
    row.additional_driver_fee_per_day = Decimal("250.00")
    row.insurance_fee_per_day = Decimal("300.00")
    row.late_fee_per_day = Decimal("800.00")
    db.commit()

    rates = scheduling.current_rates(db)

    assert rates.additional_driver_fee_per_day == Decimal("250.00")
    assert rates.insurance_fee_per_day == Decimal("300.00")
    assert rates.late_fee_per_day == Decimal("800.00")


def test_availability_for_is_ok_on_a_free_window(seeded):
    db, vehicle, customer = seeded
    assert scheduling.availability_for(db, vehicle, Interval(JAN10, JAN12)).ok


def test_availability_for_reports_a_conflict(seeded):
    db, vehicle, customer = seeded
    make_reservation(db, vehicle, customer, JAN10, JAN12, "CONFIRMED")

    verdict = scheduling.availability_for(db, vehicle, Interval(JAN10 + timedelta(hours=1), JAN12))

    assert not verdict.ok
    assert verdict.reason == CONFLICT


def test_availability_for_reports_inactive_before_anything_else(seeded):
    db, vehicle, customer = seeded
    vehicle.is_active = False
    vehicle.status = "MAINTENANCE"
    db.commit()

    assert scheduling.availability_for(db, vehicle, Interval(JAN10, JAN12)).reason == INACTIVE


def test_availability_for_reports_maintenance(seeded):
    db, vehicle, customer = seeded
    vehicle.status = "MAINTENANCE"
    db.commit()

    assert scheduling.availability_for(db, vehicle, Interval(JAN10, JAN12)).reason == MAINTENANCE


def test_availability_for_ignores_a_reserved_or_rented_status(seeded):
    db, vehicle, customer = seeded
    # RESERVED/RENTED describe the vehicle *right now*; a free future window is
    # still bookable. Only date overlap may block a booking.
    for status in ("RESERVED", "RENTED"):
        vehicle.status = status
        db.commit()
        assert scheduling.availability_for(db, vehicle, Interval(JAN10, JAN12)).ok


def test_quote_for_prices_two_days_with_no_extras(seeded):
    db, vehicle, customer = seeded

    result = scheduling.quote_for(
        db,
        vehicle,
        Interval(JAN10, JAN12),
        want_additional_driver=False,
        want_insurance=False,
    )

    assert result.total_amount == Decimal("2600.00")
    assert result.duration.billable_days == 2


def test_quote_for_adds_the_extras_from_the_rates_row(seeded):
    db, vehicle, customer = seeded
    row = RentalRates.current(db)
    row.additional_driver_fee_per_day = Decimal("250.00")
    row.insurance_fee_per_day = Decimal("300.00")
    db.commit()

    result = scheduling.quote_for(
        db,
        vehicle,
        Interval(JAN10, JAN12),
        want_additional_driver=True,
        want_insurance=True,
    )

    # 2600 base + (250 + 300) x 2 days
    assert result.total_amount == Decimal("3700.00")
    assert [line[0] for line in result.lines] == [
        "Base rental",
        "Additional driver",
        "Insurance",
    ]


def test_quote_for_passes_the_vehicles_own_hourly_rate_through(seeded):
    db, vehicle, customer = seeded

    # 25 hours: one full day plus one extra hour at 200/hour.
    result = scheduling.quote_for(
        db,
        vehicle,
        Interval(JAN10, JAN10 + timedelta(hours=25)),
        want_additional_driver=False,
        want_insurance=False,
    )

    assert result.total_amount == Decimal("1500.00")
