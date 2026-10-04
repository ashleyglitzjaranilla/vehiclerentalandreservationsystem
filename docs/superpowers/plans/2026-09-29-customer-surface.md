# Phase 3 — The Customer Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer search by date, see a real price, book a vehicle, and follow it through to a completed rental — and let an admin confirm the booking, hand over the keys, and take the vehicle back.

**Architecture:** A new module `rental/scheduling.py` is the only place the ORM meets phase 2's pure domain package: it turns rows into `Interval`/`Rates` values, calls `rental.domain`, and hands back `Availability` and `Quote`. Routes call `scheduling`, never `rental.domain`. The live price preview is one `GET /api/quote` endpoint plus ~40 lines of vanilla JS, so pricing has exactly one implementation. Booking commits under a `SELECT … FOR UPDATE` on the vehicle row with the availability re-checked inside the transaction.

**Tech Stack:** Flask 3, SQLAlchemy 2, Jinja2, Flask-WTF/WTForms, Tailwind CSS v4 (standalone CLI, `output.css` committed), pytest, Python 3.12 under `uv`.

**Source spec:** `docs/superpowers/specs/2026-09-29-customer-surface-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **No new runtime dependencies.** The live preview is vanilla JavaScript; no framework, no build step.
- **`rental/domain/` stays pure**, and `uv run python scripts/check-domain-purity.py` still passes. `scheduling.py` is where the ORM meets the domain, and it is **not** in that package.
- **`rental/scheduling.py` must not import Flask**, `request`, or `session`. It takes a `db` and plain arguments so it is testable without an app context.
- **Money stays `Decimal` through `money()`.** No float touches a price.
- **Every datetime is naive local, from `rental/clock.py`.** Never `datetime.now()`, `datetime.utcnow()` or `date.today()` directly. Verify with:
  `grep -rn 'datetime\.now\|utcnow\|date\.today' rental/ --include=*.py` — every hit must be inside `rental/clock.py`.
- **Tailwind is rebuilt once, at the end** (Task 11), with the documented `SSL_CERT_FILE` workaround, and `rental/static/css/output.css` is committed.
- **No template may live under a directory named** `public`, `static`, `api`, `_next` or `.well-known`. Vercel strips those segments from the function bundle. `tests/test_template_layout.py` enforces this — do not weaken it.
- **Every POST is CSRF-protected** by the app-wide `CSRFProtect(app)` (`rental/__init__.py:43`). Every form template needs
  `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- **Every `/my/` route is `@customer_required`; every `/admin/` route is `@admin_required`.**
- **No fake functionality.** No "Coming soon" buttons, no placeholder numbers. Every figure on every page comes from the database.

### Operational constraints (carried from phase 2)

- **Pin `DATABASE_URL` on any `flask` command you run locally.** Example:
  `DATABASE_URL=sqlite:///rental.db uv run flask --app rental routes`
  An unset `DATABASE_URL` now raises rather than silently creating an empty database (`rental/db.py`).
- **Never pass `--yes` to `flask reset-db`.** It destroys the working database.
- **Count your own tests.** The baseline at the start of this plan is **228 passing**. Every task reports the new total, and the total must only go up.
- Run the suite with `uv run pytest -q`.

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `rental/scheduling.py` | The ORM↔domain bridge: `blocked_intervals`, `current_rates`, `availability_for`, `quote_for`, `parse_window` |
| `rental/booking.py` | Customer booking flow: `/api/quote`, `POST /book/<id>`, review, confirm |
| `rental/admin/reservations.py` | The reservation queue: confirm, reject, start |
| `rental/admin/rentals.py` | The rental list: mark returned |
| `rental/static/js/quote-preview.js` | ~40 lines of vanilla JS driving the live preview |
| `rental/templates/booking/review.html` | The itemised quote and the Confirm button |
| `rental/templates/customer/reservations.html` | My Reservations list + empty state |
| `rental/templates/customer/reservation_detail.html` | One reservation, its quote lines, Cancel |
| `rental/templates/customer/rentals.html` | My Rentals list + empty state |
| `rental/templates/customer/rental_detail.html` | One rental, late fee itemised |
| `rental/templates/customer/profile.html` | Name / phone / email |
| `rental/templates/admin/reservations.html` | The queue + empty state |
| `rental/templates/admin/rentals.html` | Active and completed rentals |
| `rental/templates/partials/_quote_lines.html` | The itemised quote table, shared by four pages |
| `rental/templates/partials/_date_picker.html` | The pickup/return/extras widget, shared by browse and detail |
| `tests/test_scheduling.py` | The bridge, against a seeded database |
| `tests/test_booking.py` | The booking flow's routes, including the ones that must fail |
| `tests/test_my_area.py` | My Reservations / My Rentals / profile, including ownership |
| `tests/test_admin_lifecycle.py` | Confirm, reject, start, return |
| `tests/test_booking_journey.py` | The demo scenario end to end |

**Modified:**

| File | Change |
| --- | --- |
| `rental/__init__.py:11-14,46-52` | Import and register `booking`, `admin_reservations`, `admin_rentals` |
| `rental/auth.py:55` | `next=request.path` → `next=request.full_path` so the dates survive the login round trip |
| `rental/public.py:47,89` | Browse and detail accept `pickup`/`return`/`driver`/`insurance` and render a verdict |
| `rental/portal.py` | Add `reservations`, `reservation_detail`, `cancel`, `rentals`, `rental_detail`, `profile` |
| `rental/forms.py` | Add `ProfileForm` |
| `rental/templates/storefront/browse.html` | Date fields in the filter bar; per-card verdict |
| `rental/templates/storefront/vehicle_detail.html` | The booking widget, server-rendered quote, live preview |
| `rental/templates/layout_public.html` | Nav links for My Reservations / My Rentals / Profile |
| `rental/templates/layout_admin.html` | Nav links for Reservations / Rentals |
| `rental/static/css/output.css` | Rebuilt once in Task 11 |

**Note on `safe_next_page`:** `rental/auth.py` already rejects any `next` that does not start with a single `/`, which blocks `//evil.com` and absolute URLs. The spec's "this phase adds a check that `next` is a relative path" is **already satisfied** — Task 5 only widens `request.path` to `request.full_path` and adds a test pinning both behaviours.

---

### Task 1: `rental/scheduling.py` — the ORM↔domain bridge

**Files:**
- Create: `rental/scheduling.py`
- Test: `tests/test_scheduling.py`

**Interfaces:**
- Consumes: `rental.domain.availability.{Interval, Availability, check}`, `rental.domain.pricing.{Rates, Quote, quote}`, `rental.models.{Vehicle, Reservation, Rental, RentalRates}`, `rental.clock.now`
- Produces — every later task calls only these:
  - `BLOCKING_RESERVATION_STATUSES: tuple[str, ...] = ("PENDING", "CONFIRMED")`
  - `BLOCKING_RENTAL_STATUSES: tuple[str, ...] = ("ACTIVE",)`
  - `parse_window(pickup: str | None, return_: str | None) -> Interval | None`
  - `blocked_intervals(db, vehicle, *, exclude_reservation_id: int | None = None) -> list[Interval]`
  - `current_rates(db) -> Rates`
  - `availability_for(db, vehicle, interval) -> Availability`
  - `quote_for(db, vehicle, interval, *, want_additional_driver: bool, want_insurance: bool) -> Quote`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduling.py`:

```python
"""The bridge between database rows and phase 2's pure domain functions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental import scheduling
from rental.db import get_session
from rental.domain.availability import CONFLICT, INACTIVE, MAINTENANCE, Interval
from rental.models import Rental, RentalRates, Reservation, User, Vehicle


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scheduling.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rental.scheduling'`.

- [ ] **Step 3: Write the implementation**

Create `rental/scheduling.py`:

```python
"""Where database rows meet the pure domain functions.

`rental/domain/` takes plain values and returns plain values; it imports
neither Flask nor SQLAlchemy, and `scripts/check-domain-purity.py` keeps it
that way. Something has to turn rows into those values, and this is it.

Routes call this module. They never import `rental.domain` directly -- which is
what makes the live preview, the review page and the commit three callers of
one calculation rather than three implementations that drift apart.

This module takes a session and plain arguments, so it can be tested without an
app context. It must not import Flask.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from .domain.availability import Availability, Interval, check
from .domain.pricing import Quote, Rates, quote
from .models import Rental, RentalRates, Reservation, Vehicle

#: A reservation in one of these states holds the slot. "First request holds it"
#: is the reason PENDING is here: an unconfirmed request still blocks others.
BLOCKING_RESERVATION_STATUSES: tuple[str, ...] = ("PENDING", "CONFIRMED")

#: A vehicle that is out on an ACTIVE rental is not available, whatever its
#: reservation says.
BLOCKING_RENTAL_STATUSES: tuple[str, ...] = ("ACTIVE",)

#: What an <input type="datetime-local"> submits.
WINDOW_FORMAT = "%Y-%m-%dT%H:%M"


def parse_window(pickup: str | None, return_: str | None) -> Interval | None:
    """Turn two form values into an Interval, or None when they are unusable.

    Returning None rather than raising is deliberate: a half-filled or
    nonsensical date pair is the normal state of the browse page before the
    customer has chosen anything, not an error to report.
    """
    if not pickup or not return_:
        return None
    try:
        start = datetime.strptime(pickup, WINDOW_FORMAT)
        end = datetime.strptime(return_, WINDOW_FORMAT)
    except ValueError:
        return None
    if end <= start:
        return None
    return Interval(start, end)


def blocked_intervals(
    db, vehicle: Vehicle, *, exclude_reservation_id: int | None = None
) -> list[Interval]:
    """Every window this vehicle is already spoken for.

    `exclude_reservation_id` leaves out the reservation being re-examined, so a
    booking is never found to conflict with itself.
    """
    reservations = select(Reservation).where(
        Reservation.vehicle_id == vehicle.id,
        Reservation.status.in_(BLOCKING_RESERVATION_STATUSES),
    )
    if exclude_reservation_id is not None:
        reservations = reservations.where(Reservation.id != exclude_reservation_id)

    rentals = select(Rental).where(
        Rental.vehicle_id == vehicle.id,
        Rental.status.in_(BLOCKING_RENTAL_STATUSES),
    )
    if exclude_reservation_id is not None:
        rentals = rentals.where(Rental.reservation_id != exclude_reservation_id)

    blocked = [
        Interval(row.pickup_at, row.return_at) for row in db.scalars(reservations).all()
    ]
    blocked += [
        Interval(row.actual_pickup, row.actual_return or row.expected_return)
        for row in db.scalars(rentals).all()
    ]
    return blocked


def current_rates(db) -> Rates:
    """The one RentalRates row, as the domain's plain-value Rates."""
    row = RentalRates.current(db)
    return Rates(
        additional_driver_fee_per_day=row.additional_driver_fee_per_day,
        insurance_fee_per_day=row.insurance_fee_per_day,
        late_fee_per_day=row.late_fee_per_day,
    )


def availability_for(db, vehicle: Vehicle, interval: Interval) -> Availability:
    """Can this vehicle be booked for this window?

    `vehicle.status` describes the vehicle *right now*. Only MAINTENANCE blocks
    a future window; RESERVED and RENTED are answered by date overlap instead,
    which is why they are normalised away here.
    """
    status = vehicle.status if vehicle.status == "MAINTENANCE" else "AVAILABLE"
    return check(
        interval,
        is_active=vehicle.is_active,
        status=status,
        blocked=blocked_intervals(db, vehicle),
    )


def quote_for(
    db,
    vehicle: Vehicle,
    interval: Interval,
    *,
    want_additional_driver: bool,
    want_insurance: bool,
) -> Quote:
    """What this vehicle costs for this window, itemised."""
    return quote(
        interval.start,
        interval.end,
        daily_rate=vehicle.daily_rate,
        hourly_rate=vehicle.hourly_rate,
        rates=current_rates(db),
        want_additional_driver=want_additional_driver,
        want_insurance=want_insurance,
    )
```

If `Interval` is not orderable, the `sorted(...)` in
`test_blocked_intervals_includes_pending_and_confirmed` will raise `TypeError`.
In that case add `order=True` to `Interval`'s `@dataclass` decorator in
`rental/domain/availability.py` — it is a frozen value object of two
comparable fields, so ordering is well defined and adds no dependency.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scheduling.py -q`
Expected: 17 passed.

- [ ] **Step 5: Prove the domain is still pure and nothing else broke**

```bash
uv run python scripts/check-domain-purity.py
uv run pytest -q
```
Expected: the purity script prints its OK line and exits 0; the suite is at **245 passed**.

- [ ] **Step 6: Commit**

```bash
git add rental/scheduling.py tests/test_scheduling.py rental/domain/availability.py
git commit -m "feat: add rental/scheduling.py, the bridge from rows to the domain"
```

---

### Task 2: The booking blueprint and `GET /api/quote`

The JSON endpoint the live preview reads. It is public: it prices published
rates against a published fleet and reveals nothing a visitor cannot already
get from the detail page. It takes no session and writes nothing.

**Files:**
- Create: `rental/booking.py`
- Modify: `rental/__init__.py:11` (import), `rental/__init__.py:47` (register)
- Test: `tests/test_booking.py`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: blueprint `booking.bp` (no `url_prefix`), endpoint `booking.api_quote` at `/api/quote`. The JSON shape below is what Task 6's JavaScript reads.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_booking.py`:

```python
"""The booking flow's routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental.db import get_session
from rental.models import RentalRates, Reservation, User, Vehicle

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
    assert body["lines"][0] == ["Base rental", "PHP 1,300.00 x 2 day(s)", "2600.00"]


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_booking.py -q`
Expected: 404s everywhere — `/api/quote` does not exist.

- [ ] **Step 3: Write the implementation**

Create `rental/booking.py`:

```python
"""Turning a chosen window into a reservation.

Every price on every page in this flow comes from `scheduling.quote_for`, and
every verdict from `scheduling.availability_for`. Nothing here re-derives a
figure, which is what keeps the live preview, the review page and the committed
reservation in agreement.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from . import scheduling
from .auth import current_role
from .db import get_session
from .models import Vehicle

bp = Blueprint("booking", __name__)


def wants(name: str) -> bool:
    """Read a checkbox from the query string or the form.

    A checkbox that is off is simply absent, so presence is the whole test.
    """
    return request.values.get(name) not in (None, "", "0", "false")


def visible_vehicle(vehicle_id: int) -> Vehicle:
    """Load a vehicle a customer is allowed to see, or 404.

    Matches `public.vehicle_detail`: a disabled vehicle is not part of the
    fleet on offer, but stays reachable for an admin.
    """
    vehicle = get_session().get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    if not vehicle.is_active and current_role() != "admin":
        abort(404)
    return vehicle


@bp.route("/api/quote")
def api_quote():
    """Price one window, as JSON, for the live preview.

    Public on purpose: it prices published rates against a published fleet and
    reveals nothing the detail page does not already show. It reads no session
    and writes nothing.
    """
    vehicle = visible_vehicle(request.args.get("vehicle", type=int) or 0)
    interval = scheduling.parse_window(
        request.args.get("pickup"), request.args.get("return")
    )
    if interval is None:
        return (
            jsonify(
                available=False,
                reason="window",
                message="Choose a pickup date and a return date after it.",
                total=None,
                lines=[],
            ),
            400,
        )

    db = get_session()
    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        return jsonify(
            available=False,
            reason=verdict.reason,
            message=verdict.message,
            total=None,
            lines=[],
        )

    result = scheduling.quote_for(
        db,
        vehicle,
        interval,
        want_additional_driver=wants("driver"),
        want_insurance=wants("insurance"),
    )
    return jsonify(
        available=True,
        reason=None,
        message=None,
        total=str(result.total_amount),
        lines=[[label, detail, str(amount)] for label, detail, amount in result.lines],
    )
```

- [ ] **Step 4: Register the blueprint**

In `rental/__init__.py`, add `booking` to the existing `from . import` line (line 11) so it reads:

```python
from . import auth, booking, cli, db, portal, public, reports
```

and register it immediately after `public` (line 47):

```python
    app.register_blueprint(public.bp)
    app.register_blueprint(booking.bp)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_booking.py -q`
Expected: 6 passed.

If `test_api_quote_prices_a_window_for_an_anonymous_visitor` fails on the
`lines[0]` detail string, print the actual value and copy it into the test —
`_peso` in `rental/domain/pricing.py` owns that formatting, and the test must
match it rather than the other way round.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: **251 passed**.

- [ ] **Step 7: Commit**

```bash
git add rental/booking.py rental/__init__.py tests/test_booking.py
git commit -m "feat: add GET /api/quote, the one price the whole flow reads"
```

---

### Task 3: The date-aware vehicle detail page

The booking widget, the server-rendered verdict, and the itemised quote. No
JavaScript yet — Task 6 layers the live preview on top of a page that already
works without it.

**Files:**
- Create: `rental/templates/partials/_date_picker.html`, `rental/templates/partials/_quote_lines.html`
- Modify: `rental/public.py:89-113` (`vehicle_detail`), `rental/templates/storefront/vehicle_detail.html`
- Test: `tests/test_public.py` (append)

**Interfaces:**
- Consumes: `scheduling.parse_window`, `scheduling.availability_for`, `scheduling.quote_for`, `booking.wants`
- Produces:
  - Macro `date_picker(action, vehicle_id, pickup, return_, driver, insurance, submit_label)` in `partials/_date_picker.html`
  - Macro `quote_lines(quote)` in `partials/_quote_lines.html` — used unchanged by Tasks 5, 7 and 9
  - `vehicle_detail` passes `interval`, `verdict`, `quote`, `pickup`, `return_`, `driver`, `insurance` to the template.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_public.py`:

```python
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

    assert "already booked" in body.lower()
    assert "4,400.00" not in body


def test_detail_page_offers_booking_to_a_signed_out_visitor(client, sample_vehicle):
    body = client.get(
        f"/vehicles/{sample_vehicle}?pickup=2026-01-10T09:00&return=2026-01-12T09:00"
    ).get_data(as_text=True)

    # The price is public; Book is what sends them to log in (Task 5).
    assert f'action="/book/{sample_vehicle}"' in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_public.py -q -k detail_page`
Expected: FAIL — "Check availability" is absent and the page still says "Online booking opens soon."

- [ ] **Step 3: Write the two partials**

Create `rental/templates/partials/_date_picker.html`:

```jinja
{# The pickup/return/extras widget. One definition, used by the detail page and
   the browse filter bar, so a customer sees the same control in both places.

   `action` is where the form posts or gets. On the detail page it is
   /book/<id> (POST); on browse it is the browse URL itself (GET). #}
{% macro date_picker(action, method, vehicle_id, pickup, return_, driver, insurance, submit_label) %}
<form method="{{ method }}" action="{{ action }}" data-quote-form
      {% if vehicle_id %}data-vehicle="{{ vehicle_id }}"{% endif %}>
  {% if method == 'post' %}
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  {% endif %}
  <div class="grid gap-3 sm:grid-cols-2">
    <div>
      <label class="field-label" for="pickup">Pickup</label>
      <input class="field" type="datetime-local" id="pickup" name="pickup"
             value="{{ pickup or '' }}" required>
    </div>
    <div>
      <label class="field-label" for="return">Return</label>
      <input class="field" type="datetime-local" id="return" name="return"
             value="{{ return_ or '' }}" required>
    </div>
  </div>
  <div class="mt-3 space-y-2 text-sm text-ink">
    <label class="flex items-center gap-2">
      <input type="checkbox" name="driver" value="1" {% if driver %}checked{% endif %}>
      <span>Additional driver</span>
    </label>
    <label class="flex items-center gap-2">
      <input type="checkbox" name="insurance" value="1" {% if insurance %}checked{% endif %}>
      <span>Insurance</span>
    </label>
  </div>
  <button type="submit" class="btn btn-primary mt-4 w-full">{{ submit_label }}</button>
</form>
{% endmacro %}
```

Create `rental/templates/partials/_quote_lines.html`:

```jinja
{# One itemised quote, rendered the same way on the detail page, the review
   page, the reservation detail and the rental detail. The figures come from
   `scheduling.quote_for`; nothing here does arithmetic. #}
{% macro quote_lines(quote) %}
<table class="w-full text-sm">
  <tbody>
    {% for label, detail, amount in quote.lines %}
      <tr class="border-b border-line last:border-0">
        <td class="py-2">
          <span class="font-medium text-ink">{{ label }}</span>
          <span class="block text-xs text-muted">{{ detail }}</span>
        </td>
        <td class="py-2 text-right font-semibold text-ink">
          ₱{{ '{:,.2f}'.format(amount) }}
        </td>
      </tr>
    {% endfor %}
    <tr>
      <td class="pt-3 text-sm font-semibold text-ink">Total</td>
      <td class="pt-3 text-right">
        <span class="rate" data-quote-total>₱{{ '{:,.2f}'.format(quote.total_amount) }}</span>
      </td>
    </tr>
  </tbody>
</table>
{% endmacro %}
```

- [ ] **Step 4: Teach `vehicle_detail` about dates**

In `rental/public.py`, add the imports at the top:

```python
from . import scheduling
from .booking import wants
```

Then replace the body of `vehicle_detail` after the `abort(404)` guards with:

```python
    pickup = request.args.get("pickup", "")
    return_ = request.args.get("return", "")
    interval = scheduling.parse_window(pickup, return_)
    driver = wants("driver")
    insurance = wants("insurance")

    verdict = None
    quote = None
    if interval is not None:
        verdict = scheduling.availability_for(db, vehicle, interval)
        if verdict.ok:
            quote = scheduling.quote_for(
                db,
                vehicle,
                interval,
                want_additional_driver=driver,
                want_insurance=insurance,
            )

    return render_template(
        "storefront/vehicle_detail.html",
        vehicle=vehicle,
        rates=RentalRates.current(db),
        pickup=pickup,
        return_=return_,
        driver=driver,
        insurance=insurance,
        verdict=verdict,
        quote=quote,
    )
```

An import cycle is possible here: `rental/booking.py` imports from
`rental/scheduling.py` and `rental/auth.py`, and `rental/public.py` would now
import from `rental/booking.py`. `booking.py` does not import `public`, so
there is no cycle — but if one appears, move `wants` into `rental/scheduling.py`
is **not** the fix (it would put Flask's `request` in a Flask-free module).
Move it to a new tiny helper in `rental/public.py` and have `booking.py` import
it from there instead.

- [ ] **Step 5: Replace the sidebar of `storefront/vehicle_detail.html`**

Add the two imports beside the existing one at the top of the file:

```jinja
{% from 'partials/_date_picker.html' import date_picker %}
{% from 'partials/_quote_lines.html' import quote_lines %}
```

Replace the whole `{% if is_customer %} … {% endif %}` block at the end of the
sidebar card with:

```jinja
      <div class="mt-5 border-t border-line pt-4">
        {{ date_picker(url_for('booking.start', vehicle_id=vehicle.id), 'post',
                       vehicle.id, pickup, return_, driver, insurance,
                       'Check availability' if not quote else 'Book this vehicle') }}
      </div>

      <div class="mt-4" data-quote-panel>
        {% if verdict and not verdict.ok %}
          <div class="alert alert-warning">
            <span>{{ verdict.message }}</span>
          </div>
        {% elif quote %}
          <div class="border-t border-line pt-4">
            {{ quote_lines(quote) }}
          </div>
        {% endif %}
      </div>

      {% if not current_user %}
        <p class="mt-3 text-xs text-muted">
          You will be asked to log in before the booking is confirmed.
        </p>
      {% endif %}
```

`booking.start` is the `POST /book/<vehicle_id>` endpoint that Task 5 creates.
Until then `url_for` will raise `BuildError`, so **Task 3's tests will not pass
in isolation**. Add the placeholder route now, at the bottom of
`rental/booking.py`, so this task is independently testable:

```python
@bp.route("/book/<int:vehicle_id>", methods=["POST"])
def start(vehicle_id: int):
    """Validate the chosen window and send the customer to review it.

    Task 5 fills this in. It exists here so the detail page's form has a real
    target from the moment the form is rendered.
    """
    visible_vehicle(vehicle_id)
    abort(501)
```

Also delete the now-dead "Currently unavailable" block only if `verdict`
already says the same thing — it does not, because `verdict` is None with no
dates chosen. **Keep it.**

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_public.py -q`
Expected: every test in the file passes, including the five new ones.

If `test_detail_page_explains_a_conflict_instead_of_pricing_it` fails on the
phrase "already booked", read the actual message from
`rental/domain/availability.py` and change the assertion to a distinctive
substring of the real message. Never change the domain message to suit a test.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: **256 passed**.

- [ ] **Step 8: Commit**

```bash
git add rental/public.py rental/booking.py rental/templates/partials/_date_picker.html \
        rental/templates/partials/_quote_lines.html \
        rental/templates/storefront/vehicle_detail.html tests/test_public.py
git commit -m "feat: price the chosen window on the vehicle detail page"
```

---

### Task 4: The date-aware browse grid

With no dates chosen, every bookable vehicle reads as available and the status
badge is informational. With dates chosen, each card answers for **those**
dates.

**Files:**
- Modify: `rental/public.py:47-87` (`browse`), `rental/templates/storefront/browse.html`, `rental/templates/partials/_vehicle_card.html`
- Test: `tests/test_public.py` (append)

**Interfaces:**
- Consumes: `scheduling.parse_window`, `scheduling.availability_for`
- Produces: `browse` passes `pickup`, `return_`, `driver`, `insurance` and `verdicts` (a `dict[int, Availability]`, empty when no window is chosen) to the template. `vehicle_card(vehicle, verdict=None, window='')` gains two optional arguments — existing callers are unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_public.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_public.py -q -k browse`
Expected: the three "for your dates" tests fail; the two negative ones pass for
the wrong reason (nothing renders a verdict yet). That is expected — they are
there to stay green afterwards.

- [ ] **Step 3: Extend `browse` in `rental/public.py`**

After the existing `vehicles, page, total_pages, total = paginate(...)` line, add:

```python
    pickup = request.args.get("pickup", "")
    return_ = request.args.get("return", "")
    interval = scheduling.parse_window(pickup, return_)
    driver = wants("driver")
    insurance = wants("insurance")

    # Only the page's own vehicles are checked -- a verdict per row on the
    # whole fleet would be a query per vehicle for rows nobody is looking at.
    verdicts = (
        {v.id: scheduling.availability_for(db, v, interval) for v in vehicles}
        if interval is not None
        else {}
    )
```

`browse` does not currently open a session. Add `db = get_session()` at the top
of the function, beside the existing argument parsing.

Add these to the `render_template` call:

```python
        pickup=pickup,
        return_=return_,
        driver=driver,
        insurance=insurance,
        verdicts=verdicts,
```

and include the dates in `filtered` so the Clear button appears when only dates
are set:

```python
        filtered=bool(
            vehicle_type or transmission or seats or min_rate or max_rate
            or pickup or return_
        ),
```

- [ ] **Step 4: Show the verdict on each card**

In `rental/templates/partials/_vehicle_card.html`, change the macro signature to:

```jinja
{% macro vehicle_card(vehicle, verdict=None, window='') %}
```

and insert this immediately after the closing `</div>` of the type/year block:

```jinja
    {% if verdict %}
      {% if verdict.ok %}
        <p class="pill pill-success">Available for your dates</p>
      {% else %}
        <p class="pill pill-warning">Not available for your dates</p>
      {% endif %}
    {% endif %}
```

Find the card's existing link to the detail page and append the window to it:

```jinja
href="{{ url_for('public.vehicle_detail', vehicle_id=vehicle.id) }}{{ window }}"
```

`pill-success` and `pill-warning` must already exist in the stylesheet. Check:

```bash
grep -n 'pill-success\|pill-warning' rental/static/src/input.css
```

If either is missing, add it beside the existing `pill-*` rules in
`input.css` following their exact shape. Tailwind silently drops a class it
does not know, so a missing rule fails as invisible styling, not as an error.

- [ ] **Step 5: Pass the verdict and the window in `browse.html`**

Add the date picker's two fields to the filter form's grid — change
`lg:grid-cols-5` to `lg:grid-cols-7` and add, before the Type field:

```jinja
    <div>
      <label class="field-label" for="pickup">Pickup</label>
      <input class="field" type="datetime-local" id="pickup" name="pickup" value="{{ pickup }}">
    </div>
    <div>
      <label class="field-label" for="return">Return</label>
      <input class="field" type="datetime-local" id="return" name="return" value="{{ return_ }}">
    </div>
```

Above the grid loop, build the query suffix once:

```jinja
{% set window = ('?pickup=' ~ pickup | urlencode ~ '&return=' ~ return_ | urlencode) if pickup and return_ else '' %}
```

and change the loop to:

```jinja
      {{ vehicle_card(vehicle, verdicts.get(vehicle.id), window) }}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_public.py -q`
Expected: all pass, including the five new browse tests.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: **261 passed**.

- [ ] **Step 8: Commit**

```bash
git add rental/public.py rental/templates/storefront/browse.html \
        rental/templates/partials/_vehicle_card.html rental/static/src/input.css \
        tests/test_public.py
git commit -m "feat: answer the browse grid for the customer's chosen dates"
```

---

### Task 5: Book, review, confirm — and the login round trip

The load-bearing task. A logged-out visitor who clicks Book lands on the login
page, comes back to the same vehicle with the same dates, and confirms. The
commit re-checks availability **inside** the transaction, under a row lock.

**Files:**
- Modify: `rental/booking.py`, `rental/auth.py:55`
- Create: `rental/templates/booking/review.html`
- Test: `tests/test_booking.py` (append), `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - `booking.start` — `POST /book/<vehicle_id>`
  - `booking.review` — `GET /book/<vehicle_id>/review`
  - `booking.confirm` — `POST /book/<vehicle_id>/confirm`
  - A `Reservation` row in status `PENDING` with `reservation_number` assigned. Tasks 7 and 8 read it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_booking.py`:

```python
def window(**extra) -> dict:
    data = {"pickup": JAN10, "return": JAN12}
    data.update(extra)
    return data


def test_book_sends_a_signed_out_visitor_to_log_in_carrying_the_dates(client, vehicle_id):
    response = client.post(f"/book/{vehicle_id}", data=window())

    assert response.status_code == 302
    assert "/login?next=" in response.headers["Location"]
    assert "2026-01-10T09%3A00" in response.headers["Location"]


def test_book_sends_a_signed_in_customer_to_review(customer_client, vehicle_id):
    response = customer_client.post(f"/book/{vehicle_id}", data=window())

    assert response.status_code == 302
    assert f"/book/{vehicle_id}/review" in response.headers["Location"]
    assert "pickup=2026-01-10T09%3A00" in response.headers["Location"]


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


def test_confirm_refuses_an_unusable_window(customer_client, vehicle_id, app):
    customer_client.post(
        f"/book/{vehicle_id}/confirm", data={"pickup": JAN12, "return": JAN10}
    )

    with app.app_context():
        assert get_session().query(Reservation).count() == 0


def test_an_admin_cannot_book_for_themselves(admin_client, vehicle_id):
    assert admin_client.post(f"/book/{vehicle_id}/confirm", data=window()).status_code == 403
```

Append to `tests/test_auth.py`:

```python
def test_login_redirect_preserves_the_query_string_of_the_page_asked_for(client):
    response = client.get("/my/reservations")

    assert response.status_code == 302
    assert "next=%2Fmy%2Freservations" in response.headers["Location"]


def test_login_refuses_to_bounce_to_another_site(client):
    response = client.post(
        "/login?next=//evil.example.com",
        data={"username": "maria", "password": CUSTOMER_PASSWORD},
    )

    assert response.headers["Location"] == "/my"
```

`CUSTOMER_PASSWORD` is already importable from `tests/conftest.py`; add it to
the file's existing import from conftest, or use the literal `"secret123"` if
`tests/test_auth.py` already does so.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_booking.py tests/test_auth.py -q`
Expected: the new booking tests fail with 501 or `BuildError`;
`test_login_refuses_to_bounce_to_another_site` **passes already** —
`safe_next_page` in `rental/auth.py` has blocked that since phase 1. It is
here to keep it blocked.

- [ ] **Step 3: Widen the login redirect to carry the query string**

In `rental/auth.py`, line 55, change:

```python
        return redirect(url_for("auth.login", next=request.path))
```

to:

```python
        # full_path, not path: a customer sent to log in from a priced booking
        # window must come back to that same window, dates intact.
        return redirect(url_for("auth.login", next=request.full_path))
```

`request.full_path` always ends in `?` even with no query string, which is
harmless — it is still a relative path and `safe_next_page` accepts it.

- [ ] **Step 4: Write the three routes**

Replace the placeholder `start` at the bottom of `rental/booking.py` with:

```python
def window_from_request(vehicle_id: int):
    """The chosen window, or a redirect back to the vehicle explaining why not."""
    interval = scheduling.parse_window(
        request.values.get("pickup"), request.values.get("return")
    )
    if interval is None:
        flash("Choose a pickup time and a return time after the pickup.", "warning")
        return None, redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))
    return interval, None


def review_url(vehicle_id: int) -> str:
    """The review page for the window currently in the request."""
    return url_for(
        "booking.review",
        vehicle_id=vehicle_id,
        pickup=request.values.get("pickup", ""),
        **{"return": request.values.get("return", "")},
        driver="1" if wants("driver") else "",
        insurance="1" if wants("insurance") else "",
    )


@bp.route("/book/<int:vehicle_id>", methods=["POST"])
def start(vehicle_id: int):
    """Validate the chosen window and send the customer on to review it.

    A signed-out visitor is sent to log in with `next` pointing at the review
    page, so the dates they picked survive the round trip rather than being
    retyped.
    """
    visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    target = review_url(vehicle_id)
    if current_user() is None:
        return redirect(url_for("auth.login", next=target))
    return redirect(target)


@bp.route("/book/<int:vehicle_id>/review")
@customer_required
def review(vehicle_id: int):
    """The itemised quote and the Confirm button. Nothing is written here."""
    vehicle = visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    db = get_session()
    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        flash(verdict.message, "warning")
        return redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))

    return render_template(
        "booking/review.html",
        vehicle=vehicle,
        interval=interval,
        quote=scheduling.quote_for(
            db,
            vehicle,
            interval,
            want_additional_driver=wants("driver"),
            want_insurance=wants("insurance"),
        ),
        pickup=request.args.get("pickup", ""),
        return_=request.args.get("return", ""),
        driver=wants("driver"),
        insurance=wants("insurance"),
    )


@bp.route("/book/<int:vehicle_id>/confirm", methods=["POST"])
@customer_required
def confirm(vehicle_id: int):
    """Create the PENDING reservation, if the window is still free.

    The availability shown on the review page was already stale when the
    customer clicked. Re-checking here, inside the transaction that writes the
    row, under a lock on the vehicle, is what makes "first request holds the
    slot" true rather than merely likely.
    """
    vehicle = visible_vehicle(vehicle_id)
    interval, bail = window_from_request(vehicle_id)
    if bail is not None:
        return bail

    db = get_session()
    # Serialises booking attempts for this one vehicle. Postgres honours the
    # lock; SQLite ignores the clause and gets the same guarantee from being
    # single-writer.
    db.execute(select(Vehicle).where(Vehicle.id == vehicle.id).with_for_update())

    verdict = scheduling.availability_for(db, vehicle, interval)
    if not verdict.ok:
        db.rollback()
        flash("That vehicle was just booked for those dates. Please pick another window.", "warning")
        return redirect(url_for("public.vehicle_detail", vehicle_id=vehicle_id))

    driver = wants("driver")
    insurance = wants("insurance")
    # Recomputed here rather than trusted from the form: a posted total is a
    # number the customer controls.
    priced = scheduling.quote_for(
        db, vehicle, interval, want_additional_driver=driver, want_insurance=insurance
    )

    reservation = Reservation(
        user_id=current_user().id,
        vehicle_id=vehicle.id,
        pickup_at=interval.start,
        return_at=interval.end,
        pickup_location=request.form.get("pickup_location", "").strip() or None,
        return_location=request.form.get("return_location", "").strip() or None,
        want_additional_driver=driver,
        want_insurance=insurance,
        rental_hours=priced.duration.hours,
        rental_days=priced.duration.billable_days,
        daily_rate=priced.daily_rate,
        hourly_rate=priced.hourly_rate,
        base_amount=priced.base_amount,
        additional_fees=priced.additional_fees,
        total_amount=priced.total_amount,
        status="PENDING",
    )
    db.add(reservation)
    # flush assigns the id that the reference number is built from.
    db.flush()
    reservation.assign_number()
    db.commit()

    flash(f"Reservation {reservation.reservation_number} was requested.", "success")
    return redirect(url_for("portal.reservation_detail", reservation_id=reservation.id))
```

Extend the imports at the top of `rental/booking.py` to:

```python
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select

from . import scheduling
from .auth import current_role, current_user, customer_required
from .db import get_session
from .models import Reservation, Vehicle
```

`portal.reservation_detail` does not exist until Task 7. Add a stub to
`rental/portal.py` now so `url_for` resolves:

```python
@bp.route("/reservations/<int:reservation_id>")
@customer_required
def reservation_detail(reservation_id: int):
    """One reservation. Task 7 fills this in."""
    abort(501)
```

with `abort` added to the Flask import in that file.

- [ ] **Step 5: Write the review template**

Create `rental/templates/booking/review.html`:

```jinja
{% extends 'layout_public.html' %}
{% from 'partials/_quote_lines.html' import quote_lines %}
{% block title %}Review your booking &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">Review your booking</h1>
  <p class="mt-1 text-sm text-muted">Nothing is reserved until you confirm.</p>
</div>

<div class="grid gap-6 lg:grid-cols-[3fr_2fr]">
  <div class="card p-5">
    <h2 class="text-base font-bold tracking-tight text-ink">{{ vehicle.display_name }}</h2>
    <p class="text-sm text-muted">{{ vehicle.vehicle_type }} &middot; {{ vehicle.year }}</p>

    <dl class="mt-5 grid grid-cols-2 gap-4">
      <div>
        <dt class="stat-label">Pickup</dt>
        <dd class="text-sm font-semibold text-ink">{{ interval.start.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Return</dt>
        <dd class="text-sm font-semibold text-ink">{{ interval.end.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Duration</dt>
        <dd class="text-sm font-semibold text-ink">
          {{ quote.duration.hours }} hour(s) &middot; {{ quote.duration.billable_days }} billable day(s)
        </dd>
      </div>
      <div>
        <dt class="stat-label">Extras</dt>
        <dd class="text-sm font-semibold text-ink">
          {% if driver or insurance %}
            {{ 'Additional driver' if driver }}{{ ', ' if driver and insurance }}{{ 'Insurance' if insurance }}
          {% else %}None{% endif %}
        </dd>
      </div>
    </dl>
  </div>

  <div class="lg:sticky lg:top-24 lg:self-start">
    <div class="card p-5">
      {{ quote_lines(quote) }}

      <form method="post" action="{{ url_for('booking.confirm', vehicle_id=vehicle.id) }}"
            class="mt-5 border-t border-line pt-4">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="pickup" value="{{ pickup }}">
        <input type="hidden" name="return" value="{{ return_ }}">
        {% if driver %}<input type="hidden" name="driver" value="1">{% endif %}
        {% if insurance %}<input type="hidden" name="insurance" value="1">{% endif %}

        <div>
          <label class="field-label" for="pickup_location">Pickup location</label>
          <input class="field" id="pickup_location" name="pickup_location" maxlength="120"
                 value="Main office" required>
        </div>
        <div class="mt-3">
          <label class="field-label" for="return_location">Return location</label>
          <input class="field" id="return_location" name="return_location" maxlength="120"
                 value="Main office" required>
        </div>

        <p class="mt-4 text-xs text-muted">
          Payment status: Pending. Settle at the counter when you collect the vehicle.
        </p>
        <button type="submit" class="btn btn-primary mt-4 w-full">Confirm reservation</button>
        <a class="btn btn-ghost mt-2 w-full"
           href="{{ url_for('public.vehicle_detail', vehicle_id=vehicle.id) }}?pickup={{ pickup | urlencode }}&return={{ return_ | urlencode }}">
          Change dates
        </a>
      </form>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_booking.py tests/test_auth.py -q`
Expected: all pass. `test_confirm_creates_a_pending_reservation_...` follows a
redirect to the Task 7 stub only in `Location`; it never fetches it, so the
`abort(501)` stub does not break it.

- [ ] **Step 7: Prove the lock is load-bearing — the first guard**

Comment out the `with_for_update()` line and the `verdict` re-check in
`confirm`, leaving only the write:

```bash
uv run pytest tests/test_booking.py::test_confirm_refuses_a_window_that_was_taken_in_the_meantime -q
```
Expected: **FAIL** — two reservations exist for the same window.

Restore both lines, re-run, and confirm it passes. Paste both transcripts into
the task report.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: **274 passed**.

- [ ] **Step 9: Commit**

```bash
git add rental/booking.py rental/auth.py rental/portal.py \
        rental/templates/booking/review.html tests/test_booking.py tests/test_auth.py
git commit -m "feat: book, review and confirm a reservation under a row lock"
```

---

### Task 6: The live price preview

An enhancement on a page that already works without it. The browser never
prices anything — it asks `/api/quote` and renders the answer.

**Files:**
- Create: `rental/static/js/quote-preview.js`
- Modify: `rental/templates/base.html` (add a `scripts` block), `rental/templates/storefront/vehicle_detail.html` (use it)
- Test: `tests/test_public.py` (append)

**Interfaces:**
- Consumes: `GET /api/quote`'s JSON shape from Task 2 — `{available, reason, message, total, lines}` where each line is `[label, detail, amount]`.
- Consumes the DOM hooks Task 3 placed: `[data-quote-form]` with `data-vehicle`, and `[data-quote-panel]`.

- [ ] **Step 1: Write the failing tests**

These are the honest limit of a server-side suite: it can prove the script is
served and wired in, not that it runs. The behaviour it drives is already
covered by Task 2's `/api/quote` tests and Task 3's server-rendered tests.

Append to `tests/test_public.py`:

```python
def test_the_quote_preview_script_is_served(client):
    response = client.get("/static/js/quote-preview.js")

    assert response.status_code == 200
    assert b"/api/quote" in response.data


def test_the_detail_page_loads_the_quote_preview_script(client, sample_vehicle):
    body = client.get(f"/vehicles/{sample_vehicle}").get_data(as_text=True)

    assert "js/quote-preview.js" in body
    assert "data-quote-panel" in body
    assert f'data-vehicle="{sample_vehicle}"' in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_public.py -q -k quote_preview`
Expected: 404 on the script, and the page does not reference it.

- [ ] **Step 3: Write the script**

Create `rental/static/js/quote-preview.js`:

```javascript
// Live price preview.
//
// The browser does no arithmetic. Pricing -- the hourly cap, the per-day
// extras, the fee table -- lives in rental/domain/pricing.py and is reached
// through /api/quote, so there is exactly one implementation to keep right.
//
// The page is fully usable without this file: whenever the URL carries dates,
// the same figures are already server-rendered.
(function () {
  var form = document.querySelector('[data-quote-form][data-vehicle]');
  var panel = document.querySelector('[data-quote-panel]');
  if (!form || !panel) return;

  var timer = null;
  var latest = 0;

  function peso(value) {
    return '₱' + Number(value).toLocaleString('en-PH', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function render(data) {
    if (!data.available) {
      panel.innerHTML = '<div class="alert alert-warning"><span></span></div>';
      panel.querySelector('span').textContent = data.message || 'Not available for those dates.';
      return;
    }
    var rows = data.lines.map(function (line) {
      var tr = document.createElement('tr');
      tr.className = 'border-b border-line last:border-0';
      var left = document.createElement('td');
      left.className = 'py-2';
      var label = document.createElement('span');
      label.className = 'font-medium text-ink';
      label.textContent = line[0];
      var detail = document.createElement('span');
      detail.className = 'block text-xs text-muted';
      detail.textContent = line[1];
      left.appendChild(label);
      left.appendChild(detail);
      var right = document.createElement('td');
      right.className = 'py-2 text-right font-semibold text-ink';
      right.textContent = peso(line[2]);
      tr.appendChild(left);
      tr.appendChild(right);
      return tr;
    });

    panel.innerHTML =
      '<div class="border-t border-line pt-4"><table class="w-full text-sm"><tbody>' +
      '</tbody></table></div>';
    var body = panel.querySelector('tbody');
    rows.forEach(function (row) { body.appendChild(row); });

    var totalRow = document.createElement('tr');
    totalRow.innerHTML =
      '<td class="pt-3 text-sm font-semibold text-ink">Total</td>' +
      '<td class="pt-3 text-right"><span class="rate" data-quote-total></span></td>';
    body.appendChild(totalRow);
    totalRow.querySelector('[data-quote-total]').textContent = peso(data.total);
  }

  function refresh() {
    var pickup = form.querySelector('[name="pickup"]').value;
    var returnAt = form.querySelector('[name="return"]').value;
    if (!pickup || !returnAt) return;

    var params = new URLSearchParams({
      vehicle: form.dataset.vehicle,
      pickup: pickup,
      'return': returnAt
    });
    if (form.querySelector('[name="driver"]').checked) params.set('driver', '1');
    if (form.querySelector('[name="insurance"]').checked) params.set('insurance', '1');

    // The previous figure stays on screen while this is in flight; a stale
    // response that arrives late is discarded rather than overwriting a newer
    // one.
    var ticket = ++latest;
    fetch('/api/quote?' + params.toString())
      .then(function (response) { return response.json(); })
      .then(function (data) { if (ticket === latest) render(data); })
      .catch(function () { /* leave the server-rendered figure in place */ });
  }

  function debounced() {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, 300);
  }

  form.addEventListener('change', debounced);
  form.addEventListener('input', debounced);
})();
```

- [ ] **Step 4: Add a scripts block to the base layout**

In `rental/templates/base.html`, add immediately before `</body>`:

```jinja
{% block scripts %}{% endblock %}
```

- [ ] **Step 5: Load it from the detail page**

At the end of `rental/templates/storefront/vehicle_detail.html`, after the
closing `{% endblock %}` of `content`, add:

```jinja
{% block scripts %}
  <script src="{{ url_for('static', filename='js/quote-preview.js') }}" defer></script>
{% endblock %}
```

`layout_public.html` extends `base.html` and overrides `body`; confirm the
`scripts` block survives that chain:

```bash
uv run pytest tests/test_public.py -q -k quote_preview
```

If the block does not render, `layout_public.html` is overriding `body`
wholesale — add `{% block scripts %}{% endblock %}` at the end of
`layout_public.html`'s `body` block instead, and remove it from `base.html`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_public.py -q`
Expected: all pass.

- [ ] **Step 7: Check the page by hand**

```bash
DATABASE_URL=sqlite:///rental.db uv run flask --app rental run --port 5000
```
Open `http://127.0.0.1:5000/vehicles/1`, pick two dates, tick Insurance, and
confirm the total updates without a page load. Then open the browser console
and confirm it is clean. Record what you saw in the task report.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: **276 passed**.

- [ ] **Step 9: Commit**

```bash
git add rental/static/js/quote-preview.js rental/templates/base.html \
        rental/templates/layout_public.html \
        rental/templates/storefront/vehicle_detail.html tests/test_public.py
git commit -m "feat: live price preview reading the server's own quote"
```

---

### Task 7: My Reservations, reservation detail, and cancel

Scoped to the signed-in customer, always. A customer opening someone else's
reservation gets a **404, not a 403** — a 403 would confirm the record exists.

**Files:**
- Modify: `rental/portal.py`
- Create: `rental/templates/customer/reservations.html`, `rental/templates/customer/reservation_detail.html`
- Test: `tests/test_my_area.py`

**Interfaces:**
- Consumes: the `Reservation` rows Task 5 writes; `rental.domain.lifecycle.cancel_reservation`; `rental.clock.now`.
- Produces:
  - `portal.reservations` — `GET /my/reservations`
  - `portal.reservation_detail` — `GET /my/reservations/<reservation_id>` (replaces the Task 5 stub)
  - `portal.cancel` — `POST /my/reservations/<reservation_id>/cancel` (named `cancel`, because `cancel_reservation` is the imported domain function)
  - `portal.owned_reservation(reservation_id) -> Reservation` — the ownership-scoped loader Task 9's rental pages copy the shape of.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_my_area.py`:

```python
"""The customer's own pages. Everything here is scoped to the signed-in user."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from rental.clock import now
from rental.db import get_session
from rental.models import Reservation, User, Vehicle


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_my_area.py -q`
Expected: 404s and 501s — only the Task 5 stub exists.

- [ ] **Step 3: Write the routes**

In `rental/portal.py`, extend the imports:

```python
from flask import Blueprint, abort, flash, redirect, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from .auth import current_user, customer_required
from .clock import now
from .db import get_session
from .domain.lifecycle import TransitionError, cancel_reservation
from .models import Rental, Reservation, Vehicle
```

Replace the Task 5 stub with:

```python
def owned_reservation(reservation_id: int) -> Reservation:
    """Load one of the signed-in customer's reservations, or 404.

    The owner filter is part of the query rather than a check afterwards, so
    there is no path that loads someone else's row at all. A missing row and
    somebody else's row are both 404: a 403 would confirm the record exists.
    """
    db = get_session()
    reservation = db.scalars(
        select(Reservation)
        .options(joinedload(Reservation.vehicle))
        .where(Reservation.id == reservation_id)
        .where(Reservation.user_id == current_user().id)
    ).first()
    if reservation is None:
        abort(404)
    return reservation


@bp.route("/reservations")
@customer_required
def reservations():
    """Every reservation this customer has ever made, newest first."""
    db = get_session()
    rows = db.scalars(
        select(Reservation)
        .options(joinedload(Reservation.vehicle))
        .where(Reservation.user_id == current_user().id)
        .order_by(Reservation.created_at.desc(), Reservation.id.desc())
    ).all()
    return render_template("customer/reservations.html", reservations=rows)


@bp.route("/reservations/<int:reservation_id>")
@customer_required
def reservation_detail(reservation_id: int):
    """One reservation, with the quote exactly as it was booked."""
    reservation = owned_reservation(reservation_id)
    return render_template(
        "customer/reservation_detail.html",
        reservation=reservation,
        can_cancel=can_cancel(reservation),
    )


def can_cancel(reservation: Reservation) -> bool:
    """A reservation may be called off any time before pickup, not after."""
    return reservation.status in ("PENDING", "CONFIRMED") and reservation.pickup_at > now()


@bp.route("/reservations/<int:reservation_id>/cancel", methods=["POST"])
@customer_required
def cancel(reservation_id: int):
    """Call off a booking and release the vehicle."""
    reservation = owned_reservation(reservation_id)
    db = get_session()

    if reservation.pickup_at <= now():
        flash(
            "This booking can no longer be cancelled online. Please contact the office.",
            "warning",
        )
        return redirect(url_for("portal.reservation_detail", reservation_id=reservation.id))

    try:
        change = cancel_reservation(reservation.status)
    except TransitionError as error:
        # A stale page, not a bug: the booking moved on while it was open.
        flash(str(error), "warning")
        return redirect(url_for("portal.reservation_detail", reservation_id=reservation.id))

    reservation.status = change.reservation_status
    db.get(Vehicle, reservation.vehicle_id).status = change.vehicle_status
    db.commit()

    flash(f"Reservation {reservation.reservation_number} was cancelled.", "success")
    return redirect(url_for("portal.reservation_detail", reservation_id=reservation.id))
```

`TransitionError`'s message is `"Cannot go from CANCELLED to CANCELLED."`,
which is why `test_cancelling_an_already_cancelled_booking_is_a_message_not_a_500`
looks for "cannot".

`Reservation.vehicle` must be a relationship for `joinedload` to work. Check:

```bash
grep -n 'relationship' rental/models.py
```

If `Reservation` has no `vehicle` relationship, drop the `.options(joinedload(...))`
calls and join explicitly instead:

```python
select(Reservation, Vehicle).join(Vehicle, Vehicle.id == Reservation.vehicle_id)
```

adjusting the templates to unpack the pair. Do **not** add a relationship to
`models.py` for this — schema changes are outside this phase.

- [ ] **Step 4: Write the two templates**

Create `rental/templates/customer/reservations.html`:

```jinja
{% extends 'layout_public.html' %}
{% block title %}My reservations &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">My Reservations</h1>
  <p class="mt-1 text-sm text-muted">
    {{ reservations | length }} reservation{{ '' if reservations | length == 1 else 's' }}
  </p>
</div>

{% if reservations %}
  <div class="card overflow-hidden">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-line text-left">
          <th class="p-4 stat-label">Reference</th>
          <th class="p-4 stat-label">Vehicle</th>
          <th class="p-4 stat-label">Pickup</th>
          <th class="p-4 stat-label">Return</th>
          <th class="p-4 stat-label">Total</th>
          <th class="p-4 stat-label">Status</th>
        </tr>
      </thead>
      <tbody>
        {% for reservation in reservations %}
          <tr class="border-b border-line last:border-0">
            <td class="p-4">
              <a class="font-semibold text-ink underline"
                 href="{{ url_for('portal.reservation_detail', reservation_id=reservation.id) }}">
                {{ reservation.reservation_number }}
              </a>
            </td>
            <td class="p-4">{{ reservation.vehicle.display_name }}</td>
            <td class="p-4">{{ reservation.pickup_at.strftime('%d %b %Y, %I:%M %p') }}</td>
            <td class="p-4">{{ reservation.return_at.strftime('%d %b %Y, %I:%M %p') }}</td>
            <td class="p-4 font-semibold">₱{{ '{:,.2f}'.format(reservation.total_amount) }}</td>
            <td class="p-4"><span class="pill {{ reservation.badge_class }}">{{ reservation.status }}</span></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% else %}
  <div class="card p-10 text-center">
    <p class="text-base font-semibold text-ink">No reservations yet</p>
    <p class="mt-1.5 text-sm text-muted">Pick your dates on any vehicle and book it online.</p>
    <a class="btn btn-primary mt-5" href="{{ url_for('public.browse') }}">Browse Vehicles</a>
  </div>
{% endif %}
{% endblock %}
```

Create `rental/templates/customer/reservation_detail.html`:

```jinja
{% extends 'layout_public.html' %}
{% block title %}{{ reservation.reservation_number }} &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6 flex items-center gap-3">
  <h1 class="page-title">{{ reservation.reservation_number }}</h1>
  <span class="pill {{ reservation.badge_class }}">{{ reservation.status }}</span>
</div>

<div class="grid gap-6 lg:grid-cols-[3fr_2fr]">
  <div class="card p-5">
    <h2 class="text-base font-bold tracking-tight text-ink">{{ reservation.vehicle.display_name }}</h2>
    <p class="text-sm text-muted">{{ reservation.vehicle.vehicle_type }} &middot; {{ reservation.vehicle.plate_number }}</p>

    <dl class="mt-5 grid grid-cols-2 gap-4">
      <div>
        <dt class="stat-label">Pickup</dt>
        <dd class="text-sm font-semibold text-ink">{{ reservation.pickup_at.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Return</dt>
        <dd class="text-sm font-semibold text-ink">{{ reservation.return_at.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Pickup location</dt>
        <dd class="text-sm font-semibold text-ink">{{ reservation.pickup_location or '—' }}</dd>
      </div>
      <div>
        <dt class="stat-label">Return location</dt>
        <dd class="text-sm font-semibold text-ink">{{ reservation.return_location or '—' }}</dd>
      </div>
      <div>
        <dt class="stat-label">Duration</dt>
        <dd class="text-sm font-semibold text-ink">
          {{ reservation.rental_hours }} hour(s) &middot; {{ reservation.rental_days }} billable day(s)
        </dd>
      </div>
      <div>
        <dt class="stat-label">Extras</dt>
        <dd class="text-sm font-semibold text-ink">
          {% if reservation.want_additional_driver or reservation.want_insurance %}
            {{ 'Additional driver' if reservation.want_additional_driver }}{{ ', ' if reservation.want_additional_driver and reservation.want_insurance }}{{ 'Insurance' if reservation.want_insurance }}
          {% else %}None{% endif %}
        </dd>
      </div>
    </dl>
  </div>

  <div class="lg:sticky lg:top-24 lg:self-start">
    <div class="card p-5">
      {# The figures were frozen when the booking was made. A later change to
         the fee table must never alter what someone already booked. #}
      <table class="w-full text-sm">
        <tbody>
          <tr class="border-b border-line">
            <td class="py-2">
              <span class="font-medium text-ink">Base rental</span>
              <span class="block text-xs text-muted">
                ₱{{ '{:,.2f}'.format(reservation.daily_rate) }} x {{ reservation.rental_days }} day(s)
              </span>
            </td>
            <td class="py-2 text-right font-semibold text-ink">₱{{ '{:,.2f}'.format(reservation.base_amount) }}</td>
          </tr>
          <tr class="border-b border-line">
            <td class="py-2"><span class="font-medium text-ink">Additional fees</span></td>
            <td class="py-2 text-right font-semibold text-ink">₱{{ '{:,.2f}'.format(reservation.additional_fees) }}</td>
          </tr>
          <tr>
            <td class="pt-3 text-sm font-semibold text-ink">Total</td>
            <td class="pt-3 text-right"><span class="rate">₱{{ '{:,.2f}'.format(reservation.total_amount) }}</span></td>
          </tr>
        </tbody>
      </table>

      <div class="mt-4 flex items-center justify-between border-t border-line pt-4">
        <span class="stat-label">Payment Status</span>
        <span class="pill pill-warning">Pending</span>
      </div>
      <p class="mt-1.5 text-xs text-muted">Settle at the counter when you collect the vehicle.</p>

      {% if can_cancel %}
        <form method="post" class="mt-4"
              action="{{ url_for('portal.cancel', reservation_id=reservation.id) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <button type="submit" class="btn btn-ghost w-full">Cancel this reservation</button>
        </form>
      {% elif reservation.status in ['PENDING', 'CONFIRMED'] %}
        <p class="mt-4 text-sm text-muted">
          This booking can no longer be cancelled online. Please contact the office.
        </p>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_my_area.py -q`
Expected: 12 passed.

- [ ] **Step 6: Prove the ownership filter is load-bearing — the second guard**

In `owned_reservation`, comment out the line
`.where(Reservation.user_id == current_user().id)`:

```bash
uv run pytest tests/test_my_area.py::test_reservation_detail_404s_on_another_customers_booking \
              tests/test_my_area.py::test_cancel_404s_on_another_customers_booking -q
```
Expected: **both FAIL** — a customer reads and can cancel another customer's
booking.

Restore the line, re-run, and confirm both pass. Paste both transcripts into
the task report.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: **288 passed**.

- [ ] **Step 8: Commit**

```bash
git add rental/portal.py rental/templates/customer/reservations.html \
        rental/templates/customer/reservation_detail.html tests/test_my_area.py
git commit -m "feat: My Reservations, reservation detail and cancel"
```

---

### Task 8: The admin reservation queue — confirm and reject

**Files:**
- Create: `rental/admin/reservations.py`, `rental/templates/admin/reservations.html`
- Modify: `rental/__init__.py` (import + register), `rental/templates/layout_admin.html` (nav link)
- Test: `tests/test_admin_lifecycle.py`

**Interfaces:**
- Consumes: `rental.domain.lifecycle.{confirm_reservation, reject_reservation, TransitionError}` — `confirm_reservation` returns `StateChange("CONFIRMED", None, "RESERVED")`, `reject_reservation` returns `StateChange("REJECTED", None, "AVAILABLE")`.
- Produces:
  - Blueprint `admin_reservations.bp` with `url_prefix="/admin/reservations"`
  - `admin_reservations.queue` — `GET /admin/reservations`
  - `admin_reservations.confirm` — `POST /admin/reservations/<reservation_id>/confirm`
  - `admin_reservations.reject` — `POST /admin/reservations/<reservation_id>/reject`
  - `admin_reservations.apply_change(db, reservation, change, rental=None)` — writes a `StateChange` across reservation, vehicle and (when given) rental in one transaction, then commits. Task 9 calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_lifecycle.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_admin_lifecycle.py -q`
Expected: 404 on every admin route.

- [ ] **Step 3: Write the blueprint**

Create `rental/admin/reservations.py`:

```python
"""The reservation queue: accept a request, or decline it.

Each action calls the matching phase 2 function and applies the StateChange it
returns, so the reservation and the vehicle move together or not at all. The
mapping of "what does confirming change" lives in `domain/lifecycle.py`, not
here -- this module is the transaction around it.
"""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..auth import admin_required
from ..db import get_session
from ..domain.lifecycle import StateChange, TransitionError, confirm_reservation, reject_reservation
from ..models import Reservation, User, Vehicle

bp = Blueprint("admin_reservations", __name__, url_prefix="/admin/reservations")

#: The queue's own order: waiting requests first, then the rest, newest first.
QUEUE_FIRST = ("PENDING", "CONFIRMED")


def load_reservation(reservation_id: int) -> Reservation:
    """Load one reservation for an admin, or 404."""
    reservation = get_session().get(Reservation, reservation_id)
    if reservation is None:
        abort(404)
    return reservation


def apply_change(db, reservation: Reservation, change: StateChange, rental=None) -> None:
    """Write a StateChange across every row it names, in one transaction.

    Requirement 18's five-part close is one value returned by the domain; this
    is the only place that turns it into writes, so a route cannot perform four
    of the five.
    """
    reservation.status = change.reservation_status
    db.get(Vehicle, reservation.vehicle_id).status = change.vehicle_status
    if change.rental_status is not None and rental is not None:
        rental.status = change.rental_status
    db.commit()


# An empty rule registers exactly "/admin/reservations"; see admin/dashboard.py.
@bp.route("")
@admin_required
def queue():
    """Every reservation, with the ones waiting on a decision at the top."""
    db = get_session()
    rows = db.scalars(
        select(Reservation)
        .options(joinedload(Reservation.vehicle), joinedload(Reservation.user))
        .order_by(Reservation.created_at.desc(), Reservation.id.desc())
    ).all()
    return render_template(
        "admin/reservations.html",
        pending=[r for r in rows if r.status == "PENDING"],
        others=[r for r in rows if r.status != "PENDING"],
    )


def decide(reservation_id: int, action, verb: str):
    """Shared body for confirm and reject.

    A TransitionError here means the page was stale -- two admins working at
    once -- which is a message, not a 500.
    """
    reservation = load_reservation(reservation_id)
    db = get_session()
    try:
        change = action(reservation.status)
    except TransitionError as error:
        flash(str(error), "warning")
        return redirect(url_for("admin_reservations.queue"))

    apply_change(db, reservation, change)
    flash(f"Reservation {reservation.reservation_number} was {verb}.", "success")
    return redirect(url_for("admin_reservations.queue"))


@bp.route("/<int:reservation_id>/confirm", methods=["POST"])
@admin_required
def confirm(reservation_id: int):
    """Accept a pending request. The vehicle is now spoken for."""
    return decide(reservation_id, confirm_reservation, "confirmed")


@bp.route("/<int:reservation_id>/reject", methods=["POST"])
@admin_required
def reject(reservation_id: int):
    """Decline a pending request and release the vehicle."""
    return decide(reservation_id, reject_reservation, "rejected")
```

If `Reservation.user` is not a relationship, drop that `joinedload` and load
the customers separately — see the note in Task 7, Step 3.

- [ ] **Step 4: Write the template**

Create `rental/templates/admin/reservations.html`:

```jinja
{% extends 'layout_admin.html' %}
{% block title %}Reservations &middot; Vehicle Rental{% endblock %}

{% macro row(reservation, actionable) %}
<tr class="border-b border-line last:border-0">
  <td class="p-4 font-semibold text-ink">{{ reservation.reservation_number }}</td>
  <td class="p-4">{{ reservation.user.display_name }}</td>
  <td class="p-4">{{ reservation.vehicle.display_name }}</td>
  <td class="p-4">{{ reservation.pickup_at.strftime('%d %b %Y, %I:%M %p') }}</td>
  <td class="p-4">{{ reservation.return_at.strftime('%d %b %Y, %I:%M %p') }}</td>
  <td class="p-4 font-semibold">₱{{ '{:,.2f}'.format(reservation.total_amount) }}</td>
  <td class="p-4"><span class="pill {{ reservation.badge_class }}">{{ reservation.status }}</span></td>
  <td class="p-4">
    {% if actionable %}
      <div class="flex gap-2">
        <form method="post" action="{{ url_for('admin_reservations.confirm', reservation_id=reservation.id) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <button type="submit" class="btn btn-primary btn-sm">Confirm</button>
        </form>
        <form method="post" action="{{ url_for('admin_reservations.reject', reservation_id=reservation.id) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <button type="submit" class="btn btn-ghost btn-sm">Reject</button>
        </form>
      </div>
    {% endif %}
  </td>
</tr>
{% endmacro %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">Reservations</h1>
  <p class="mt-1 text-sm text-muted">
    {{ pending | length }} waiting on a decision
  </p>
</div>

{% if pending %}
  <div class="card mb-8 overflow-hidden">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-line text-left">
          <th class="p-4 stat-label">Reference</th>
          <th class="p-4 stat-label">Customer</th>
          <th class="p-4 stat-label">Vehicle</th>
          <th class="p-4 stat-label">Pickup</th>
          <th class="p-4 stat-label">Return</th>
          <th class="p-4 stat-label">Total</th>
          <th class="p-4 stat-label">Status</th>
          <th class="p-4 stat-label">Action</th>
        </tr>
      </thead>
      <tbody>
        {% for reservation in pending %}{{ row(reservation, True) }}{% endfor %}
      </tbody>
    </table>
  </div>
{% else %}
  <div class="card mb-8 p-10 text-center">
    <p class="text-base font-semibold text-ink">The queue is clear.</p>
    <p class="mt-1.5 text-sm text-muted">No reservation is waiting on a decision.</p>
  </div>
{% endif %}

{% if others %}
  <h2 class="mb-3 text-sm font-bold tracking-tight text-ink">Everything else</h2>
  <div class="card overflow-hidden">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-line text-left">
          <th class="p-4 stat-label">Reference</th>
          <th class="p-4 stat-label">Customer</th>
          <th class="p-4 stat-label">Vehicle</th>
          <th class="p-4 stat-label">Pickup</th>
          <th class="p-4 stat-label">Return</th>
          <th class="p-4 stat-label">Total</th>
          <th class="p-4 stat-label">Status</th>
          <th class="p-4 stat-label"></th>
        </tr>
      </thead>
      <tbody>
        {% for reservation in others %}{{ row(reservation, False) }}{% endfor %}
      </tbody>
    </table>
  </div>
{% endif %}
{% endblock %}
```

`btn-sm` must exist in `rental/static/src/input.css`. Check with
`grep -n 'btn-sm' rental/static/src/input.css`; if it is missing, add it
beside the other `btn-*` rules, or drop the class.

- [ ] **Step 5: Register the blueprint and add the nav link**

In `rental/__init__.py`, beside the other admin imports:

```python
from .admin import reservations as admin_reservations
```

and beside the other registrations:

```python
    app.register_blueprint(admin_reservations.bp)
```

In `rental/templates/partials/_admin_nav.html`, add a Reservations link
following the exact shape of the existing links (copy one and change its
`url_for` to `admin_reservations.queue` and its label to "Reservations").

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_admin_lifecycle.py -q`
Expected: 8 passed.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: **296 passed**.

- [ ] **Step 8: Commit**

```bash
git add rental/admin/reservations.py rental/__init__.py \
        rental/templates/admin/reservations.html rental/templates/partials/_admin_nav.html \
        rental/static/src/input.css tests/test_admin_lifecycle.py
git commit -m "feat: the admin reservation queue, with confirm and reject"
```

---

### Task 9: Hand over the keys, and take the vehicle back

The two actions that create and close a `Rental`. Returning late is where phase
2's `late_charge` finally earns its keep.

**Files:**
- Create: `rental/admin/rentals.py`, `rental/templates/admin/rentals.html`
- Modify: `rental/admin/reservations.py` (the Start button on a CONFIRMED row), `rental/__init__.py`, `rental/templates/admin/reservations.html`, `rental/templates/partials/_admin_nav.html`
- Test: `tests/test_admin_lifecycle.py` (append)

**Interfaces:**
- Consumes: `rental.domain.lifecycle.{start_rental, complete_rental}` — `start_rental` returns `StateChange("CONFIRMED", "ACTIVE", "RENTED")` (the reservation **stays** CONFIRMED); `complete_rental(reservation_status, rental_status)` returns `StateChange("COMPLETED", "COMPLETED", "AVAILABLE")`. `rental.domain.pricing.late_charge(expected_return, actual_return, late_fee_per_day) -> (late_hours, fee)`. `admin_reservations.apply_change` from Task 8.
- Produces:
  - `admin_reservations.start` — `POST /admin/reservations/<reservation_id>/start`
  - Blueprint `admin_rentals.bp` with `url_prefix="/admin/rentals"`
  - `admin_rentals.index` — `GET /admin/rentals`
  - `admin_rentals.mark_returned` — `POST /admin/rentals/<rental_id>/return`
  - A `Rental` row, which Task 10's customer pages read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_lifecycle.py`:

```python
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


def test_a_vehicle_cannot_be_handed_over_twice(admin_client, app, vehicle_id):
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED")
    admin_client.post(f"/admin/reservations/{reservation_id}/start")

    response = admin_client.post(
        f"/admin/reservations/{reservation_id}/start", follow_redirects=True
    )

    assert "already" in response.get_data(as_text=True).lower()
    with app.app_context():
        assert get_session().query(Rental).count() == 1


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
    # Booked for two days ending 25 hours ago: two days late by the hour,
    # which is two late days at the fee below.
    reservation_id = add_reservation(app, vehicle_id, status="CONFIRMED", starts_in_days=-4, days=2)
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_admin_lifecycle.py -q -k "start or return or rentals_page"`
Expected: 404 on every new route.

- [ ] **Step 3: Add `start` to `rental/admin/reservations.py`**

Extend the imports in that file:

```python
from ..clock import now
from ..domain.lifecycle import (
    StateChange,
    TransitionError,
    confirm_reservation,
    reject_reservation,
    start_rental,
)
from ..models import Rental, Reservation, User, Vehicle
```

and append:

```python
@bp.route("/<int:reservation_id>/start", methods=["POST"])
@admin_required
def start(reservation_id: int):
    """Hand over the keys: create the ACTIVE rental and send the vehicle out.

    Locked and re-checked the same way a booking is, so a vehicle cannot be
    handed over twice by two admins clicking at once.
    """
    reservation = load_reservation(reservation_id)
    db = get_session()
    db.execute(select(Vehicle).where(Vehicle.id == reservation.vehicle_id).with_for_update())

    existing = db.scalars(
        select(Rental).where(Rental.reservation_id == reservation.id)
    ).first()
    if existing is not None:
        db.rollback()
        flash(
            f"Reservation {reservation.reservation_number} has already been handed over.",
            "warning",
        )
        return redirect(url_for("admin_reservations.queue"))

    try:
        change = start_rental(reservation.status)
    except TransitionError as error:
        db.rollback()
        flash(str(error), "warning")
        return redirect(url_for("admin_reservations.queue"))

    rental = Rental(
        reservation_id=reservation.id,
        vehicle_id=reservation.vehicle_id,
        customer_id=reservation.user_id,
        actual_pickup=now(),
        expected_return=reservation.return_at,
        rental_hours=reservation.rental_hours,
        rental_days=reservation.rental_days,
        late_hours=0,
        base_amount=reservation.base_amount,
        late_fee=Decimal("0.00"),
        additional_fees=reservation.additional_fees,
        total_amount=reservation.total_amount,
        status=change.rental_status,
    )
    db.add(rental)
    db.flush()
    rental.assign_number()
    apply_change(db, reservation, change, rental=rental)

    flash(f"Rental {rental.rental_number} has started.", "success")
    return redirect(url_for("admin_rentals.index"))
```

Add `from decimal import Decimal` to that file's imports.

In `rental/templates/admin/reservations.html`, add a Start form to the
`row` macro so a CONFIRMED reservation can be handed over. Replace the
`{% if actionable %}` block's contents with:

```jinja
      <div class="flex gap-2">
        {% if reservation.status == 'PENDING' %}
          <form method="post" action="{{ url_for('admin_reservations.confirm', reservation_id=reservation.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn btn-primary btn-sm">Confirm</button>
          </form>
          <form method="post" action="{{ url_for('admin_reservations.reject', reservation_id=reservation.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn btn-ghost btn-sm">Reject</button>
          </form>
        {% elif reservation.status == 'CONFIRMED' %}
          <form method="post" action="{{ url_for('admin_reservations.start', reservation_id=reservation.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn btn-primary btn-sm">Start rental</button>
          </form>
        {% endif %}
      </div>
```

and change the `queue` view's split so CONFIRMED rows are actionable too:

```python
    return render_template(
        "admin/reservations.html",
        pending=[r for r in rows if r.status == "PENDING"],
        others=[r for r in rows if r.status != "PENDING"],
        actionable_statuses=("PENDING", "CONFIRMED"),
    )
```

and render the "Everything else" table with
`{{ row(reservation, reservation.status in actionable_statuses) }}`.

- [ ] **Step 4: Write `rental/admin/rentals.py`**

```python
"""Vehicles that are out, and taking them back.

The return is requirement 18's five-part close: the rental finishes, the
reservation finishes, the vehicle comes back to AVAILABLE, the actual return
time is recorded, and any late fee is charged. `complete_rental` returns all of
those statuses as one value and `apply_change` writes them in one transaction,
so no route can do four of the five.
"""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import scheduling
from ..auth import admin_required
from ..clock import now
from ..db import get_session
from ..domain.lifecycle import TransitionError, complete_rental
from ..domain.pricing import late_charge, money
from ..models import Rental, Reservation
from .reservations import apply_change

bp = Blueprint("admin_rentals", __name__, url_prefix="/admin/rentals")


# An empty rule registers exactly "/admin/rentals"; see admin/dashboard.py.
@bp.route("")
@admin_required
def index():
    """Every rental, the ones still out first."""
    db = get_session()
    rows = db.scalars(
        select(Rental)
        .options(joinedload(Rental.vehicle), joinedload(Rental.customer))
        .order_by(Rental.actual_pickup.desc(), Rental.id.desc())
    ).all()
    return render_template(
        "admin/rentals.html",
        active=[r for r in rows if r.status == "ACTIVE"],
        finished=[r for r in rows if r.status != "ACTIVE"],
    )


@bp.route("/<int:rental_id>/return", methods=["POST"])
@admin_required
def mark_returned(rental_id: int):
    """The vehicle comes back. Records the time and charges for any overrun."""
    db = get_session()
    rental = db.get(Rental, rental_id)
    if rental is None:
        abort(404)
    reservation = db.get(Reservation, rental.reservation_id)

    try:
        change = complete_rental(reservation.status, rental.status)
    except TransitionError as error:
        flash(str(error), "warning")
        return redirect(url_for("admin_rentals.index"))

    returned_at = now()
    late_hours, fee = late_charge(
        rental.expected_return, returned_at, scheduling.current_rates(db).late_fee_per_day
    )

    rental.actual_return = returned_at
    rental.late_hours = late_hours
    rental.late_fee = fee
    rental.total_amount = money(rental.base_amount + rental.additional_fees + fee)
    apply_change(db, reservation, change, rental=rental)

    if fee:
        flash(
            f"Rental {rental.rental_number} was returned {late_hours} hour(s) late. "
            f"A late fee of PHP {fee:,.2f} was added.",
            "warning",
        )
    else:
        flash(f"Rental {rental.rental_number} was returned on time.", "success")
    return redirect(url_for("admin_rentals.index"))
```

If `Rental.vehicle` / `Rental.customer` are not relationships, drop those
`joinedload` calls and join explicitly — see the note in Task 7, Step 3.

- [ ] **Step 5: Write `rental/templates/admin/rentals.html`**

```jinja
{% extends 'layout_admin.html' %}
{% block title %}Rentals &middot; Vehicle Rental{% endblock %}

{% macro row(rental, actionable) %}
<tr class="border-b border-line last:border-0">
  <td class="p-4 font-semibold text-ink">{{ rental.rental_number }}</td>
  <td class="p-4">{{ rental.customer.display_name }}</td>
  <td class="p-4">{{ rental.vehicle.display_name }}</td>
  <td class="p-4">{{ rental.actual_pickup.strftime('%d %b %Y, %I:%M %p') }}</td>
  <td class="p-4">{{ rental.expected_return.strftime('%d %b %Y, %I:%M %p') }}</td>
  <td class="p-4">
    {{ rental.actual_return.strftime('%d %b %Y, %I:%M %p') if rental.actual_return else '—' }}
  </td>
  <td class="p-4">
    {% if rental.late_fee %}
      <span class="pill pill-warning">₱{{ '{:,.2f}'.format(rental.late_fee) }}</span>
    {% else %}—{% endif %}
  </td>
  <td class="p-4 font-semibold">₱{{ '{:,.2f}'.format(rental.total_amount) }}</td>
  <td class="p-4"><span class="pill {{ rental.badge_class }}">{{ rental.status }}</span></td>
  <td class="p-4">
    {% if actionable %}
      <form method="post" action="{{ url_for('admin_rentals.mark_returned', rental_id=rental.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="btn btn-primary btn-sm">Mark returned</button>
      </form>
    {% endif %}
  </td>
</tr>
{% endmacro %}

{% macro table(rows, actionable) %}
<div class="card overflow-hidden">
  <table class="w-full text-sm">
    <thead>
      <tr class="border-b border-line text-left">
        <th class="p-4 stat-label">Reference</th>
        <th class="p-4 stat-label">Customer</th>
        <th class="p-4 stat-label">Vehicle</th>
        <th class="p-4 stat-label">Collected</th>
        <th class="p-4 stat-label">Due back</th>
        <th class="p-4 stat-label">Returned</th>
        <th class="p-4 stat-label">Late fee</th>
        <th class="p-4 stat-label">Total</th>
        <th class="p-4 stat-label">Status</th>
        <th class="p-4 stat-label"></th>
      </tr>
    </thead>
    <tbody>
      {% for rental in rows %}{{ row(rental, actionable) }}{% endfor %}
    </tbody>
  </table>
</div>
{% endmacro %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">Rentals</h1>
  <p class="mt-1 text-sm text-muted">{{ active | length }} vehicle(s) currently out</p>
</div>

{% if active %}
  <div class="mb-8">{{ table(active, True) }}</div>
{% elif not finished %}
  <div class="card mb-8 p-10 text-center">
    <p class="text-base font-semibold text-ink">No rentals yet</p>
    <p class="mt-1.5 text-sm text-muted">
      A rental appears here once a confirmed reservation is handed over.
    </p>
    <a class="btn btn-primary mt-5" href="{{ url_for('admin_reservations.queue') }}">Go to reservations</a>
  </div>
{% else %}
  <div class="card mb-8 p-10 text-center">
    <p class="text-base font-semibold text-ink">No vehicle is out right now.</p>
  </div>
{% endif %}

{% if finished %}
  <h2 class="mb-3 text-sm font-bold tracking-tight text-ink">Completed</h2>
  {{ table(finished, False) }}
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Register and link**

In `rental/__init__.py`:

```python
from .admin import rentals as admin_rentals
```
```python
    app.register_blueprint(admin_rentals.bp)
```

Add a Rentals link to `rental/templates/partials/_admin_nav.html` pointing at
`admin_rentals.index`, following the shape of the existing links.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_admin_lifecycle.py -q`
Expected: 17 passed.

If `test_a_late_return_adds_the_late_fee_to_the_total` gives 1 late day rather
than 2, print `rental.late_hours` and check the arithmetic against
`late_charge` in `rental/domain/pricing.py` — `late_days = ceil(late_hours/24)`.
Adjust `starts_in_days`/`days` in the fixture call until the overrun is
comfortably between 25 and 47 hours, and update the expected figures to match.
Do not change `late_charge`.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: **305 passed**.

- [ ] **Step 9: Commit**

```bash
git add rental/admin/rentals.py rental/admin/reservations.py rental/__init__.py \
        rental/templates/admin/rentals.html rental/templates/admin/reservations.html \
        rental/templates/partials/_admin_nav.html tests/test_admin_lifecycle.py
git commit -m "feat: start a rental at pickup and close it with its late fee"
```

---

### Task 10: My Rentals and rental detail

Where a customer sees a total larger than the one they booked — and the reason
for it.

**Files:**
- Modify: `rental/portal.py`
- Create: `rental/templates/customer/rentals.html`, `rental/templates/customer/rental_detail.html`
- Test: `tests/test_my_area.py` (append)

**Interfaces:**
- Consumes: the `Rental` rows Task 9 writes; `portal.owned_reservation`'s shape from Task 7.
- Produces:
  - `portal.rentals` — `GET /my/rentals`
  - `portal.rental_detail` — `GET /my/rentals/<rental_id>`
  - `portal.owned_rental(rental_id) -> Rental`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_my_area.py`:

```python
from rental.models import Rental


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_my_area.py -q -k rental`
Expected: 404 on `/my/rentals`.

- [ ] **Step 3: Write the routes**

Append to `rental/portal.py`:

```python
def owned_rental(rental_id: int) -> Rental:
    """Load one of the signed-in customer's rentals, or 404.

    The owner filter is part of the query, exactly as in `owned_reservation`.
    """
    db = get_session()
    rental = db.scalars(
        select(Rental)
        .options(joinedload(Rental.vehicle))
        .where(Rental.id == rental_id)
        .where(Rental.customer_id == current_user().id)
    ).first()
    if rental is None:
        abort(404)
    return rental


@bp.route("/rentals")
@customer_required
def rentals():
    """Every rental this customer has had, the current one first."""
    db = get_session()
    rows = db.scalars(
        select(Rental)
        .options(joinedload(Rental.vehicle))
        .where(Rental.customer_id == current_user().id)
        .order_by(Rental.actual_pickup.desc(), Rental.id.desc())
    ).all()
    return render_template("customer/rentals.html", rentals=rows)


@bp.route("/rentals/<int:rental_id>")
@customer_required
def rental_detail(rental_id: int):
    """One rental, with any late fee shown as its own line.

    A customer seeing a larger total than they booked is owed the reason.
    """
    return render_template("customer/rental_detail.html", rental=owned_rental(rental_id))
```

- [ ] **Step 4: Write the templates**

Create `rental/templates/customer/rentals.html`:

```jinja
{% extends 'layout_public.html' %}
{% block title %}My rentals &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">My Rentals</h1>
  <p class="mt-1 text-sm text-muted">
    {{ rentals | length }} rental{{ '' if rentals | length == 1 else 's' }}
  </p>
</div>

{% if rentals %}
  <div class="card overflow-hidden">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-line text-left">
          <th class="p-4 stat-label">Reference</th>
          <th class="p-4 stat-label">Vehicle</th>
          <th class="p-4 stat-label">Collected</th>
          <th class="p-4 stat-label">Due back</th>
          <th class="p-4 stat-label">Total</th>
          <th class="p-4 stat-label">Status</th>
        </tr>
      </thead>
      <tbody>
        {% for rental in rentals %}
          <tr class="border-b border-line last:border-0">
            <td class="p-4">
              <a class="font-semibold text-ink underline"
                 href="{{ url_for('portal.rental_detail', rental_id=rental.id) }}">
                {{ rental.rental_number }}
              </a>
            </td>
            <td class="p-4">{{ rental.vehicle.display_name }}</td>
            <td class="p-4">{{ rental.actual_pickup.strftime('%d %b %Y, %I:%M %p') }}</td>
            <td class="p-4">{{ rental.expected_return.strftime('%d %b %Y, %I:%M %p') }}</td>
            <td class="p-4 font-semibold">₱{{ '{:,.2f}'.format(rental.total_amount) }}</td>
            <td class="p-4"><span class="pill {{ rental.badge_class }}">{{ rental.status }}</span></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% else %}
  <div class="card p-10 text-center">
    <p class="text-base font-semibold text-ink">No rentals yet</p>
    <p class="mt-1.5 text-sm text-muted">
      A rental appears here once you collect a vehicle you have booked.
    </p>
    <a class="btn btn-primary mt-5" href="{{ url_for('portal.reservations') }}">My Reservations</a>
  </div>
{% endif %}
{% endblock %}
```

Create `rental/templates/customer/rental_detail.html`:

```jinja
{% extends 'layout_public.html' %}
{% block title %}{{ rental.rental_number }} &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6 flex items-center gap-3">
  <h1 class="page-title">{{ rental.rental_number }}</h1>
  <span class="pill {{ rental.badge_class }}">{{ rental.status }}</span>
</div>

<div class="grid gap-6 lg:grid-cols-[3fr_2fr]">
  <div class="card p-5">
    <h2 class="text-base font-bold tracking-tight text-ink">{{ rental.vehicle.display_name }}</h2>
    <p class="text-sm text-muted">{{ rental.vehicle.vehicle_type }} &middot; {{ rental.vehicle.plate_number }}</p>

    <dl class="mt-5 grid grid-cols-2 gap-4">
      <div>
        <dt class="stat-label">Collected</dt>
        <dd class="text-sm font-semibold text-ink">{{ rental.actual_pickup.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Due back</dt>
        <dd class="text-sm font-semibold text-ink">{{ rental.expected_return.strftime('%d %b %Y, %I:%M %p') }}</dd>
      </div>
      <div>
        <dt class="stat-label">Returned</dt>
        <dd class="text-sm font-semibold text-ink">
          {{ rental.actual_return.strftime('%d %b %Y, %I:%M %p') if rental.actual_return else 'Still out' }}
        </dd>
      </div>
      <div>
        <dt class="stat-label">Duration</dt>
        <dd class="text-sm font-semibold text-ink">
          {{ rental.rental_hours }} hour(s) &middot; {{ rental.rental_days }} billable day(s)
        </dd>
      </div>
    </dl>
  </div>

  <div class="lg:sticky lg:top-24 lg:self-start">
    <div class="card p-5">
      <table class="w-full text-sm">
        <tbody>
          <tr class="border-b border-line">
            <td class="py-2"><span class="font-medium text-ink">Base rental</span></td>
            <td class="py-2 text-right font-semibold text-ink">₱{{ '{:,.2f}'.format(rental.base_amount) }}</td>
          </tr>
          <tr class="border-b border-line">
            <td class="py-2"><span class="font-medium text-ink">Additional fees</span></td>
            <td class="py-2 text-right font-semibold text-ink">₱{{ '{:,.2f}'.format(rental.additional_fees) }}</td>
          </tr>
          {% if rental.late_fee %}
            <tr class="border-b border-line">
              <td class="py-2">
                <span class="font-medium text-ink">Late return</span>
                <span class="block text-xs text-muted">{{ rental.late_hours }} hour(s) past the due time</span>
              </td>
              <td class="py-2 text-right font-semibold text-ink">₱{{ '{:,.2f}'.format(rental.late_fee) }}</td>
            </tr>
          {% endif %}
          <tr>
            <td class="pt-3 text-sm font-semibold text-ink">Total</td>
            <td class="pt-3 text-right"><span class="rate">₱{{ '{:,.2f}'.format(rental.total_amount) }}</span></td>
          </tr>
        </tbody>
      </table>

      <div class="mt-4 flex items-center justify-between border-t border-line pt-4">
        <span class="stat-label">Payment Status</span>
        <span class="pill pill-warning">Pending</span>
      </div>
      <p class="mt-1.5 text-xs text-muted">Settle any balance at the counter.</p>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_my_area.py -q`
Expected: 17 passed.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: **310 passed**.

- [ ] **Step 7: Commit**

```bash
git add rental/portal.py rental/templates/customer/rentals.html \
        rental/templates/customer/rental_detail.html tests/test_my_area.py
git commit -m "feat: My Rentals, with any late fee shown as its own line"
```

---

### Task 11: The profile page and the customer navigation

**Files:**
- Modify: `rental/forms.py`, `rental/portal.py`, `rental/templates/partials/_public_nav.html`, `rental/templates/customer/dashboard.html`
- Create: `rental/templates/customer/profile.html`
- Test: `tests/test_my_area.py` (append)

**Interfaces:**
- Consumes: `User.{full_name, phone, email}`; the existing `EMAIL_PATTERN` and `FlaskForm` conventions in `rental/forms.py`.
- Produces: `ProfileForm`; `portal.profile` — `GET`/`POST /my/profile`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_my_area.py`:

```python
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
    customer_client.post(
        "/my/profile",
        data={"full_name": "Maria Santos", "email": "admin@example.com", "phone": "0917 000 0001"},
    )

    with app.app_context():
        user = get_session().query(User).filter_by(username="maria").one()
        assert user.email == "maria@example.com"


def test_profile_rejects_a_malformed_email(customer_client, app):
    customer_client.post(
        "/my/profile",
        data={"full_name": "Maria Santos", "email": "not-an-email", "phone": "0917 000 0001"},
    )

    with app.app_context():
        assert get_session().query(User).filter_by(username="maria").one().email == "maria@example.com"


def test_the_customer_navigation_links_to_every_own_page(customer_client):
    body = customer_client.get("/my").get_data(as_text=True)

    assert "/my/reservations" in body
    assert "/my/rentals" in body
    assert "/my/profile" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_my_area.py -q -k "profile or navigation"`
Expected: 404 on `/my/profile`.

- [ ] **Step 3: Add `ProfileForm` to `rental/forms.py`**

```python
class ProfileForm(FlaskForm):
    """A customer's own contact details. Username and role are not editable here."""

    full_name = StringField(
        "Full name", validators=[DataRequired(), Length(max=120)]
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Length(max=120),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Save changes")
```

- [ ] **Step 4: Add the route to `rental/portal.py`**

Add `from .forms import ProfileForm` and `from .models import User` to the
imports, and append:

```python
@bp.route("/profile", methods=["GET", "POST"])
@customer_required
def profile():
    """The customer's own contact details."""
    db = get_session()
    user = current_user()
    form = ProfileForm(obj=user)

    if form.validate_on_submit():
        taken = db.scalars(
            select(User).where(User.email == form.email.data).where(User.id != user.id)
        ).first()
        if taken is not None:
            form.email.errors.append("That email address is already in use.")
        else:
            user.full_name = form.full_name.data
            user.email = form.email.data
            user.phone = form.phone.data
            db.commit()
            flash("Your profile was updated.", "success")
            return redirect(url_for("portal.profile"))

    return render_template("customer/profile.html", form=form, user=user)
```

- [ ] **Step 5: Write `rental/templates/customer/profile.html`**

```jinja
{% extends 'layout_public.html' %}
{% block title %}My profile &middot; Vehicle Rental{% endblock %}

{% block content %}
<div class="mb-6">
  <h1 class="page-title">My Profile</h1>
  <p class="mt-1 text-sm text-muted">Signed in as {{ user.username }}</p>
</div>

<div class="card max-w-xl p-5">
  <form method="post">
    {{ form.hidden_tag() }}
    {% for field in [form.full_name, form.email, form.phone] %}
      <div class="mb-4">
        <label class="field-label" for="{{ field.id }}">{{ field.label.text }}</label>
        {{ field(class='field') }}
        {% for error in field.errors %}
          <p class="mt-1 text-xs text-danger">{{ error }}</p>
        {% endfor %}
      </div>
    {% endfor %}
    <button type="submit" class="btn btn-primary">Save changes</button>
  </form>
</div>
{% endblock %}
```

`text-danger` must exist in `rental/static/src/input.css`. Check with
`grep -n 'text-danger' rental/static/src/input.css rental/templates/auth/*.html`
and copy whatever class the existing auth forms use for field errors instead of
inventing one.

- [ ] **Step 6: Add the navigation links**

In `rental/templates/partials/_public_nav.html`, inside the branch that renders
for a signed-in customer, add three links — My Reservations
(`portal.reservations`), My Rentals (`portal.rentals`), Profile
(`portal.profile`) — following the exact shape of the links already there.

In `rental/templates/customer/dashboard.html`, make the four stat cards lead
somewhere: wrap the "My Reservations" card in a link to
`portal.reservations` and the two rental cards in links to `portal.rentals`,
and the "Available Vehicles" card in a link to `public.browse`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_my_area.py -q`
Expected: 22 passed.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: **315 passed**.

- [ ] **Step 9: Commit**

```bash
git add rental/forms.py rental/portal.py rental/templates/customer/profile.html \
        rental/templates/partials/_public_nav.html \
        rental/templates/customer/dashboard.html tests/test_my_area.py
git commit -m "feat: the customer profile page and the my-area navigation"
```

---

### Task 12: The journey end to end, the Tailwind rebuild, and the sweep

The demo scenario as one test, plus the housekeeping that must happen exactly
once and last.

**Files:**
- Create: `tests/test_booking_journey.py`
- Modify: `rental/static/css/output.css` (rebuilt), `README.md`
- Test: the whole suite

**Interfaces:**
- Consumes: every route Tasks 1-11 produced. This task adds no new interface.

- [ ] **Step 1: Write the journey test**

Create `tests/test_booking_journey.py`:

```python
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
        # The rental started "now"; the vehicle was due back at the booked time.
        rental.expected_return = return_at
        db.commit()

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
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_booking_journey.py -q`
Expected: 1 passed.

If step 7's late fee is 800 rather than 1600, print `rental.late_hours` and
adjust the fixture window so the overrun lands between 25 and 47 hours — the
arithmetic in `late_charge` is correct and tested; the fixture is what moves.

- [ ] **Step 3: Sweep for clock violations**

```bash
grep -rn 'datetime\.now\|utcnow\|date\.today' rental/ --include=*.py
```
Expected: every hit is inside `rental/clock.py`. Any other hit is a bug — route
it through `clock.now()` / `clock.today()` and re-run the suite.

- [ ] **Step 4: Sweep for domain purity and template placement**

```bash
uv run python scripts/check-domain-purity.py
grep -rn 'from .domain\|from rental.domain\|from ..domain' rental/ --include=*.py
```
`rental/scheduling.py`, `rental/portal.py`, `rental/admin/reservations.py` and
`rental/admin/rentals.py` may import the domain. **`rental/booking.py` and
`rental/public.py` may not** — they go through `scheduling`. If either does,
move the call behind a `scheduling` function and re-run.

`tests/test_template_layout.py` already covers the reserved directory names;
confirm it is still green.

- [ ] **Step 5: Confirm no fake functionality shipped**

```bash
grep -rni 'coming soon\|opens soon\|placeholder\|lorem\|TODO' rental/templates/ rental/*.py rental/admin/*.py
```
Expected: no hit that a user can see. The "Online booking opens soon" line
Task 3 replaced must be gone.

- [ ] **Step 6: Rebuild Tailwind — once, here, at the end**

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
  uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git diff --stat rental/static/css/output.css
```

The diff must be non-empty — this phase added classes (`pill-success`,
`btn-sm`, the new grid columns). An empty diff means Tailwind did not see the
new templates; check that every template directory this phase created is inside
the content globs the CLI scans, and re-run.

Then confirm the new classes actually landed:

```bash
grep -c 'pill-success' rental/static/css/output.css
```
Expected: at least 1.

- [ ] **Step 7: Check every page by hand**

```bash
DATABASE_URL=sqlite:///rental.db uv run flask --app rental run --port 5000
```

Walk the journey in a browser as a customer and as an admin: browse with dates,
detail with the live preview, review, confirm, My Reservations, cancel, the
admin queue, confirm, start, My Rentals, mark returned, the late fee on the
rental detail, and the profile page. Confirm each empty state renders. Record
what you saw, and any console error, in the task report.

- [ ] **Step 8: Update the README**

Add a short section describing the booking flow and the three admin actions,
following the shape of the sections already there. Keep it to what the code
does — no roadmap, no future tense.

- [ ] **Step 9: Run the full suite one last time**

Run: `uv run pytest -q`
Expected: **316 passed**.

- [ ] **Step 10: Commit**

```bash
git add tests/test_booking_journey.py rental/static/css/output.css README.md
git commit -m "test: the booking journey end to end, and rebuild the stylesheet"
```

---

## Self-Review Record

Run after every task is complete, before the final whole-branch review.

**Spec coverage** — every section of
`docs/superpowers/specs/2026-09-29-customer-surface-design.md` maps to a task:

| Spec section | Task |
| --- | --- |
| The new boundary, `rental/scheduling.py` | 1 |
| `GET /api/quote`, public, no session | 2 |
| Date-aware detail page, server-rendered verdict and quote | 3 |
| Browse grid answering for the chosen dates | 4 |
| Logged-out visitor picks dates and hits Book; the login round trip | 5 |
| The quote is a snapshot; `reservation_number` via `assign_number()` | 5 |
| Integrity: the row lock and the re-check inside the transaction | 5 (guard proven) |
| The live preview; works with JavaScript disabled | 6 |
| My Reservations, reservation detail, cancel before pickup | 7 |
| Ownership: 404 not 403 | 7 (guard proven) |
| Confirm and reject; `TransitionError` flashed, not a 500 | 8 |
| Start a rental; the reservation stays CONFIRMED | 9 |
| Return, with `late_charge` and its own line | 9, 10 |
| My Rentals, rental detail | 10 |
| The profile page | 11 |
| Empty states on every list | 7, 8, 9, 10, 11 |
| The three testing layers and the walkthrough | 1-11, then 12 |
| "Payment Status: Pending", no payments, no email | 5, 7, 10 |
| The vehicle status caveat (AVAILABLE with future bookings) | 7, 9 — by construction; availability is date overlap, never `vehicle.status` |

**Not in this phase, and deliberately absent:** payments, email, editing a
booking's dates, admin-side booking on a customer's behalf. Phase 4 keeps the
rental management dashboard, the availability view, maintenance, the customers
page, revenue, and the three reports with CSV.

**Test count ladder** — each task's expected total, so a drift is caught the
moment it happens:

| After task | Total |
| --- | --- |
| baseline | 228 |
| 1 | 245 |
| 2 | 251 |
| 3 | 256 |
| 4 | 261 |
| 5 | 274 |
| 6 | 276 |
| 7 | 288 |
| 8 | 296 |
| 9 | 305 |
| 10 | 310 |
| 11 | 315 |
| 12 | 316 |

These are the counts this plan's own test code adds. If a task's actual total
differs, **count the tests you wrote** before assuming the ladder is wrong —
and never adjust a later task's number to paper over a missing test.
