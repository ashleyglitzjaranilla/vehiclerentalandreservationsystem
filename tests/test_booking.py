"""The booking flow's routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental.db import get_session
from rental.models import Maintenance, RentalRates, Reservation, User, Vehicle

JAN10 = "2026-01-10T09:00"
JAN12 = "2026-01-12T09:00"


@pytest.fixture
def vehicle_id(app):
    """One bookable vehicle with both a daily and an hourly rate."""
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
            hourly_rate=Decimal("200.00"),
            date_acquired=date(2022, 1, 1),
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id


def test_api_quote_prices_a_window_for_an_anonymous_visitor(client, vehicle_id):
    response = client.get(
        f"/api/quote?vehicle={vehicle_id}&pickup={JAN10}&return={JAN12}"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["available"] is True
    assert body["total"] == "2600.00"
    assert body["lines"][0] == ["Base rental", "₱1,300.00 x 2 day(s)", "2600.00"]


def test_api_quote_includes_the_extras_when_asked(client, vehicle_id, app):
    with app.app_context():
        db = get_session()
        rates = RentalRates.current(db)
        rates.additional_driver_fee_per_day = Decimal("250.00")
        rates.insurance_fee_per_day = Decimal("300.00")
        db.commit()

    response = client.get(
        f"/api/quote?vehicle={vehicle_id}&pickup={JAN10}&return={JAN12}"
        "&driver=1&insurance=1"
    )

    assert response.get_json()["total"] == "3700.00"


def test_api_quote_reports_a_conflict_rather_than_a_price(client, vehicle_id, app):
    with app.app_context():
        db = get_session()
        customer = db.query(User).filter_by(username="maria").one()
        db.add(
            Reservation(
                user_id=customer.id,
                vehicle_id=vehicle_id,
                pickup_at=datetime(2026, 1, 10, 9, 0),
                return_at=datetime(2026, 1, 12, 9, 0),
                pickup_location="Main office",
                return_location="Main office",
                daily_rate=Decimal("1300.00"),
                base_amount=Decimal("0.00"),
                additional_fees=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                status="CONFIRMED",
            )
        )
        db.commit()

    body = client.get(
        f"/api/quote?vehicle={vehicle_id}&pickup={JAN10}&return={JAN12}"
    ).get_json()

    assert body["available"] is False
    assert body["reason"] == "conflict"
    assert body["total"] is None
    assert body["message"]


def test_api_quote_rejects_an_unusable_window(client, vehicle_id):
    response = client.get(
        f"/api/quote?vehicle={vehicle_id}&pickup={JAN12}&return={JAN10}"
    )

    assert response.status_code == 400
    assert response.get_json()["message"]


def test_api_quote_404s_on_an_unknown_vehicle(client):
    assert client.get(f"/api/quote?vehicle=9999&pickup={JAN10}&return={JAN12}").status_code == 404


def test_api_quote_404s_on_a_disabled_vehicle(client, vehicle_id, app):
    with app.app_context():
        db = get_session()
        db.get(Vehicle, vehicle_id).is_active = False
        db.commit()

    assert client.get(
        f"/api/quote?vehicle={vehicle_id}&pickup={JAN10}&return={JAN12}"
    ).status_code == 404


def window(**extra) -> dict:
    data = {"pickup": JAN10, "return": JAN12}
    data.update(extra)
    return data


def test_book_sends_a_signed_out_visitor_to_log_in_carrying_the_dates(client, vehicle_id):
    response = client.post(f"/book/{vehicle_id}", data=window())

    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
    # The dates ride inside `next`, so its own "=" and "&" are escaped. Werkzeug
    # leaves ":" alone -- it is legal in a query string.
    assert "pickup%3D2026-01-10T09:00" in response.headers["Location"]
    assert "return%3D2026-01-12T09:00" in response.headers["Location"]


def test_book_sends_a_signed_in_customer_to_review(customer_client, vehicle_id):
    response = customer_client.post(f"/book/{vehicle_id}", data=window())

    assert response.status_code == 302
    assert f"/book/{vehicle_id}/review" in response.headers["Location"]
    assert "pickup=2026-01-10T09:00" in response.headers["Location"]
    assert "return=2026-01-12T09:00" in response.headers["Location"]


def test_book_rejects_an_unusable_window_back_to_the_vehicle(customer_client, vehicle_id):
    response = customer_client.post(
        f"/book/{vehicle_id}", data={"pickup": JAN12, "return": JAN10}, follow_redirects=True
    )

    assert "after the pickup" in response.get_data(as_text=True)


def test_review_shows_the_itemised_quote_and_a_confirm_button(customer_client, vehicle_id):
    body = customer_client.get(
        f"/book/{vehicle_id}/review?pickup={JAN10}&return={JAN12}"
    ).get_data(as_text=True)

    assert "2,600.00" in body
    assert "Base rental" in body
    assert f'action="/book/{vehicle_id}/confirm"' in body


def test_review_requires_a_signed_in_customer(client, vehicle_id):
    response = client.get(f"/book/{vehicle_id}/review?pickup={JAN10}&return={JAN12}")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_confirm_creates_a_pending_reservation_with_the_quote_frozen_onto_it(
    customer_client, vehicle_id, app
):
    response = customer_client.post(
        f"/book/{vehicle_id}/confirm",
        data=window(pickup_location="Main office", return_location="Main office"),
    )

    assert response.status_code == 302
    with app.app_context():
        db = get_session()
        reservation = db.query(Reservation).one()
        assert reservation.status == "PENDING"
        assert reservation.reservation_number == "RES-00001"
        assert reservation.total_amount == Decimal("2600.00")
        assert reservation.daily_rate == Decimal("1300.00")
        assert reservation.rental_days == 2
        assert reservation.pickup_location == "Main office"
        assert f"/my/reservations/{reservation.id}" in response.headers["Location"]


def test_confirm_ignores_a_total_posted_by_the_client(customer_client, vehicle_id, app):
    customer_client.post(
        f"/book/{vehicle_id}/confirm",
        data=window(total_amount="1.00", base_amount="1.00", pickup_location="Main office"),
    )

    with app.app_context():
        assert get_session().query(Reservation).one().total_amount == Decimal("2600.00")


def test_confirm_refuses_a_window_that_was_taken_in_the_meantime(
    customer_client, vehicle_id, app
):
    with app.app_context():
        db = get_session()
        other = db.query(User).filter_by(username="admin").one()
        db.add(
            Reservation(
                user_id=other.id,
                vehicle_id=vehicle_id,
                pickup_at=datetime(2026, 1, 10, 9, 0),
                return_at=datetime(2026, 1, 12, 9, 0),
                pickup_location="Main office",
                return_location="Main office",
                daily_rate=Decimal("1300.00"),
                base_amount=Decimal("0.00"),
                additional_fees=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                status="PENDING",
            )
        )
        db.commit()

    response = customer_client.post(
        f"/book/{vehicle_id}/confirm",
        data=window(pickup_location="Main office"),
        follow_redirects=True,
    )

    assert "just booked" in response.get_data(as_text=True)
    with app.app_context():
        assert get_session().query(Reservation).count() == 1


def test_confirm_refuses_a_window_covered_by_an_open_maintenance_record(
    customer_client, vehicle_id, app
):
    """`Maintenance.blocks_booking` is what stops a booking over workshop dates.

    The vehicle's own status column stays AVAILABLE here on purpose: the open
    maintenance record alone has to be enough.
    """
    with app.app_context():
        db = get_session()
        db.add(
            Maintenance(
                vehicle_id=vehicle_id,
                description="Brake overhaul",
                start_date=date(2026, 1, 11),
                expected_end_date=date(2026, 1, 13),
                status="SCHEDULED",
            )
        )
        db.commit()

    response = customer_client.post(
        f"/book/{vehicle_id}/confirm",
        data=window(pickup_location="Main office"),
        follow_redirects=True,
    )

    assert "just booked" in response.get_data(as_text=True)
    with app.app_context():
        assert get_session().query(Reservation).count() == 0


def test_confirm_refuses_an_unusable_window(customer_client, vehicle_id, app):
    customer_client.post(
        f"/book/{vehicle_id}/confirm", data={"pickup": JAN12, "return": JAN10}
    )

    with app.app_context():
        assert get_session().query(Reservation).count() == 0


def test_an_admin_cannot_book_for_themselves(admin_client, vehicle_id):
    assert admin_client.post(f"/book/{vehicle_id}/confirm", data=window()).status_code == 403
