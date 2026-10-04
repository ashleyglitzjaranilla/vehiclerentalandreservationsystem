"""The three admin actions that close the loop: confirm, start, return."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from rental.clock import now
from rental.db import get_session
from rental.models import Rental, RentalRates, Reservation, User, Vehicle


@pytest.fixture
def vehicle_id(app):
    with app.app_context():
        db = get_session()
        vehicle = Vehicle(
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
        db.add(vehicle)
        db.commit()
        return vehicle.id


def add_reservation(app, vehicle_id, *, status="PENDING", starts_in_days=1, days=2):
    with app.app_context():
        db = get_session()
        user = db.query(User).filter_by(username="maria").one()
        start = now() + timedelta(days=starts_in_days)
        reservation = Reservation(
            user_id=user.id,
            vehicle_id=vehicle_id,
            pickup_at=start,
            return_at=start + timedelta(days=days),
            pickup_location="Main office",
            return_location="Main office",
            rental_hours=days * 24,
            rental_days=days,
            daily_rate=Decimal("1300.00"),
            base_amount=Decimal("1300.00") * days,
            additional_fees=Decimal("0.00"),
            total_amount=Decimal("1300.00") * days,
            status=status,
        )
        db.add(reservation)
        db.flush()
        reservation.assign_number()
        db.commit()
        return reservation.id


def test_the_queue_shows_an_empty_state_when_nothing_is_waiting(admin_client):
    assert "queue is clear" in admin_client.get("/admin/reservations").get_data(as_text=True).lower()


def test_the_queue_lists_a_pending_request(admin_client, app, vehicle_id):
    add_reservation(app, vehicle_id)

    body = admin_client.get("/admin/reservations").get_data(as_text=True)

    assert "RES-00001" in body
    assert "Maria Santos" in body
    assert "Confirm" in body
    assert "Reject" in body


def test_confirm_moves_the_reservation_and_reserves_the_vehicle(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id)

    assert admin_client.post(f"/admin/reservations/{reservation_id}/confirm").status_code == 302
    with app.app_context():
        db = get_session()
        assert db.get(Reservation, reservation_id).status == "CONFIRMED"
        assert db.get(Vehicle, vehicle_id).status == "RESERVED"


def test_reject_declines_the_request_and_frees_the_vehicle(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id)

    assert admin_client.post(f"/admin/reservations/{reservation_id}/reject").status_code == 302
    with app.app_context():
        db = get_session()
        assert db.get(Reservation, reservation_id).status == "REJECTED"
        assert db.get(Vehicle, vehicle_id).status == "AVAILABLE"


def test_confirming_twice_is_a_message_not_a_500(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")

    response = admin_client.post(
        f"/admin/reservations/{reservation_id}/confirm", follow_redirects=True
    )

    assert response.status_code == 200
    assert "cannot" in response.get_data(as_text=True).lower()
    with app.app_context():
        assert get_session().get(Reservation, reservation_id).status == "CONFIRMED"


def test_a_customer_is_refused_the_queue(customer_client):
    assert customer_client.get("/admin/reservations").status_code == 403


def test_a_customer_cannot_confirm_a_reservation(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id)

    assert customer_client.post(f"/admin/reservations/{reservation_id}/confirm").status_code == 403
    with app.app_context():
        assert get_session().get(Reservation, reservation_id).status == "PENDING"


def test_confirm_404s_on_a_reservation_that_does_not_exist(admin_client):
    assert admin_client.post("/admin/reservations/9999/confirm").status_code == 404


def test_start_creates_an_active_rental_and_sends_the_vehicle_out(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")

    assert admin_client.post(f"/admin/reservations/{reservation_id}/start").status_code == 302
    with app.app_context():
        db = get_session()
        rental = db.query(Rental).one()
        assert rental.status == "ACTIVE"
        assert rental.rental_number == "RNT-00001"
        assert rental.reservation_id == reservation_id
        assert rental.expected_return == db.get(Reservation, reservation_id).return_at
        assert rental.total_amount == Decimal("2600.00")
        # The reservation is not finished until the vehicle comes back.
        assert db.get(Reservation, reservation_id).status == "CONFIRMED"
        assert db.get(Vehicle, vehicle_id).status == "RENTED"


def test_start_is_refused_on_a_pending_reservation(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="PENDING")

    response = admin_client.post(
        f"/admin/reservations/{reservation_id}/start", follow_redirects=True
    )

    assert "CONFIRMED" in response.get_data(as_text=True)
    with app.app_context():
        assert get_session().query(Rental).count() == 0


def test_the_same_reservation_cannot_be_started_twice(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    response = admin_client.post(
        f"/admin/reservations/{reservation_id}/start", follow_redirects=True
    )

    assert "already" in response.get_data(as_text=True).lower()
    with app.app_context():
        assert get_session().query(Rental).count() == 1


def test_a_vehicle_cannot_be_handed_over_twice(admin_client, app, vehicle_id):
    # Two CONFIRMED reservations on one vehicle that do not overlap -- today's
    # and next week's -- so nothing upstream refused them. The vehicle itself is
    # still only one vehicle, and it is already out.
    out_now = add_reservation(app, vehicle_id, status="CONFIRMED")
    next_week = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=10)
    admin_client.post(f"/admin/reservations/{out_now}/start")

    response = admin_client.post(f"/admin/reservations/{next_week}/start", follow_redirects=True)

    assert "already" in response.get_data(as_text=True).lower()
    with app.app_context():
        db = get_session()
        assert db.query(Rental).count() == 1
        assert db.get(Reservation, next_week).status == "CONFIRMED"


def test_start_is_refused_on_a_vehicle_in_maintenance(admin_client, app, vehicle_id):
    """A car in the workshop cannot be handed over, whatever the reservation says."""
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    with app.app_context():
        db = get_session()
        db.get(Vehicle, vehicle_id).status = "MAINTENANCE"
        db.commit()

    response = admin_client.post(
        f"/admin/reservations/{reservation_id}/start", follow_redirects=True
    )

    assert response.status_code == 200
    assert "under maintenance and cannot be handed over" in response.get_data(as_text=True)
    with app.app_context():
        db = get_session()
        assert db.query(Rental).count() == 0
        assert db.get(Reservation, reservation_id).status == "CONFIRMED"
        assert db.get(Vehicle, vehicle_id).status == "MAINTENANCE"


def test_an_on_time_return_closes_everything_with_no_late_fee(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-1)
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    with app.app_context():
        rental_id = get_session().query(Rental).one().id

    assert admin_client.post(f"/admin/rentals/{rental_id}/return").status_code == 302
    with app.app_context():
        db = get_session()
        rental = db.get(Rental, rental_id)
        assert rental.status == "COMPLETED"
        assert rental.actual_return is not None
        assert rental.late_fee == Decimal("0.00")
        assert rental.late_hours == 0
        assert rental.total_amount == Decimal("2600.00")
        assert db.get(Reservation, reservation_id).status == "COMPLETED"
        assert db.get(Vehicle, vehicle_id).status == "AVAILABLE"


def test_a_late_return_adds_the_late_fee_to_the_total(admin_client, app, vehicle_id):
    # Booked for two days ending a day ago: the overrun rounds up to 25 whole
    # hours, which `late_charge` charges as two late days at the fee below.
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-3, days=2)
    with app.app_context():
        db = get_session()
        RentalRates.current(db).late_fee_per_day = Decimal("800.00")
        db.commit()
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    with app.app_context():
        db = get_session()
        rental = db.query(Rental).one()
        rental_id = rental.id
        # The rental started "now"; pin the expected return to the booked one so
        # the overrun is the reservation's, not the clock's.
        rental.expected_return = db.get(Reservation, reservation_id).return_at
        db.commit()

    admin_client.post(f"/admin/rentals/{rental_id}/return")

    with app.app_context():
        rental = get_session().get(Rental, rental_id)
        assert rental.late_hours > 24
        assert rental.late_fee == Decimal("1600.00")  # 2 late days x 800
        assert rental.total_amount == Decimal("4200.00")  # 2600 + 1600


def test_returning_a_completed_rental_is_a_message_not_a_500(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-1)
    admin_client.post(f"/admin/reservations/{reservation_id}/start")
    with app.app_context():
        rental_id = get_session().query(Rental).one().id
    admin_client.post(f"/admin/rentals/{rental_id}/return")

    response = admin_client.post(f"/admin/rentals/{rental_id}/return", follow_redirects=True)

    assert response.status_code == 200
    assert "cannot" in response.get_data(as_text=True).lower()


def test_the_admin_rentals_page_shows_an_empty_state(admin_client):
    assert "No rentals yet" in admin_client.get("/admin/rentals").get_data(as_text=True)


def test_the_admin_rentals_page_lists_an_active_rental(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    body = admin_client.get("/admin/rentals").get_data(as_text=True)

    assert "RNT-00001" in body
    assert "Maria Santos" in body
    assert "Mark returned" in body


def test_a_customer_is_refused_the_admin_rentals_page(customer_client):
    assert customer_client.get("/admin/rentals").status_code == 403
