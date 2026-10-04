"""Who may reach which page. One table, three kinds of session."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from rental.db import get_session
from rental.models import Vehicle

PUBLIC_PAGES = ["/", "/vehicles"]
ADMIN_PAGES = [
    "/admin",
    "/admin/vehicles",
    "/admin/vehicles/add",
    "/admin/vehicles/search",
    "/admin/rates",
    "/admin/reports",
    "/admin/reports/export.csv",
]
CUSTOMER_PAGES = ["/my"]


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_anonymous_visitors_can_browse_the_storefront(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN_PAGES + CUSTOMER_PAGES)
def test_anonymous_visitors_are_sent_to_login_with_a_next_parameter(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_a_customer_is_refused_every_admin_page(customer_client, path):
    assert customer_client.get(path).status_code == 403


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_an_admin_reaches_every_admin_page(admin_client, path):
    assert admin_client.get(path).status_code == 200


@pytest.mark.parametrize("path", CUSTOMER_PAGES)
def test_an_admin_is_refused_the_customer_portal(admin_client, path):
    assert admin_client.get(path).status_code == 403


@pytest.mark.parametrize("path", CUSTOMER_PAGES)
def test_a_customer_reaches_their_own_portal(customer_client, path):
    assert customer_client.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN_PAGES + CUSTOMER_PAGES)
def test_no_admin_or_portal_page_answers_with_a_trailing_slash_redirect(admin_client, path):
    """A blueprint prefix plus @bp.route("/") registers "/admin/", not "/admin".

    Werkzeug then answers 308 for "/admin", which silently breaks every link and
    every test that expects 200. Empty rules avoid it; this locks that in.
    """
    assert admin_client.get(path).status_code != 308


def test_guest_mode_is_gone(client):
    assert client.post("/guest").status_code == 404


def test_an_admin_reaches_an_admin_guarded_page(admin_client):
    assert admin_client.get("/admin/vehicles").status_code == 200


def test_a_customer_is_refused_an_admin_guarded_page(customer_client):
    assert customer_client.get("/admin/vehicles").status_code == 403


def test_an_anonymous_visitor_is_redirected_with_a_next_parameter(client):
    response = client.get("/admin/vehicles")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]


def test_the_customer_dashboard_greets_them_by_name(customer_client):
    assert b"Welcome, Maria Santos" in customer_client.get("/my").data


def test_the_customer_dashboard_counts_are_real_and_start_at_zero(customer_client, sample_vehicle):
    response = customer_client.get("/my")
    assert b"My Reservations" in response.data
    assert b"Available Vehicles" in response.data
    assert b"Total Rentals" in response.data

    html = response.get_data(as_text=True)
    figures = [v.strip() for v in re.findall(r'stat-value[^>]*>([^<]+)<', html)]
    # Available Vehicles, My Reservations, Active Rental, Total Rentals.
    assert figures == ["1", "0", "0", "0"]


def test_the_customer_dashboard_offers_a_way_into_the_storefront(customer_client):
    assert b"Browse Vehicles" in customer_client.get("/my").data


def test_the_customer_dashboard_has_an_empty_reservations_state(customer_client):
    response = customer_client.get("/my")
    assert b"have any reservations yet" in response.data


def test_the_available_vehicles_count_reflects_only_bookable_vehicles(app, customer_client):
    """Available Vehicles must come from a real query, not a hardcoded number.

    Seeds a fleet where the naive "count everything" answer (6) and the
    naive "count AVAILABLE regardless of is_active" answer (5) both differ
    from the correct answer: active AND status == AVAILABLE (4). One vehicle
    is RESERVED (a real, non-obvious status) and one is AVAILABLE but
    disabled (is_active=False) -- a stray inactive vehicle should not count
    as bookable.
    """
    with app.app_context():
        db = get_session()
        for i in range(4):
            db.add(Vehicle(
                plate_number=f"AVL {1000 + i}", brand="Toyota", model="Vios", year=2024,
                vehicle_type="Sedan", daily_rate=Decimal("1500.00"),
                status="AVAILABLE", is_active=True,
            ))
        db.add(Vehicle(
            plate_number="RES 1000", brand="Toyota", model="Vios", year=2024,
            vehicle_type="Sedan", daily_rate=Decimal("1500.00"),
            status="RESERVED", is_active=True,
        ))
        db.add(Vehicle(
            plate_number="OFF 1000", brand="Toyota", model="Vios", year=2024,
            vehicle_type="Sedan", daily_rate=Decimal("1500.00"),
            status="AVAILABLE", is_active=False,
        ))
        db.commit()

    html = customer_client.get("/my").get_data(as_text=True)

    figures = [v.strip() for v in re.findall(r'stat-value[^>]*>([^<]+)<', html)]
    # Available Vehicles, My Reservations, Active Rental, Total Rentals.
    assert figures[0] == "4"
