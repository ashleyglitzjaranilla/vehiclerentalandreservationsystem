"""The public storefront: the landing page, the browse grid and vehicle detail."""

from __future__ import annotations


def test_the_landing_page_sells_the_rental_system(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Rent the Right Vehicle" in response.data
    assert b"Browse Vehicles" in response.data
    assert b"Automatic Calculation" in response.data


def test_the_landing_page_shows_real_vehicles(client, sample_vehicle):
    response = client.get("/")
    assert b"Toyota Hilux" in response.data


def test_the_landing_page_counts_what_is_actually_available(client, sample_vehicle):
    assert b"1 vehicle" in client.get("/").data


def test_browse_lists_active_vehicles_with_their_rate(client, sample_vehicle):
    response = client.get("/vehicles")
    assert response.status_code == 200
    assert b"Toyota Hilux" in response.data
    assert "₱2,200".encode() in response.data


def test_browse_filters_by_type(client, sample_vehicle):
    assert b"Toyota Hilux" in client.get("/vehicles?type=Pickup").data
    assert b"Toyota Hilux" not in client.get("/vehicles?type=Sedan").data


def test_browse_filters_by_transmission_and_seats(client, sample_vehicle):
    assert b"Toyota Hilux" in client.get("/vehicles?transmission=Automatic&seats=5").data
    assert b"Toyota Hilux" not in client.get("/vehicles?transmission=Manual").data
    assert b"Toyota Hilux" not in client.get("/vehicles?seats=7").data


def test_browse_filters_by_rate_range(client, sample_vehicle):
    assert b"Toyota Hilux" in client.get("/vehicles?min_rate=1000&max_rate=3000").data
    assert b"Toyota Hilux" not in client.get("/vehicles?max_rate=1000").data


def test_a_disabled_vehicle_leaves_the_storefront(app, client, sample_vehicle):
    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        db = get_session()
        db.get(Vehicle, sample_vehicle).is_active = False
        db.commit()

    assert b"Toyota Hilux" not in client.get("/vehicles").data


def test_browse_has_an_empty_state_that_offers_a_way_out(client):
    response = client.get("/vehicles?type=Motorcycle")
    assert b"No vehicles match" in response.data
    assert b"Show all vehicles" in response.data


def test_vehicle_detail_shows_the_rental_facts(client, sample_vehicle):
    response = client.get(f"/vehicles/{sample_vehicle}")
    assert response.status_code == 200
    assert b"Toyota Hilux 2021" in response.data
    assert "₱2,200.00".encode() in response.data
    assert b"Automatic" in response.data
    assert b"Diesel" in response.data


def test_a_vehicle_without_a_photo_falls_back_to_its_type_silhouette(client, sample_vehicle):
    response = client.get(f"/vehicles/{sample_vehicle}")
    assert b"img/types/pickup.svg" in response.data


def test_a_vehicle_with_a_photo_uses_it(app, client, sample_vehicle):
    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        db = get_session()
        db.get(Vehicle, sample_vehicle).image_url = "https://example.com/hilux.jpg"
        db.commit()

    assert b"https://example.com/hilux.jpg" in client.get(f"/vehicles/{sample_vehicle}").data


def test_vehicle_detail_quotes_the_fees_from_the_rates_table(app, client, sample_vehicle):
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        db = get_session()
        RentalRates.current(db).insurance_fee_per_day = Decimal("450.00")
        db.commit()

    assert "₱450.00".encode() in client.get(f"/vehicles/{sample_vehicle}").data


def test_a_vehicle_under_maintenance_says_so(app, client, sample_vehicle):
    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        db = get_session()
        db.get(Vehicle, sample_vehicle).status = "MAINTENANCE"
        db.commit()

    assert b"under maintenance" in client.get(f"/vehicles/{sample_vehicle}").data


def test_a_disabled_vehicle_is_hidden_from_visitors_but_not_from_an_admin(
    app, client, admin_client, sample_vehicle
):
    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        db = get_session()
        db.get(Vehicle, sample_vehicle).is_active = False
        db.commit()

    assert client.get(f"/vehicles/{sample_vehicle}").status_code == 404
    assert admin_client.get(f"/vehicles/{sample_vehicle}").status_code == 200


def test_detail_page_shows_no_quote_until_dates_are_chosen(client, sample_vehicle):
    body = client.get(f"/vehicles/{sample_vehicle}").get_data(as_text=True)

    assert "Check availability" in body
    assert "Total" not in body


def test_detail_page_prices_the_chosen_window_without_javascript(client, sample_vehicle):
    body = client.get(
        f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    # The sample vehicle is 2,200.00/day; two days is 4,400.00.
    assert "4,400.00" in body
    assert "Base rental" in body


def test_detail_page_keeps_the_extras_ticked_and_charges_for_them(client, sample_vehicle, app):
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        db = get_session()
        rates = RentalRates.current(db)
        rates.insurance_fee_per_day = Decimal("300.00")
        db.commit()

    body = client.get(
        f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
        "&insurance=1"
    ).get_data(as_text=True)

    assert "5,000.00" in body  # 4,400 + 300 x 2
    assert "Insurance" in body


def test_detail_page_explains_a_conflict_instead_of_pricing_it(client, sample_vehicle, app):
    from datetime import datetime
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import Reservation, User

    with app.app_context():
        db = get_session()
        customer = db.query(User).filter_by(username="maria").one()
        db.add(
            Reservation(
                user_id=customer.id,
                vehicle_id=sample_vehicle,
                pickup_at=datetime(2026, 1, 10, 9, 0),
                return_at=datetime(2026, 1, 12, 9, 0),
                pickup_location="Main office",
                return_location="Main office",
                daily_rate=Decimal("2200.00"),
                base_amount=Decimal("0.00"),
                additional_fees=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                status="PENDING",
            )
        )
        db.commit()

    body = client.get(
        f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    assert "already reserved or rented" in body.lower()
    assert "4,400.00" not in body


def test_detail_page_offers_booking_to_a_signed_out_visitor(client, sample_vehicle):
    body = client.get(
        f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    # The price is public; Book is what sends them to log in (Task 5).
    assert f'action="/book/{sample_vehicle}"' in body


def test_browse_shows_no_per_date_verdict_without_dates(client, sample_vehicle):
    body = client.get("/vehicles").get_data(as_text=True)

    assert "Available for your dates" not in body
    assert "Not available for your dates" not in body


def test_browse_marks_a_free_vehicle_available_for_the_chosen_dates(client, sample_vehicle):
    body = client.get(
        "/vehicles?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    assert "Available for your dates" in body


def test_browse_marks_a_taken_vehicle_unavailable_for_the_chosen_dates(
    client, sample_vehicle, app
):
    from datetime import datetime
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import Reservation, User

    with app.app_context():
        db = get_session()
        customer = db.query(User).filter_by(username="maria").one()
        db.add(
            Reservation(
                user_id=customer.id,
                vehicle_id=sample_vehicle,
                pickup_at=datetime(2026, 1, 10, 9, 0),
                return_at=datetime(2026, 1, 12, 9, 0),
                pickup_location="Main office",
                return_location="Main office",
                daily_rate=Decimal("2200.00"),
                base_amount=Decimal("0.00"),
                additional_fees=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                status="CONFIRMED",
            )
        )
        db.commit()

    body = client.get(
        "/vehicles?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    assert "Not available for your dates" in body


def test_browse_carries_the_dates_into_each_vehicles_link(client, sample_vehicle):
    body = client.get(
        "/vehicles?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    assert f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09%3A00" in body


def test_browse_ignores_a_backwards_window_rather_than_erroring(client, sample_vehicle):
    response = client.get("/vehicles?pickup=2026-01-12T09:00&return=2026-01-10T09:00")

    assert response.status_code == 200
    assert "Available for your dates" not in response.get_data(as_text=True)


def test_the_quote_preview_script_is_served(client):
    response = client.get("/static/js/quote-preview.js")

    assert response.status_code == 200
    assert b"/api/quote" in response.data


def test_the_detail_page_loads_the_quote_preview_script(client, sample_vehicle):
    body = client.get(f"/vehicles/{sample_vehicle}").get_data(as_text=True)

    assert "js/quote-preview.js" in body
    assert "data-quote-panel" in body
    assert f'data-vehicle="{sample_vehicle}"' in body
