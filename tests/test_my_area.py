"""The customer's own pages. Everything here is scoped to the signed-in user."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental.clock import now
from rental.db import get_session
from rental.models import Rental, Reservation, User, Vehicle


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


def add_reservation(app, vehicle_id, *, username="maria", status="PENDING", starts_in_days=7):
    """Insert one reservation and return its id."""
    with app.app_context():
        db = get_session()
        user = db.query(User).filter_by(username=username).one()
        start = now() + timedelta(days=starts_in_days)
        reservation = Reservation(
            user_id=user.id,
            vehicle_id=vehicle_id,
            pickup_at=start,
            return_at=start + timedelta(days=2),
            pickup_location="Main office",
            return_location="Main office",
            rental_hours=48,
            rental_days=2,
            daily_rate=Decimal("1300.00"),
            base_amount=Decimal("2600.00"),
            additional_fees=Decimal("0.00"),
            total_amount=Decimal("2600.00"),
            status=status,
        )
        db.add(reservation)
        db.flush()
        reservation.assign_number()
        db.commit()
        return reservation.id


def test_my_reservations_shows_an_empty_state_with_a_way_forward(customer_client):
    body = customer_client.get("/my/reservations").get_data(as_text=True)

    assert "No reservations yet" in body
    assert "Browse Vehicles" in body


def test_my_reservations_lists_the_customers_own_bookings(customer_client, app, vehicle_id):
    add_reservation(app, vehicle_id)

    body = customer_client.get("/my/reservations").get_data(as_text=True)

    assert "RES-00001" in body
    assert "Mirage" in body
    assert "2,600.00" in body


def test_my_reservations_does_not_list_another_customers_booking(customer_client, app, vehicle_id):
    add_reservation(app, vehicle_id, username="admin")

    assert "RES-00001" not in customer_client.get("/my/reservations").get_data(as_text=True)


def test_reservation_detail_shows_the_frozen_quote(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id)

    body = customer_client.get(f"/my/reservations/{reservation_id}").get_data(as_text=True)

    assert "RES-00001" in body
    assert "2,600.00" in body
    assert "Payment Status" in body
    assert "Pending" in body


def test_reservation_detail_404s_on_another_customers_booking(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, username="admin")

    # 404, not 403: a 403 would confirm the record exists.
    assert customer_client.get(f"/my/reservations/{reservation_id}").status_code == 404


def test_reservation_detail_404s_on_a_reservation_that_does_not_exist(customer_client):
    assert customer_client.get("/my/reservations/9999").status_code == 404


def test_cancel_before_pickup_releases_the_vehicle(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    with app.app_context():
        db = get_session()
        db.get(Vehicle, vehicle_id).status = "RESERVED"
        db.commit()

    response = customer_client.post(f"/my/reservations/{reservation_id}/cancel")

    assert response.status_code == 302
    with app.app_context():
        db = get_session()
        assert db.get(Reservation, reservation_id).status == "CANCELLED"
        assert db.get(Vehicle, vehicle_id).status == "AVAILABLE"


def test_cancel_is_refused_once_pickup_has_passed(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-1)

    response = customer_client.post(
        f"/my/reservations/{reservation_id}/cancel", follow_redirects=True
    )

    assert "contact the office" in response.get_data(as_text=True).lower()
    with app.app_context():
        assert get_session().get(Reservation, reservation_id).status == "CONFIRMED"


def test_the_cancel_button_is_gone_once_pickup_has_passed(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-1)

    body = customer_client.get(f"/my/reservations/{reservation_id}").get_data(as_text=True)

    assert "/cancel" not in body
    assert "contact the office" in body.lower()


def test_cancel_is_refused_once_the_vehicle_has_been_handed_over(
    customer_client, admin_client, app, vehicle_id
):
    """An early collection leaves pickup_at in the future while the car is out.

    Cancelling then would be unrecoverable: the domain permits no
    CANCELLED -> COMPLETED transition, so the rental could never be closed and
    no late fee could ever be charged.
    """
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    assert admin_client.post(f"/admin/reservations/{reservation_id}/start").status_code == 302

    response = customer_client.post(
        f"/my/reservations/{reservation_id}/cancel", follow_redirects=True
    )

    assert response.status_code == 200
    assert "contact the office" in response.get_data(as_text=True).lower()
    with app.app_context():
        db = get_session()
        assert db.get(Reservation, reservation_id).status == "CONFIRMED"
        assert db.query(Rental).one().status == "ACTIVE"
        assert db.get(Vehicle, vehicle_id).status == "RENTED"


def test_the_cancel_button_is_gone_once_the_vehicle_has_been_handed_over(
    customer_client, admin_client, app, vehicle_id
):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    body = customer_client.get(f"/my/reservations/{reservation_id}").get_data(as_text=True)

    assert "/cancel" not in body
    assert "contact the office" in body.lower()


def test_cancelling_leaves_a_vehicle_in_maintenance_in_maintenance(
    customer_client, app, vehicle_id
):
    """The customer-reachable half of the MAINTENANCE release bug.

    Releasing a reservation writes a literal AVAILABLE. A car that went into
    the workshop after the booking was made must not be put back on offer by
    the customer calling the booking off.
    """
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    with app.app_context():
        db = get_session()
        db.get(Vehicle, vehicle_id).status = "MAINTENANCE"
        db.commit()

    response = customer_client.post(f"/my/reservations/{reservation_id}/cancel")

    assert response.status_code == 302
    with app.app_context():
        db = get_session()
        assert db.get(Reservation, reservation_id).status == "CANCELLED"
        assert db.get(Vehicle, vehicle_id).status == "MAINTENANCE"


def test_cancel_404s_on_another_customers_booking(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, username="admin")

    assert customer_client.post(f"/my/reservations/{reservation_id}/cancel").status_code == 404


def test_cancelling_an_already_cancelled_booking_is_a_message_not_a_500(
    customer_client, app, vehicle_id
):
    reservation_id = add_reservation(app, vehicle_id, status="CANCELLED")

    response = customer_client.post(
        f"/my/reservations/{reservation_id}/cancel", follow_redirects=True
    )

    assert response.status_code == 200
    assert "cannot" in response.get_data(as_text=True).lower()


def test_an_admin_is_refused_the_customer_pages(admin_client):
    assert admin_client.get("/my/reservations").status_code == 403


def add_rental(app, vehicle_id, reservation_id, *, username="maria", late_fee=Decimal("0.00")):
    """Insert one rental against an existing reservation and return its id."""
    with app.app_context():
        db = get_session()
        user = db.query(User).filter_by(username=username).one()
        reservation = db.get(Reservation, reservation_id)
        rental = Rental(
            reservation_id=reservation_id,
            vehicle_id=vehicle_id,
            customer_id=user.id,
            actual_pickup=reservation.pickup_at,
            expected_return=reservation.return_at,
            actual_return=reservation.return_at + timedelta(hours=25) if late_fee else None,
            rental_hours=48,
            rental_days=2,
            late_hours=25 if late_fee else 0,
            base_amount=Decimal("2600.00"),
            late_fee=late_fee,
            additional_fees=Decimal("0.00"),
            total_amount=Decimal("2600.00") + late_fee,
            status="COMPLETED" if late_fee else "ACTIVE",
        )
        db.add(rental)
        db.flush()
        rental.assign_number()
        db.commit()
        return rental.id


def test_my_rentals_explains_the_empty_state(customer_client):
    body = customer_client.get("/my/rentals").get_data(as_text=True)

    assert "No rentals yet" in body
    assert "collect" in body.lower()


def test_my_rentals_lists_the_customers_own_rental(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    add_rental(app, vehicle_id, reservation_id)

    body = customer_client.get("/my/rentals").get_data(as_text=True)

    assert "RNT-00001" in body
    assert "Mirage" in body


def test_my_rentals_does_not_list_another_customers_rental(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, username="admin", status="CONFIRMED")
    add_rental(app, vehicle_id, reservation_id, username="admin")

    assert "RNT-00001" not in customer_client.get("/my/rentals").get_data(as_text=True)


def test_rental_detail_itemises_a_late_fee(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    rental_id = add_rental(app, vehicle_id, reservation_id, late_fee=Decimal("1600.00"))

    body = customer_client.get(f"/my/rentals/{rental_id}").get_data(as_text=True)

    assert "Late return" in body
    assert "1,600.00" in body
    assert "4,200.00" in body
    assert "25 hour" in body


def test_rental_detail_404s_on_another_customers_rental(customer_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, username="admin", status="CONFIRMED")
    rental_id = add_rental(app, vehicle_id, reservation_id, username="admin")

    assert customer_client.get(f"/my/rentals/{rental_id}").status_code == 404


def test_profile_shows_the_customers_current_details(customer_client):
    body = customer_client.get("/my/profile").get_data(as_text=True)

    assert "Maria Santos" in body
    assert "maria@example.com" in body
    assert "0917 000 0001" in body


def test_profile_saves_a_change(customer_client, app):
    response = customer_client.post(
        "/my/profile",
        data={
            "full_name": "Maria Cruz",
            "email": "maria.cruz@example.com",
            "phone": "0917 111 2222",
        },
        follow_redirects=True,
    )

    assert "updated" in response.get_data(as_text=True).lower()
    with app.app_context():
        user = get_session().query(User).filter_by(username="maria").one()
        assert user.full_name == "Maria Cruz"
        assert user.email == "maria.cruz@example.com"


def test_profile_rejects_an_email_already_taken_by_someone_else(customer_client, app):
    response = customer_client.post(
        "/my/profile",
        data={"full_name": "Maria Santos", "email": "admin@example.com", "phone": "0917 000 0001"},
    )

    # The form is re-rendered with the error, not redirected and not a 500:
    # asserting only that the stored email is unchanged would pass even if the
    # route did not exist.
    assert response.status_code == 200
    assert "already in use" in response.get_data(as_text=True)
    with app.app_context():
        user = get_session().query(User).filter_by(username="maria").one()
        assert user.email == "maria@example.com"


def test_profile_rejects_a_malformed_email(customer_client, app):
    response = customer_client.post(
        "/my/profile",
        data={"full_name": "Maria Santos", "email": "not-an-email", "phone": "0917 000 0001"},
    )

    assert response.status_code == 200
    assert "valid email" in response.get_data(as_text=True)
    with app.app_context():
        assert get_session().query(User).filter_by(username="maria").one().email == "maria@example.com"


def test_the_customer_navigation_links_to_every_own_page(customer_client):
    body = customer_client.get("/my").get_data(as_text=True)

    assert "/my/reservations" in body
    assert "/my/rentals" in body
    assert "/my/profile" in body
