"""Adding, viewing, searching, editing and deleting vehicles."""

from __future__ import annotations

from decimal import Decimal

from rental.db import get_session
from rental.models import Vehicle

NEW_VEHICLE = {
    "plate_number": "  new 9999 ",
    "brand": "Nissan",
    "model": "Navara",
    "year": "2022",
    "vehicle_type": "Pickup",
    "color": "Grey",
    "status": "AVAILABLE",
    "seats": "5",
    "transmission": "Automatic",
    "fuel_type": "Gasoline",
    "daily_rate": "1500.00",
    "hourly_rate": "",
    "image_url": "",
    "date_acquired": "2022-04-01",
    "description": "Bought new.",
}


def test_dashboard_shows_totals(admin_client, sample_vehicle):
    response = admin_client.get("/admin")
    assert response.status_code == 200
    assert b"Rental Management Dashboard" in response.data
    # One vehicle, and it is AVAILABLE, so both those tiles must read 1.
    assert response.data.count(b">1</p>") == 2
    assert b"AVAILABLE" in response.data


def test_add_vehicle_saves_and_normalises_the_plate(app, admin_client):
    response = admin_client.post("/admin/vehicles/add", data=NEW_VEHICLE, follow_redirects=True)
    assert response.status_code == 200
    assert b"Vehicle NEW 9999 was added." in response.data

    with app.app_context():
        vehicle = get_session().query(Vehicle).filter_by(plate_number="NEW 9999").one()
        assert vehicle.brand == "Nissan"
        assert vehicle.year == 2022


def test_add_vehicle_rejects_a_duplicate_plate(admin_client, sample_vehicle):
    data = dict(NEW_VEHICLE, plate_number="ABC 1234")
    response = admin_client.post("/admin/vehicles/add", data=data)
    assert response.status_code == 200
    assert b"already exists" in response.data


def test_add_vehicle_rejects_an_out_of_range_year(admin_client):
    data = dict(NEW_VEHICLE, year="1800")
    response = admin_client.post("/admin/vehicles/add", data=data)
    assert b"Year must be between" in response.data


def test_view_vehicles_lists_the_vehicle(admin_client, sample_vehicle):
    response = admin_client.get("/admin/vehicles")
    assert response.status_code == 200
    assert b"ABC 1234" in response.data
    assert b"Hilux" in response.data


def test_view_vehicles_paginates_at_ten_per_page(app, admin_client):
    with app.app_context():
        db = get_session()
        for number in range(12):
            db.add(
                Vehicle(
                    plate_number=f"PAG {number:04d}",
                    brand="Toyota",
                    model="Vios",
                    year=2020,
                    vehicle_type="Sedan",
                    status="AVAILABLE",
                    daily_rate=Decimal("1500.00"),
                )
            )
        db.commit()

    first_page = admin_client.get("/admin/vehicles?sort=plate&dir=asc")
    assert first_page.data.count(b"PAG ") == 10
    assert b"PAG 0010" not in first_page.data

    second_page = admin_client.get("/admin/vehicles?sort=plate&dir=asc&page=2")
    assert b"PAG 0010" in second_page.data


def test_view_vehicles_sorts_by_year(app, admin_client, sample_vehicle):
    with app.app_context():
        db = get_session()
        db.add(
            Vehicle(
                plate_number="OLD 0001",
                brand="Honda",
                model="Civic",
                year=1999,
                vehicle_type="Sedan",
                status="MAINTENANCE",
                daily_rate=Decimal("1200.00"),
            )
        )
        db.commit()

    ascending = admin_client.get("/admin/vehicles?sort=year&dir=asc").data
    assert ascending.index(b"OLD 0001") < ascending.index(b"ABC 1234")

    descending = admin_client.get("/admin/vehicles?sort=year&dir=desc").data
    assert descending.index(b"ABC 1234") < descending.index(b"OLD 0001")


def test_search_matches_case_insensitive_partial_text(admin_client, sample_vehicle):
    assert b"ABC 1234" in admin_client.get("/admin/vehicles/search?q=toyo").data
    assert b"ABC 1234" in admin_client.get("/admin/vehicles/search?q=hilu").data
    assert b"ABC 1234" in admin_client.get("/admin/vehicles/search?q=abc").data


def test_search_with_no_match_says_so(admin_client, sample_vehicle):
    response = admin_client.get("/admin/vehicles/search?q=zzzzz")
    assert b"No vehicles matched your search." in response.data


def test_search_filters_by_status_and_type(admin_client, sample_vehicle):
    assert b"ABC 1234" in admin_client.get("/admin/vehicles/search?status=AVAILABLE").data
    assert b"ABC 1234" not in admin_client.get("/admin/vehicles/search?status=MAINTENANCE").data
    assert b"ABC 1234" in admin_client.get("/admin/vehicles/search?type=Pickup").data
    assert b"ABC 1234" not in admin_client.get("/admin/vehicles/search?type=Sedan").data


def test_edit_vehicle_prefills_and_saves(app, admin_client, sample_vehicle):
    page = admin_client.get(f"/admin/vehicles/{sample_vehicle}/edit")
    assert page.status_code == 200
    assert b"ABC 1234" in page.data

    data = dict(NEW_VEHICLE, plate_number="ABC 1234", status="MAINTENANCE", color="Blue")
    response = admin_client.post(
        f"/admin/vehicles/{sample_vehicle}/edit", data=data, follow_redirects=True
    )
    assert b"Vehicle ABC 1234 was updated." in response.data

    with app.app_context():
        vehicle = get_session().get(Vehicle, sample_vehicle)
        assert vehicle.status == "MAINTENANCE"
        assert vehicle.color == "Blue"


def test_edit_vehicle_rejects_a_plate_used_by_another_vehicle(app, admin_client, sample_vehicle):
    with app.app_context():
        db = get_session()
        db.add(
            Vehicle(
                plate_number="DUP 0001",
                brand="Ford",
                model="Ranger",
                year=2020,
                vehicle_type="Pickup",
                status="AVAILABLE",
                daily_rate=Decimal("1800.00"),
            )
        )
        db.commit()

    data = dict(NEW_VEHICLE, plate_number="DUP 0001")
    response = admin_client.post(f"/admin/vehicles/{sample_vehicle}/edit", data=data)
    assert b"Another vehicle already uses plate DUP 0001." in response.data


def test_delete_shows_a_confirmation_page_and_does_not_delete_on_get(
    app, admin_client, sample_vehicle
):
    response = admin_client.get(f"/admin/vehicles/{sample_vehicle}/delete")
    assert response.status_code == 200
    assert b"This cannot be undone." in response.data

    with app.app_context():
        assert get_session().get(Vehicle, sample_vehicle) is not None


def test_delete_removes_the_vehicle_on_post(app, admin_client, sample_vehicle):
    response = admin_client.post(f"/admin/vehicles/{sample_vehicle}/delete", follow_redirects=True)
    assert b"Vehicle ABC 1234 was deleted." in response.data

    with app.app_context():
        assert get_session().get(Vehicle, sample_vehicle) is None


def test_missing_vehicle_returns_the_custom_404_page(admin_client):
    response = admin_client.get("/admin/vehicles/999999/edit")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_the_fleet_table_shows_the_daily_rate(admin_client, sample_vehicle):
    assert "₱2,200.00".encode() in admin_client.get("/admin/vehicles").data


def test_adding_a_vehicle_without_a_rate_is_refused(admin_client):
    response = admin_client.post("/admin/vehicles/add", data=dict(NEW_VEHICLE, daily_rate=""))
    assert response.status_code == 200
    assert b"Daily rate is required." in response.data


def test_a_negative_rate_is_refused(app, admin_client):
    response = admin_client.post("/admin/vehicles/add", data=dict(NEW_VEHICLE, daily_rate="-50"))
    assert response.status_code == 200
    assert b"cannot be negative" in response.data

    # The message is not the point -- the point is that nothing was written.
    from sqlalchemy import select

    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        plate = NEW_VEHICLE["plate_number"].strip().upper()
        assert get_session().scalars(select(Vehicle).where(Vehicle.plate_number == plate)).first() is None


def test_a_zero_daily_rate_is_accepted(app, admin_client):
    """Zero is a legitimate rate; DataRequired would reject it as missing."""
    from decimal import Decimal

    from sqlalchemy import select

    from rental.db import get_session
    from rental.models import Vehicle

    admin_client.post("/admin/vehicles/add", data=dict(NEW_VEHICLE, daily_rate="0"))

    with app.app_context():
        plate = NEW_VEHICLE["plate_number"].strip().upper()
        vehicle = get_session().scalars(select(Vehicle).where(Vehicle.plate_number == plate)).one()
        assert vehicle.daily_rate == Decimal("0.00")


def test_the_rates_page_shows_the_current_fees(admin_client):
    response = admin_client.get("/admin/rates")
    assert response.status_code == 200
    assert b"Rental Rates" in response.data
    assert b"500.00" in response.data


def test_saving_new_rates_persists_them(app, admin_client):
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import RentalRates

    response = admin_client.post(
        "/admin/rates",
        data={
            "additional_driver_fee_per_day": "650.00",
            "insurance_fee_per_day": "0",
            "late_fee_per_day": "900.00",
        },
        follow_redirects=True,
    )
    assert b"Rental rates were updated." in response.data

    with app.app_context():
        rates = RentalRates.current(get_session())
        assert rates.additional_driver_fee_per_day == Decimal("650.00")
        # Zero is a legitimate fee -- the form must not treat it as missing.
        assert rates.insurance_fee_per_day == Decimal("0.00")


def test_a_negative_fee_is_refused(app, admin_client):
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        before = RentalRates.current(get_session()).additional_driver_fee_per_day

    response = admin_client.post(
        "/admin/rates",
        data={
            "additional_driver_fee_per_day": "-1",
            "insurance_fee_per_day": "300.00",
            "late_fee_per_day": "800.00",
        },
    )
    assert response.status_code == 200
    assert b"cannot be negative" in response.data

    # The message is not the point -- the point is that nothing was written.
    with app.app_context():
        assert RentalRates.current(get_session()).additional_driver_fee_per_day == before


def test_a_customer_cannot_change_the_rates(app, customer_client):
    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        before = RentalRates.current(get_session()).late_fee_per_day

    assert customer_client.post(
        "/admin/rates",
        data={
            "additional_driver_fee_per_day": "1.00",
            "insurance_fee_per_day": "1.00",
            "late_fee_per_day": "1.00",
        },
    ).status_code == 403

    with app.app_context():
        assert RentalRates.current(get_session()).late_fee_per_day == before


def test_toggle_active_disables_and_re_enables_a_vehicle(app, admin_client, sample_vehicle):
    from rental.db import get_session
    from rental.models import Vehicle

    admin_client.post(f"/admin/vehicles/{sample_vehicle}/toggle-active")
    with app.app_context():
        assert get_session().get(Vehicle, sample_vehicle).is_active is False

    admin_client.post(f"/admin/vehicles/{sample_vehicle}/toggle-active")
    with app.app_context():
        assert get_session().get(Vehicle, sample_vehicle).is_active is True


def test_toggle_active_refuses_a_get(admin_client, sample_vehicle):
    assert admin_client.get(f"/admin/vehicles/{sample_vehicle}/toggle-active").status_code == 405


def test_a_customer_cannot_disable_a_vehicle(customer_client, sample_vehicle):
    assert customer_client.post(
        f"/admin/vehicles/{sample_vehicle}/toggle-active"
    ).status_code == 403


def test_an_admin_still_sees_every_action_control(admin_client, sample_vehicle):
    """Guard against a role flag silently disappearing from the templates.

    Jinja renders an undefined name as falsy rather than raising, so renaming or
    dropping the flag these templates test would hide every action control from
    every admin without a single test failing. Task 6 shipped exactly that bug
    (`is_editor` outlived the context processor that defined it) and it was
    caught by eye, not by the suite -- because the one test covering it had been
    deleted along with guest mode. This is that test, restored.
    """
    listing = admin_client.get("/admin/vehicles").get_data(as_text=True)
    assert "Add Vehicle" in listing
    assert f"/admin/vehicles/{sample_vehicle}/edit" in listing
    assert f"/admin/vehicles/{sample_vehicle}/delete" in listing

    detail = admin_client.get(f"/admin/vehicles/{sample_vehicle}").get_data(as_text=True)
    assert f"/admin/vehicles/{sample_vehicle}/edit" in detail
    assert f"/admin/vehicles/{sample_vehicle}/delete" in detail
    assert f"/admin/vehicles/{sample_vehicle}/toggle-active" in detail


def test_the_admin_dashboard_counts_the_real_fleet(app, admin_client):
    """The cards must reflect real queries, not hardcoded markup.

    The requirements forbid fake static statistics, so this seeds a fleet with a
    deliberately lopsided status mix and asserts the rendered figures match it.
    A template with the numbers baked in would pass a label-only test.
    """
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import Vehicle

    mix = ["AVAILABLE"] * 4 + ["RESERVED"] * 3 + ["RENTED"] * 2 + ["MAINTENANCE"] * 1
    with app.app_context():
        db = get_session()
        for i, status in enumerate(mix):
            db.add(Vehicle(
                plate_number=f"DSH {1000 + i}", brand="Toyota", model="Vios", year=2024,
                vehicle_type="Sedan", daily_rate=Decimal("1500.00"), status=status,
            ))
        db.commit()

    html = admin_client.get("/admin").get_data(as_text=True)

    assert "Rental Management Dashboard" in html
    for label in ["Total Vehicles", "Available", "Reserved", "Currently Rented", "Under Maintenance"]:
        assert label in html

    import re

    figures = [v.strip() for v in re.findall(r'stat-value[^>]*>([^<]+)<', html)]
    # total, available, reserved, rented, maintenance, then the four operations cards
    assert figures[:5] == ["10", "4", "3", "2", "1"]


def test_revenue_is_zero_until_a_rental_completes(admin_client, sample_vehicle):
    assert "₱0.00".encode() in admin_client.get("/admin").data
