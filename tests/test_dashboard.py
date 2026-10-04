"""Regression tests for the Rental Management Dashboard's day window.

The dashboard's "Today's Pickups" and "Today's Returns" tiles must mean today
in Manila (`rental.clock.today()`), not the server's own local date -- on
Vercel the server runs in UTC, so `date.today()` names the wrong day for part
of the Philippine day. That divergence was the one live defect phase 2
existed to fix (see rental/clock.py), yet nothing tested the call site that
actually uses it: reverting rental/admin/dashboard.py's two `today()` calls
back to `datetime.combine(date.today(), ...)` passed all 204 tests.

These tests monkeypatch `rental.admin.dashboard.today` to a fixed date, so if
the dashboard reads the real server clock instead, the counts come out wrong.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from rental.db import get_session
from rental.models import Rental, Reservation, User

FIXED_TODAY = date(2026, 3, 10)
OTHER_DAY = date(2026, 3, 11)


def _stat_value(html: bytes, label: str) -> int:
    """Pull the number shown in the stat-card for the given label.

    Matching by label rather than by digit avoids false positives from the
    page's other stat-values (total vehicles, pending reservations, etc.).
    """
    match = re.search(
        re.escape(label.encode()) + rb"</p>\s*<p class=\"stat-value\">(\d+)</p>",
        html,
    )
    assert match, f"could not find a stat-value for {label!r} in the response"
    return int(match.group(1))


def test_pickups_today_uses_the_clock_not_the_servers_local_date(
    app, admin_client, sample_vehicle, monkeypatch
):
    monkeypatch.setattr("rental.admin.dashboard.today", lambda: FIXED_TODAY)

    with app.app_context():
        db = get_session()
        customer_id = db.query(User).filter_by(username="maria").one().id

        in_window = datetime.combine(FIXED_TODAY, time(9, 0))
        outside_window = datetime.combine(OTHER_DAY, time(9, 0))

        db.add_all(
            [
                Reservation(
                    user_id=customer_id,
                    vehicle_id=sample_vehicle,
                    pickup_at=in_window,
                    return_at=in_window + timedelta(days=1),
                    daily_rate=Decimal("1500.00"),
                    status="CONFIRMED",
                ),
                Reservation(
                    user_id=customer_id,
                    vehicle_id=sample_vehicle,
                    pickup_at=outside_window,
                    return_at=outside_window + timedelta(days=1),
                    daily_rate=Decimal("1500.00"),
                    status="CONFIRMED",
                ),
            ]
        )
        db.commit()

    response = admin_client.get("/admin")
    assert response.status_code == 200
    # Only the in-window reservation should be counted. If the dashboard used
    # date.today() (the real server date, 2026-09-29 as this suite runs)
    # instead of the patched clock, neither pickup falls inside that window
    # and this would read 0, not 1.
    assert _stat_value(response.data, "Today's Pickups") == 1


def test_returns_today_uses_the_clock_not_the_servers_local_date(
    app, admin_client, sample_vehicle, monkeypatch
):
    monkeypatch.setattr("rental.admin.dashboard.today", lambda: FIXED_TODAY)

    with app.app_context():
        db = get_session()
        customer_id = db.query(User).filter_by(username="maria").one().id

        in_window_return = datetime.combine(FIXED_TODAY, time(17, 0))
        outside_window_return = datetime.combine(OTHER_DAY, time(17, 0))

        reservation_a = Reservation(
            user_id=customer_id,
            vehicle_id=sample_vehicle,
            pickup_at=in_window_return - timedelta(days=1),
            return_at=in_window_return,
            daily_rate=Decimal("1500.00"),
            status="CONFIRMED",
        )
        reservation_b = Reservation(
            user_id=customer_id,
            vehicle_id=sample_vehicle,
            pickup_at=outside_window_return - timedelta(days=1),
            return_at=outside_window_return,
            daily_rate=Decimal("1500.00"),
            status="CONFIRMED",
        )
        db.add_all([reservation_a, reservation_b])
        db.commit()

        db.add_all(
            [
                Rental(
                    reservation_id=reservation_a.id,
                    vehicle_id=sample_vehicle,
                    customer_id=customer_id,
                    actual_pickup=reservation_a.pickup_at,
                    expected_return=in_window_return,
                    status="ACTIVE",
                ),
                Rental(
                    reservation_id=reservation_b.id,
                    vehicle_id=sample_vehicle,
                    customer_id=customer_id,
                    actual_pickup=reservation_b.pickup_at,
                    expected_return=outside_window_return,
                    status="ACTIVE",
                ),
            ]
        )
        db.commit()

    response = admin_client.get("/admin")
    assert response.status_code == 200
    # Same guard for returns: only the rental expected back on FIXED_TODAY
    # counts. Reverting to date.today() would query the real system date and
    # miss both rentals, reading 0 instead of 1.
    assert _stat_value(response.data, "Today's Returns") == 1
