"""The demo scenario, end to end, through the HTTP layer only.

Nothing here reaches into a route's internals: every step is a request a person
could make in a browser. If this passes, the phase works.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from rental.clock import now
from rental.db import get_session
from rental.models import Rental, RentalRates, Reservation, User, Vehicle

WINDOW_FORMAT = "%Y-%m-%dT%H:%M"


@pytest.fixture
def fleet(app):
    """One bookable vehicle and a late fee to charge against it."""
    with app.app_context():
        db = get_session()
        db.add(
            Vehicle(
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
                date_acquired=date(2022, 1, 1),
            )
        )
        rates = RentalRates.current(db)
        rates.insurance_fee_per_day = Decimal("300.00")
        rates.late_fee_per_day = Decimal("800.00")
        db.commit()
        return db.query(Vehicle).one().id


def test_a_booking_travels_from_browse_to_a_completed_late_rental(
    app, client, customer_client, admin_client, fleet
):
    # The window starts three days ago so the rental can be returned late
    # without any waiting: booked for two days, so it is already overdue.
    pickup = (now() - timedelta(days=3)).replace(second=0, microsecond=0)
    return_at = pickup + timedelta(days=2)
    window = {
        "pickup": pickup.strftime(WINDOW_FORMAT),
        "return": return_at.strftime(WINDOW_FORMAT),
        "insurance": "1",
    }

    # 1. A visitor browses with dates and sees the vehicle offered for them.
    grid = client.get(
        f"/vehicles?pickup={window['pickup']}&return={window['return']}"
    ).get_data(as_text=True)
    assert "Available for your dates" in grid

    # 2. The detail page prices it without any JavaScript: 2 x 1300 + 2 x 300.
    detail = client.get(
        f"/vehicles/{fleet}?pickup={window['pickup']}&return={window['return']}&insurance=1"
    ).get_data(as_text=True)
    assert "3,200.00" in detail

    # 3. The signed-in customer confirms it.
    customer_client.post(
        f"/book/{fleet}/confirm",
        data=dict(window, pickup_location="Main office", return_location="Main office"),
    )
    with app.app_context():
        reservation = get_session().query(Reservation).one()
        reservation_id = reservation.id
        assert reservation.status == "PENDING"
        assert reservation.total_amount == Decimal("3200.00")

    # 4. The same window is now closed to everyone else.
    assert "Not available for your dates" in client.get(
        f"/vehicles?pickup={window['pickup']}&return={window['return']}"
    ).get_data(as_text=True)

    # 5. The admin confirms it, then hands over the keys.
    admin_client.post(f"/admin/reservations/{reservation_id}/confirm")
    admin_client.post(f"/admin/reservations/{reservation_id}/start")
    with app.app_context():
        db = get_session()
        rental = db.query(Rental).one()
        rental_id = rental.id
        assert rental.status == "ACTIVE"
        assert db.get(Vehicle, fleet).status == "RENTED"
        # `start` already set expected_return from the reservation, which is the
        # booked return time -- so the vehicle is already overdue with nothing
        # fabricated. Every step of this test stays an HTTP request.
        assert rental.expected_return == return_at

    # 6. The customer can see it out.
    assert "RNT-00001" in customer_client.get("/my/rentals").get_data(as_text=True)

    # 7. It comes back a day late. 24-48 hours over is 2 late days at 800.
    admin_client.post(f"/admin/rentals/{rental_id}/return")
    with app.app_context():
        db = get_session()
        rental = db.get(Rental, rental_id)
        assert rental.status == "COMPLETED"
        assert rental.late_fee == Decimal("1600.00")
        assert rental.total_amount == Decimal("4800.00")  # 3200 + 1600
        assert db.get(Reservation, reservation_id).status == "COMPLETED"
        assert db.get(Vehicle, fleet).status == "AVAILABLE"

    # 8. The customer sees the larger total, and why.
    page = customer_client.get(f"/my/rentals/{rental_id}").get_data(as_text=True)
    assert "Late return" in page
    assert "1,600.00" in page
    assert "4,800.00" in page

    # 9. The vehicle is bookable again for a future window.
    future = now() + timedelta(days=30)
    assert "Available for your dates" in client.get(
        f"/vehicles?pickup={future.strftime(WINDOW_FORMAT)}"
        f"&return={(future + timedelta(days=1)).strftime(WINDOW_FORMAT)}"
    ).get_data(as_text=True)
