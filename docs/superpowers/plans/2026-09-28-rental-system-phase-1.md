# Vehicle Rental System — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Vehicle Inventory Management System into the foundation of a Vehicle Rental and Reservation System — rental-shaped schema, admin/customer roles, a public storefront a visitor can browse, and an admin fleet console — without yet building booking.

**Architecture:** A server-rendered Flask app keeps its shape. The `inventory` package is renamed `rental` and its one monolithic `vehicles.py` splits into `public.py` (storefront) and an `admin/` sub-package. Six SQLAlchemy models replace two. Sessions carry a `user_id`; the role is read off the `User` row, and three decorators (`login_required`, `admin_required`, `customer_required`) replace the old viewer/editor pair. The anonymous "guest" session is retired because the storefront is genuinely public.

**Tech Stack:** Python 3.12 · Flask 3 · SQLAlchemy 2 · Flask-WTF/WTForms · Jinja2 · Tailwind CSS v4 (standalone CLI via `pytailwindcss`, output committed) · SQLite locally, Neon Postgres on Vercel · pytest

**Spec:** `docs/superpowers/specs/2026-09-28-vehicle-rental-system-design.md` (phase 1 section)

## Global Constraints

- **No new runtime dependencies.** `pyproject.toml`'s `dependencies` list must not grow. Dev dependencies must not grow either.
- **No JavaScript in phase 1.** The existing app's only script is `window.print()`. Menus use `<details>`. The live price preview is phase 3.
- **Money is `Numeric(10, 2)`.** All arithmetic uses `decimal.Decimal` and is quantised with `.quantize(Decimal("0.01"))`. No float ever touches a peso amount.
- **Currency symbol is `₱`** and is written directly in templates.
- **Tailwind output is committed.** After any template or `input.css` change, rebuild with:
  `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify`
  and commit `output.css`. Vercel runs no build step.
  The `SSL_CERT_FILE` prefix is required: the standalone CLI downloads itself on
  first run and fails with `CERTIFICATE_VERIFY_FAILED` without it. The README
  documents this. A rebuild is only needed when a change touches a `class="..."`
  attribute or `input.css`; renaming a Python identifier never needs one.
- **The Tailwind build is scoped to `rental/templates`** by `source(none)` on
  line 1 of `input.css`. Do not remove it. Without it, v4's automatic detection
  scans the whole repository and compiles class names out of the Markdown code
  blocks in `docs/`, putting CSS for templates that do not exist yet into the
  served stylesheet.
- **Class names chosen in Python must be listed** in `input.css`'s `@source inline(...)`, or Tailwind will not find them when scanning templates.
- **Tables are never created at import time.** DDL happens only in `flask` CLI commands.
- **Product name:** `Vehicle Rental and Reservation System`. **Tagline:** `Online reservation + vehicle availability + automatic rental calculation`.
- **Vehicle statuses** are exactly `AVAILABLE`, `RESERVED`, `RENTED`, `MAINTENANCE` — stored uppercase.
- **Run tests with** `uv run pytest -q`. Every task ends with the whole suite green.
- **No dead buttons.** A control that renders must work. Anything belonging to phases 2–4 is not rendered at all.

---

### Task 1: Rename the package `inventory` → `rental`

Purely mechanical, and cheapest now before the file count grows. Nothing behavioural changes; the suite must stay green.

**Files:**
- Rename: `inventory/` → `rental/` (use `git mv` so history follows)
- Modify: `app.py`, `pyproject.toml`, `.vercelignore`, `rental/db.py`, `rental/static/src/input.css`
- Modify: every file under `tests/` that imports `inventory`

**Interfaces:**
- Consumes: nothing
- Produces: the package is importable as `rental`; `rental.create_app()` is the factory; `rental.db.DEFAULT_SQLITE_URL == "sqlite:///rental.db"`

- [ ] **Step 1: Run the suite first, so you know it was green before you started**

Run: `uv run pytest -q`
Expected: all tests pass. If not, stop and report — do not start renaming on top of a red suite.

- [ ] **Step 2: Move the package and rewrite every import**

```bash
git mv inventory rental
grep -rl 'inventory' --include='*.py' --include='*.toml' --include='*.css' . \
  | grep -v '\.venv' | grep -v '__pycache__' \
  | xargs sed -i 's/\bfrom inventory\b/from rental/g; s/\bimport inventory\b/import rental/g'
sed -i 's/from inventory/from rental/g' app.py
```

- [ ] **Step 3: Fix the remaining non-import references by hand**

In `rental/db.py`, change the default database file:

```python
# Used when no DATABASE_URL is provided (local development / demos).
DEFAULT_SQLITE_URL = "sqlite:///rental.db"
```

In `rental/static/src/input.css`, the `@source` path is relative to the file and does not mention the package, so it needs no change. Confirm it still reads `@source "../../templates";`.

In `pyproject.toml`:

```toml
[project]
name = "vehicle-rental"
version = "0.1.0"
description = "A Flask + SQLAlchemy vehicle rental and reservation system."
```

`[tool.pytest.ini_options].pythonpath = ["."]` stays as it is — it points at the project root, not the package.

In `.vercelignore`, update the comment and the path:

```text
# CSS build sources. Only the built rental/static/css/output.css is served,
# and it is committed, so Vercel needs no build step.
rental/static/src/
```

- [ ] **Step 4: Check nothing still refers to the old package**

Run: `grep -rn '\binventory\b' --include='*.py' --include='*.toml' --include='*.html' --include='*.css' . | grep -v '\.venv' | grep -v '__pycache__' | grep -v '\.git/' | grep -v docs/`
Expected: no output. (`docs/` is excluded because the spec quotes the old name deliberately.)

- [ ] **Step 5: Run the suite**

Run: `uv run pytest -q`
Expected: the same number of tests pass as in Step 1.

- [ ] **Step 6: Commit**

```bash
rm -rf inventory.db rental/__pycache__ tests/__pycache__ .pytest_cache
git add -A
git commit -m "refactor: rename the inventory package to rental"
```

---

### Task 2: Rename `make` → `brand` and `remarks` → `description`

The requirements name these columns `brand` and `description`. `reset-db` drops everything later, so the rename costs nothing. Still purely mechanical.

**Files:**
- Modify: `rental/models.py`, `rental/forms.py`, `rental/vehicles.py`, `rental/reports.py`, `rental/cli.py`
- Modify: `rental/templates/partials/_vehicle_table.html`, `rental/templates/partials/_vehicle_form_fields.html`, `rental/templates/vehicle_detail.html`, `rental/templates/vehicle_delete.html`, `rental/templates/search.html`
- Modify: `tests/conftest.py`, `tests/test_vehicles.py`, `tests/test_guest.py`

**Interfaces:**
- Consumes: Task 1's `rental` package
- Produces: `Vehicle.brand` and `Vehicle.description`; `VehicleForm.brand` and `VehicleForm.description`; the CSV column list contains `brand` and `description`

- [ ] **Step 1: Rename in Python**

```bash
grep -rl --include='*.py' -e 'make' -e 'remarks' rental tests \
  | xargs sed -i 's/\bVehicle\.make\b/Vehicle.brand/g; s/\bvehicle\.make\b/vehicle.brand/g; s/\bform\.make\b/form.brand/g; s/\bremarks\b/description/g'
```

Then open each of `rental/models.py`, `rental/forms.py`, `rental/vehicles.py`, `rental/reports.py`, `rental/cli.py` and fix what the pattern could not reach:

- `models.py`: the column becomes `brand: Mapped[str] = mapped_column(String(50), nullable=False)`, and `__repr__` uses `self.brand`.
- `forms.py`: the field becomes `brand = StringField("Brand", filters=[clean_text], validators=[DataRequired(message="Brand is required."), Length(max=50)])`.
- `vehicles.py`: `SORTABLE_COLUMNS` key `"make"` becomes `"brand"` mapping to `Vehicle.brand`; `copy_form_into_vehicle` assigns `vehicle.brand = form.brand.data`; the `search()` ilike clause uses `Vehicle.brand`.
- `reports.py`: `CSV_COLUMNS` replaces `"make"` with `"brand"` and `"remarks"` with `"description"`.
- `cli.py`: the `SAMPLE_VEHICLES` unpacking variable `make` becomes `brand` and the `Vehicle(...)` kwarg becomes `brand=brand`, `description=description or None`.

- [ ] **Step 2: Rename in the templates**

```bash
grep -rl -e 'make' -e 'remarks' rental/templates \
  | xargs sed -i 's/vehicle\.make/vehicle.brand/g; s/form\.make/form.brand/g; s/\bremarks\b/description/g'
```

Then check each template by eye for user-visible copy: the table header and the detail page's label must read **Brand** and **Description**, not "Make" and "Remarks". The sort link whose query string reads `sort=make` becomes `sort=brand`.

- [ ] **Step 3: Check nothing was missed**

Run: `grep -rn '\bmake\b\|\bremarks\b' --include='*.py' --include='*.html' rental tests`
Expected: no output.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Rebuild the stylesheet and commit**

```bash
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "refactor: rename Vehicle.make to brand and remarks to description"
```

---

### Task 3: Vehicle rental columns and the new status vocabulary

Adds the columns that make a vehicle rentable, and replaces the four inventory statuses with the four rental ones.

**Files:**
- Modify: `rental/models.py`, `rental/forms.py`, `rental/vehicles.py`, `rental/cli.py`
- Modify: `rental/templates/partials/_vehicle_form_fields.html`, `rental/templates/vehicle_detail.html`
- Modify: `tests/conftest.py`, `tests/test_vehicles.py`, `tests/test_reports.py`, `tests/test_guest.py`
- Test: `tests/test_models.py` (create)

**Interfaces:**
- Consumes: Task 2's `Vehicle.brand` / `Vehicle.description`
- Produces:
  - `VEHICLE_TYPES: list[str]`, `TRANSMISSIONS: list[str]`, `FUEL_TYPES: list[str]`, `VEHICLE_STATUSES: list[str]`
  - `STATUS_BADGES: dict[str, str]`
  - `Vehicle.seats: int`, `.transmission: str`, `.fuel_type: str`, `.daily_rate: Decimal`, `.hourly_rate: Decimal | None`, `.image_url: str | None`, `.is_active: bool`
  - `Vehicle.display_name -> str`, `Vehicle.type_slug -> str`, `Vehicle.badge_class -> str`
  - `VehicleForm` fields `seats`, `transmission`, `fuel_type`, `daily_rate`, `hourly_rate`, `image_url`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
"""The model layer: vocabularies, defaults and derived properties."""

from __future__ import annotations

from decimal import Decimal

from rental.models import STATUS_BADGES, VEHICLE_STATUSES, VEHICLE_TYPES, Vehicle


def test_vehicle_statuses_are_the_four_rental_states():
    assert VEHICLE_STATUSES == ["AVAILABLE", "RESERVED", "RENTED", "MAINTENANCE"]


def test_every_vehicle_status_has_a_badge_colour():
    assert set(STATUS_BADGES) == set(VEHICLE_STATUSES)


def test_vehicle_types_include_the_rental_body_styles():
    assert "Hatchback" in VEHICLE_TYPES
    assert "MPV" in VEHICLE_TYPES


def test_display_name_reads_as_a_rental_listing():
    vehicle = Vehicle(brand="Toyota", model="Vios", year=2024)
    assert vehicle.display_name == "Toyota Vios 2024"


def test_type_slug_picks_the_silhouette_filename():
    assert Vehicle(vehicle_type="MPV").type_slug == "mpv"
    assert Vehicle(vehicle_type="Sedan").type_slug == "sedan"


def test_daily_only_vehicle_has_no_hourly_rate():
    vehicle = Vehicle(daily_rate=Decimal("1500.00"))
    assert vehicle.hourly_rate is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'VEHICLE_STATUSES'`

- [ ] **Step 3: Rewrite the vocabularies and extend `Vehicle`**

In `rental/models.py`, replace the `VEHICLE_TYPES` / `STATUSES` / `STATUS_BADGES` block with:

```python
# The fixed option lists used by the forms, the filters and the reports.
VEHICLE_TYPES = ["Sedan", "Hatchback", "MPV", "SUV", "Pickup", "Van", "Truck", "Motorcycle"]
TRANSMISSIONS = ["Automatic", "Manual"]
FUEL_TYPES = ["Gasoline", "Diesel", "Electric", "Hybrid"]

# A vehicle's state right now. Whether it can be booked for a particular date
# range is computed from overlapping reservations, rentals and maintenance --
# never read off this column. See the spec's "Vehicle status is not the same
# thing as availability".
VEHICLE_STATUSES = ["AVAILABLE", "RESERVED", "RENTED", "MAINTENANCE"]

STATUS_BADGES = {
    "AVAILABLE": "pill-green",
    "RESERVED": "pill-amber",
    "RENTED": "pill-blue",
    "MAINTENANCE": "pill-slate",
}
```

Add `Boolean` and `Numeric` to the existing `from sqlalchemy import ...` line, and `from decimal import Decimal` at the top.

Add these columns to `Vehicle`, after `status`:

```python
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    transmission: Mapped[str] = mapped_column(String(20), nullable=False, default="Automatic")
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False, default="Gasoline")
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # NULL means this vehicle is daily-only: a part day rounds up to a whole one.
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # An absolute URL or a path under static/. Blank falls back to the per-type
    # silhouette, so a vehicle never renders a broken image.
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # False is what "Disable Vehicle" does: hidden from the storefront and
    # unbookable, but its history is kept.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Change the `status` column default to `"AVAILABLE"`, and add two properties next to `badge_class`:

```python
    @property
    def display_name(self) -> str:
        """The vehicle as a customer sees it named, e.g. 'Toyota Vios 2024'."""
        return f"{self.brand} {self.model} {self.year}"

    @property
    def type_slug(self) -> str:
        """The vehicle type lower-cased, which is the silhouette's filename."""
        return (self.vehicle_type or "sedan").lower()
```

- [ ] **Step 4: Run the model test**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Extend `VehicleForm`**

In `rental/forms.py`, import the new vocabularies and `DecimalField`:

```python
from wtforms import DecimalField  # add to the existing wtforms import
from .models import FUEL_TYPES, TRANSMISSIONS, VEHICLE_STATUSES, VEHICLE_TYPES
```

Replace the `status` field's choices and add the rental fields:

```python
    status = SelectField(
        "Status",
        choices=[(s, s.title()) for s in VEHICLE_STATUSES],
        validators=[DataRequired()],
    )
    seats = IntegerField(
        "Seats",
        validators=[
            DataRequired(message="Number of seats is required."),
            NumberRange(min=1, max=30, message="Seats must be between 1 and 30."),
        ],
    )
    transmission = SelectField(
        "Transmission", choices=[(t, t) for t in TRANSMISSIONS], validators=[DataRequired()]
    )
    fuel_type = SelectField(
        "Fuel type", choices=[(f, f) for f in FUEL_TYPES], validators=[DataRequired()]
    )
    daily_rate = DecimalField(
        "Daily rate (PHP)",
        places=2,
        validators=[
            DataRequired(message="Daily rate is required."),
            NumberRange(min=0, message="Daily rate cannot be negative."),
        ],
    )
    hourly_rate = DecimalField(
        "Hourly rate (PHP)",
        places=2,
        validators=[Optional(), NumberRange(min=0, message="Hourly rate cannot be negative.")],
    )
    image_url = StringField(
        "Image URL", filters=[clean_text], validators=[Optional(), Length(max=500)]
    )
```

`hourly_rate` is left blank for a daily-only vehicle; `Optional()` turns the empty string into `None`.

In `rental/vehicles.py`, extend `copy_form_into_vehicle` with the six new assignments:

```python
    vehicle.seats = form.seats.data
    vehicle.transmission = form.transmission.data
    vehicle.fuel_type = form.fuel_type.data
    vehicle.daily_rate = form.daily_rate.data
    vehicle.hourly_rate = form.hourly_rate.data
    vehicle.image_url = form.image_url.data
```

- [ ] **Step 6: Render the new fields**

In `rental/templates/partials/_vehicle_form_fields.html`, add rows for `seats`, `transmission`, `fuel_type`, `daily_rate`, `hourly_rate` and `image_url`, copying the markup pattern the existing fields use (label with `.field-label`, input with `.field`, errors with `.field-error`). Add a hint under `hourly_rate`:

```html
<p class="field-hint">Leave blank for a daily-only vehicle.</p>
```

In `rental/templates/vehicle_detail.html`, add the same six to the definition list, formatting money as `₱{{ '{:,.2f}'.format(vehicle.daily_rate) }}`.

- [ ] **Step 7: Update the fixtures and the sample data**

In `tests/conftest.py`, the `sample_vehicle` fixture's `Vehicle(...)` needs the now-required fields:

```python
        vehicle = Vehicle(
            plate_number="ABC 1234",
            brand="Toyota",
            model="Hilux",
            year=2021,
            vehicle_type="Pickup",
            color="White",
            status="AVAILABLE",
            seats=5,
            transmission="Automatic",
            fuel_type="Diesel",
            daily_rate=Decimal("2200.00"),
            date_acquired=date(2021, 3, 15),
        )
```

Add `from decimal import Decimal` to the imports.

In `tests/test_vehicles.py`, `NEW_VEHICLE` gains `"seats": "5"`, `"transmission": "Automatic"`, `"fuel_type": "Gasoline"`, `"daily_rate": "1500.00"`, `"hourly_rate": ""`, `"image_url": ""`, and `"status": "AVAILABLE"`. Any assertion matching `b"Available"` becomes `b"AVAILABLE"`.

In `rental/cli.py`, `SAMPLE_VEHICLES` is rewritten wholesale in Task 8. For now, make it insert cleanly: append `seats`, `transmission`, `fuel_type` and `daily_rate` to each tuple and to the unpacking, and change every status string to uppercase.

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 9: Rebuild the stylesheet and commit**

```bash
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add rental fields and the four rental statuses to Vehicle"
```

---

### Task 4: The `RentalRates` model

One row holding the fees every price calculation reads. Nothing in a template may hardcode a fee.

**Files:**
- Modify: `rental/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Task 3's `rental.models`
- Produces: `RentalRates` with `additional_driver_fee_per_day`, `insurance_fee_per_day`, `late_fee_per_day`, `updated_at`, and the classmethod `RentalRates.current(session) -> RentalRates`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_rental_rates_current_creates_the_single_row(app):
    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        db = get_session()
        rates = RentalRates.current(db)
        assert rates.id == 1
        assert rates.additional_driver_fee_per_day == Decimal("500.00")
        assert rates.insurance_fee_per_day == Decimal("300.00")
        assert rates.late_fee_per_day == Decimal("800.00")


def test_rental_rates_current_reuses_the_row_and_keeps_edits(app):
    from rental.db import get_session
    from rental.models import RentalRates

    with app.app_context():
        db = get_session()
        RentalRates.current(db).insurance_fee_per_day = Decimal("350.00")
        db.commit()

        again = RentalRates.current(db)
        assert again.id == 1
        assert again.insurance_fee_per_day == Decimal("350.00")
        assert db.query(RentalRates).count() == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'RentalRates'`

- [ ] **Step 3: Add the model**

In `rental/models.py`, after `Vehicle`:

```python
# The fees a rental can attract, on top of the vehicle's own daily rate. These
# live in the database rather than in the templates so an admin can change them
# (requirement 21) without a deploy.
DEFAULT_ADDITIONAL_DRIVER_FEE = Decimal("500.00")
DEFAULT_INSURANCE_FEE = Decimal("300.00")
DEFAULT_LATE_FEE = Decimal("800.00")


class RentalRates(Base):
    """The system-wide fee schedule. Exactly one row, id 1."""

    __tablename__ = "rental_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    additional_driver_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_ADDITIONAL_DRIVER_FEE
    )
    insurance_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_INSURANCE_FEE
    )
    late_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_LATE_FEE
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    @classmethod
    def current(cls, session) -> "RentalRates":
        """Return the one rates row, creating it with the defaults if it is missing.

        Every caller gets a row, so no page has to handle the table being empty
        -- which it is on a database created by ``init-db`` without a seed.
        """
        rates = session.get(cls, 1)
        if rates is None:
            rates = cls(id=1)
            session.add(rates)
            session.commit()
        return rates
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add rental/models.py tests/test_models.py
git commit -m "feat: add the RentalRates fee schedule model"
```

---

### Task 5: The `Reservation`, `Rental` and `Maintenance` models

The tables the booking engine will write to. Phase 1 creates them and nothing more — no routes, no forms.

**Files:**
- Modify: `rental/models.py`, `rental/static/src/input.css`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Task 4's `rental.models`
- Produces:
  - `RESERVATION_STATUSES`, `RENTAL_STATUSES`, `MAINTENANCE_STATUSES`, `RESERVATION_BADGES`, `RENTAL_BADGES`
  - `Reservation` with the spec's columns and `assign_number() -> None`
  - `Rental` with the spec's columns and `assign_number() -> None`
  - `Maintenance` with the spec's columns and the property `blocks_booking -> bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_reservation_and_rental_statuses_match_the_requirements():
    from rental.models import RENTAL_STATUSES, RESERVATION_STATUSES

    assert RESERVATION_STATUSES == [
        "PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "REJECTED",
    ]
    assert RENTAL_STATUSES == ["ACTIVE", "COMPLETED"]


def test_every_reservation_and_rental_status_has_a_badge_colour():
    from rental.models import (
        RENTAL_BADGES, RENTAL_STATUSES, RESERVATION_BADGES, RESERVATION_STATUSES,
    )

    assert set(RESERVATION_BADGES) == set(RESERVATION_STATUSES)
    assert set(RENTAL_BADGES) == set(RENTAL_STATUSES)


def test_reservation_number_is_padded_from_the_row_id():
    from rental.models import Reservation

    reservation = Reservation()
    reservation.id = 1
    reservation.assign_number()
    assert reservation.reservation_number == "RES-00001"


def test_rental_number_is_padded_from_the_row_id():
    from rental.models import Rental

    rental = Rental()
    rental.id = 42
    rental.assign_number()
    assert rental.rental_number == "RNT-00042"


def test_unfinished_maintenance_blocks_booking_and_finished_does_not():
    from rental.models import Maintenance

    assert Maintenance(status="SCHEDULED").blocks_booking is True
    assert Maintenance(status="IN_PROGRESS").blocks_booking is True
    assert Maintenance(status="COMPLETED").blocks_booking is False


def test_a_new_vehicle_defaults_to_available_and_active(app):
    from decimal import Decimal

    from rental.db import get_session
    from rental.models import Vehicle

    with app.app_context():
        db = get_session()
        vehicle = Vehicle(
            plate_number="DEF 0001",
            brand="Toyota",
            model="Vios",
            year=2024,
            vehicle_type="Sedan",
            daily_rate=Decimal("1500.00"),
        )
        db.add(vehicle)
        db.commit()

        assert vehicle.status == "AVAILABLE"
        assert vehicle.is_active is True
        assert vehicle.seats == 5
        assert vehicle.transmission == "Automatic"
        assert vehicle.fuel_type == "Gasoline"


def test_the_new_tables_are_created(app):
    from sqlalchemy import inspect

    from rental.db import get_engine

    with app.app_context():
        tables = set(inspect(get_engine()).get_table_names())

    assert {"reservations", "rentals", "maintenance", "rental_rates"} <= tables
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'RESERVATION_STATUSES'`

- [ ] **Step 3: Add the three models**

In `rental/models.py`, add `ForeignKey` and `Text` to the SQLAlchemy imports if not already present, then append:

```python
RESERVATION_STATUSES = ["PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "REJECTED"]
RENTAL_STATUSES = ["ACTIVE", "COMPLETED"]
MAINTENANCE_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED"]

RESERVATION_BADGES = {
    "PENDING": "pill-amber",
    "CONFIRMED": "pill-green",
    "CANCELLED": "pill-slate",
    "COMPLETED": "pill-blue",
    "REJECTED": "pill-red",
}

RENTAL_BADGES = {
    "ACTIVE": "pill-blue",
    "COMPLETED": "pill-green",
}


class Reservation(Base):
    """A customer's request to rent one vehicle over one date range."""

    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)

    # One datetime per endpoint rather than a separate date and time column:
    # overlap comparison is the most important query in the system and it needs
    # a single comparable value. Forms still collect date and time separately.
    pickup_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    return_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    return_location: Mapped[str | None] = mapped_column(String(120), nullable=True)

    want_additional_driver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    want_insurance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    rental_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rental_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The rates are snapshotted here on purpose. An admin editing the vehicle's
    # daily rate afterwards must not change what this customer was quoted.
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    additional_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    def assign_number(self) -> None:
        """Set the human-facing reference from the row id, e.g. RES-00001.

        Called after the insert has been flushed and inside the same
        transaction, so the id exists and two concurrent requests cannot be
        handed the same number.
        """
        self.reservation_number = f"RES-{self.id:05d}"

    @property
    def badge_class(self) -> str:
        return RESERVATION_BADGES.get(self.status, "pill-slate")

    def __repr__(self) -> str:
        return f"<Reservation {self.reservation_number} {self.status}>"


class Rental(Base):
    """A confirmed reservation that has actually been picked up."""

    __tablename__ = "rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rental_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id"), unique=True, nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    # Denormalised so the reports can group without joining through reservations.
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    actual_pickup: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expected_return: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actual_return: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    rental_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rental_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    late_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    additional_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    def assign_number(self) -> None:
        """Set the human-facing reference from the row id, e.g. RNT-00042."""
        self.rental_number = f"RNT-{self.id:05d}"

    @property
    def badge_class(self) -> str:
        return RENTAL_BADGES.get(self.status, "pill-slate")

    def __repr__(self) -> str:
        return f"<Rental {self.rental_number} {self.status}>"


class Maintenance(Base):
    """A window during which a vehicle is off the road."""

    __tablename__ = "maintenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED")
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    @property
    def blocks_booking(self) -> bool:
        """True while this window still takes the vehicle off the road.

        A completed record is history and blocks nothing; a scheduled future one
        blocks its dates, which is what stops a customer booking over it.
        """
        return self.status != "COMPLETED"

    def __repr__(self) -> str:
        return f"<Maintenance vehicle={self.vehicle_id} {self.status}>"
```

- [ ] **Step 4: Add the `pill-red` colour Tailwind will now need**

In `rental/static/src/input.css`, add to the pill block:

```css
  .pill-red   { @apply bg-red-100 text-red-700; }
```

and extend the inline source list so Tailwind keeps every Python-chosen class:

```css
@source inline("pill-green pill-blue pill-amber pill-slate pill-red");
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 6: Run the whole suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the Reservation, Rental and Maintenance models"
```

---

### Task 6: Roles — `User` columns, `current_user`, three decorators, guest retired

The security backbone. After this task a customer cannot reach an admin page and the anonymous guest session is gone.

**Files:**
- Modify: `rental/models.py`, `rental/auth.py`, `rental/vehicles.py`, `rental/reports.py`, `rental/__init__.py`, `rental/forms.py`
- Modify: `rental/templates/base.html`, `login.html`, `partials/_nav_links.html`, `partials/_vehicle_table.html`, `403.html`
- Modify: `tests/conftest.py`, `tests/test_auth.py`
- Delete: `tests/test_guest.py`

`tests/test_roles.py` is NOT created here. Its routes do not exist until Task 11,
and committing a test file marked skip would leave the suite carrying disabled
tests for five tasks. Task 11 writes it against routes that exist.

**Interfaces:**
- Consumes: Task 5's models
- Produces:
  - `ROLES = ["admin", "customer"]`
  - `User.role`, `.full_name`, `.phone`, `.is_active`, `.reset_requested_at`, `.must_change_password`
  - `User.is_admin -> bool`, `User.display_name -> str`
  - `rental.auth.current_user() -> User | None`, `current_role() -> str | None`
  - `rental.auth.login_required`, `admin_required`, `customer_required` decorators
  - `rental.auth.home_for(user) -> str`, `safe_next_page(target, user) -> str`
  - context processor exposes `current_user`, `current_role`, `is_admin`, `is_customer`

- [ ] **Step 1: Write the failing test**

The role matrix itself belongs to Task 11, which builds the routes it asserts on.
What is testable here is the decorator behaviour and the retirement of guest
mode, both of which apply to the routes that already exist. Add to
`tests/test_auth.py`:

```python
def test_guest_mode_is_gone(client):
    assert client.post("/guest").status_code == 404


def test_an_admin_reaches_an_admin_guarded_page(admin_client):
    assert admin_client.get("/vehicles").status_code == 200


def test_a_customer_is_refused_an_admin_guarded_page(customer_client):
    assert customer_client.get("/vehicles").status_code == 403


def test_an_anonymous_visitor_is_redirected_with_a_next_parameter(client):
    response = client.get("/vehicles")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]
```

Task 11 will move these four into `tests/test_roles.py` alongside the full
matrix, once the final URLs exist. For reference, that matrix is:

```python
"""Who may reach which page. One table, three kinds of session."""

from __future__ import annotations

import pytest

PUBLIC_PAGES = ["/", "/vehicles"]
ADMIN_PAGES = ["/admin", "/admin/vehicles", "/admin/vehicles/add", "/admin/rates"]
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
```

Do not create that file in this task — it is reproduced above only so Task 11
has the exact matrix to write. Creating it now would mean committing a test file
that cannot pass.

- [ ] **Step 2: Rewrite `tests/conftest.py`**

```python
"""Shared pytest fixtures: a fresh in-memory SQLite database for every test."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rental import create_app
from rental.db import get_engine, get_session
from rental.models import Base, User, Vehicle

TEST_CONFIG = {
    # "sqlite://" is an in-memory database. db.create_db_engine gives it a
    # StaticPool so the whole test shares one connection.
    "DATABASE_URL": "sqlite://",
    "TESTING": True,
    "SECRET_KEY": "test-secret",
    # Turning CSRF off lets the tests post plain dictionaries. The tokens
    # themselves are Flask-WTF's job, not this project's.
    "WTF_CSRF_ENABLED": False,
}

ADMIN_PASSWORD = "secret123"
CUSTOMER_PASSWORD = "secret123"


@pytest.fixture
def app():
    """An app on an empty in-memory database holding one admin and one customer."""
    app = create_app(TEST_CONFIG)

    with app.app_context():
        Base.metadata.create_all(get_engine())
        db = get_session()

        admin = User(username="admin", email="admin@example.com", role="admin")
        admin.set_password(ADMIN_PASSWORD)

        customer = User(
            username="maria",
            email="maria@example.com",
            role="customer",
            full_name="Maria Santos",
            phone="0917 000 0001",
        )
        customer.set_password(CUSTOMER_PASSWORD)

        db.add_all([admin, customer])
        db.commit()

    yield app


@pytest.fixture
def client(app):
    """A test client with no session at all."""
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """A test client signed in as the admin."""
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    return client


@pytest.fixture
def customer_client(app):
    """A test client signed in as the customer."""
    client = app.test_client()
    client.post("/login", data={"username": "maria", "password": CUSTOMER_PASSWORD})
    return client


@pytest.fixture
def sample_vehicle(app):
    """Insert one bookable vehicle and return its id."""
    with app.app_context():
        db = get_session()
        vehicle = Vehicle(
            plate_number="ABC 1234",
            brand="Toyota",
            model="Hilux",
            year=2021,
            vehicle_type="Pickup",
            color="White",
            status="AVAILABLE",
            seats=5,
            transmission="Automatic",
            fuel_type="Diesel",
            daily_rate=Decimal("2200.00"),
            date_acquired=date(2021, 3, 15),
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id
```

Delete the old guest suite: `git rm tests/test_guest.py`

- [ ] **Step 3: Extend `User`**

In `rental/models.py`, above `class User`:

```python
ROLES = ["admin", "customer"]
```

Add to `User`, and make `email` required:

```python
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set by the forgot-password page. An admin services it by issuing a
    # temporary password; there is no email sending in this project.
    reset_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def display_name(self) -> str:
        """The name to greet this person by, falling back to their username."""
        return self.full_name or self.username
```

- [ ] **Step 4: Replace the role machinery in `auth.py`**

Add `g` to the `from flask import ...` line, then replace `current_role`, `viewer_required` and `editor_required` with:

```python
def current_user() -> User | None:
    """Return the signed-in User, or None. Loaded once per request and cached on g.

    The role is read off the row rather than stored in the cookie, so an admin
    who is demoted loses access on their next request rather than at their next
    login.
    """
    if "current_user" not in g:
        user_id = session.get("user_id")
        g.current_user = get_session().get(User, user_id) if user_id else None
    return g.current_user


def current_role() -> str | None:
    """Return "admin", "customer", or None when nobody is signed in."""
    user = current_user()
    return user.role if user else None


def _require(view, predicate):
    """Shared body for the three decorators: redirect anonymous, 403 the wrong role."""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if not predicate(user):
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def login_required(view):
    """Any signed-in account. Anonymous visitors go to the login page."""
    return _require(view, lambda user: True)


def admin_required(view):
    """Admins only. A customer gets a 403."""
    return _require(view, lambda user: user.role == "admin")


def customer_required(view):
    """Customers only. An admin gets a 403, because these pages show 'your' rows."""
    return _require(view, lambda user: user.role == "customer")
```

- [ ] **Step 5: Delete guest mode and route login by role**

Remove the whole `guest()` view and its `@bp.route("/guest", ...)` decorator.

Rewrite `logout()`:

```python
@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Clear the session and send the visitor back to the login page."""
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
```

Add the role-aware home and rewrite `safe_next_page`:

```python
def home_for(user: User) -> str:
    """Where a freshly signed-in person belongs after signing in.

    Both roles land on the same page for now. Task 11 splits this into the
    admin console and the customer portal, once those blueprints exist. It is
    deliberately a function so that change is one line in one place.
    """
    return url_for("vehicles.dashboard")


def safe_next_page(target: str | None, user: User) -> str:
    """Return a safe redirect target, ignoring anything pointing off this site.

    Only paths beginning with a single ``/`` are accepted, which blocks
    ``//evil.com`` and full URLs from being used as an open redirect.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return home_for(user)
```

In `login()`, refuse disabled accounts and use the new helpers:

```python
    if session.get("user_id"):
        user = current_user()
        if user is not None:
            return redirect(home_for(user))

    form = LoginForm()
    if form.validate_on_submit():
        user = find_user_by_username(form.username.data.strip())
        if user is not None and user.check_password(form.password.data):
            if not user.is_active:
                flash("That account has been disabled. Please contact the office.", "error")
                return render_template("login.html", form=form)
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            flash("Signed in successfully.", "success")
            return redirect(safe_next_page(request.args.get("next"), user))
        flash("Invalid username or password.", "error")
```

In `signup()`, create a customer: `user = User(username=username, email=email, role="customer")`, then `user.full_name = form.full_name.data` and `user.phone = form.phone.data`, and finish with `return redirect(home_for(user))`.

**Do not write `url_for("portal.dashboard")` here.** That endpoint does not exist
until Task 11, and `url_for` on an unregistered endpoint raises `BuildError` —
so every sign-up and every sign-in would answer 500, including inside the test
fixtures that log in. Route through `home_for()`, which Task 11 updates once.

`SignupForm` in `rental/forms.py` gains the two optional fields:

```python
    full_name = StringField(
        "Full name", filters=[clean_text], validators=[Optional(), Length(max=120)]
    )
    phone = StringField(
        "Phone", filters=[clean_text], validators=[Optional(), Length(max=30)]
    )
```

- [ ] **Step 6: Re-guard every existing route and update the context processor**

In `rental/vehicles.py` and `rental/reports.py`, replace `@viewer_required` and `@editor_required` with `@admin_required` on every route, and fix the imports. These routes move in Task 11; admin-only is the right guard in the meantime.

In `rental/__init__.py`, rewrite `inject_globals`:

```python
    @app.context_processor
    def inject_globals():
        user = auth.current_user()
        role = user.role if user else None
        return {
            "VEHICLE_STATUSES": VEHICLE_STATUSES,
            "VEHICLE_TYPES": VEHICLE_TYPES,
            "TRANSMISSIONS": TRANSMISSIONS,
            "FUEL_TYPES": FUEL_TYPES,
            "STATUS_BADGES": STATUS_BADGES,
            "current_user": user,
            "current_username": user.username if user else None,
            "current_role": role,
            "is_admin": role == "admin",
            "is_customer": role == "customer",
            "max_year": max_year(),
        }
```

Fix the module's import line to match. The CSRF error handler's `url_for("vehicles.dashboard")` becomes `url_for("public.landing")` — a target that exists for everyone, including a visitor whose session has just expired. That endpoint arrives in Task 11; until then point it at `url_for("auth.login")` and change it in Task 11 Step 5.

- [ ] **Step 7: Strip guest mode out of the templates**

- `base.html`: delete the `is_guest` sidebar footer branch, the mobile "Sign in" link and the amber read-only banner. `show_chrome` becomes `{% set show_chrome = current_user and request.endpoint not in ['auth.login', 'auth.signup'] %}`.
- `partials/_nav_links.html`: the `editor_only` flag becomes `admin_only`, tested with `is_admin`.
- `partials/_vehicle_table.html`: `is_editor` becomes `is_admin`.
- `login.html`: delete the "Continue as guest" form and its divider.
- `403.html`: rewrite the copy — it no longer mentions guests. Say the page belongs to a different kind of account, and offer Home and Log in.

Run `grep -rn 'is_guest\|is_editor\|guest' rental/templates` afterwards; expected: no output.

- [ ] **Step 8: Update the auth tests**

In `tests/test_auth.py`, replace `auth_client` with `admin_client` throughout, give every signup payload an `email`, and add:

```python
def test_signup_creates_a_customer(app, client):
    client.post(
        "/signup",
        data={
            "username": "newbie",
            "email": "newbie@example.com",
            "full_name": "New Customer",
            "phone": "0917 000 9999",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    with app.app_context():
        from rental.auth import find_user_by_username

        user = find_user_by_username("newbie")
        assert user.role == "customer"
        assert user.full_name == "New Customer"


def test_a_disabled_account_cannot_sign_in(app, client):
    with app.app_context():
        from rental.auth import find_user_by_username
        from rental.db import get_session

        db = get_session()
        find_user_by_username("maria").is_active = False
        db.commit()

    response = client.post(
        "/login", data={"username": "maria", "password": "secret123"}, follow_redirects=True
    )
    assert b"has been disabled" in response.data
```

- [ ] **Step 9: Run the suite**

Run: `uv run pytest -q`
Expected: all tests pass, none skipped.

- [ ] **Step 10: Rebuild the stylesheet and commit**

```bash
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: replace guest mode with admin and customer roles"
```

---

### Task 7: Password reset request, change password, and the forced-change hook

No email is sent. A customer records a request; an admin services it in phase 4 by issuing a temporary password, which forces a change at next login.

**Files:**
- Modify: `rental/auth.py`, `rental/forms.py`, `rental/__init__.py`
- Create: `rental/templates/forgot_password.html`, `rental/templates/change_password.html`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: Task 6's `User.reset_requested_at`, `.must_change_password`, `login_required`, `home_for`
- Produces: routes `auth.forgot_password` (`/forgot-password`) and `auth.change_password` (`/change-password`); forms `ForgotPasswordForm`, `ChangePasswordForm`; the `before_request` hook `force_password_change`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_auth.py`:

```python
def test_forgot_password_records_the_request(app, client):
    response = client.post(
        "/forgot-password", data={"email": "maria@example.com"}, follow_redirects=True
    )
    assert b"asked the office" in response.data

    with app.app_context():
        from rental.auth import find_user_by_email

        assert find_user_by_email("maria@example.com").reset_requested_at is not None


def test_forgot_password_says_the_same_thing_for_an_unknown_address(client):
    response = client.post(
        "/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True
    )
    assert b"asked the office" in response.data


def test_a_temporary_password_forces_a_change_before_anything_else(app, customer_client):
    with app.app_context():
        from rental.auth import find_user_by_username
        from rental.db import get_session

        db = get_session()
        find_user_by_username("maria").must_change_password = True
        db.commit()

    response = customer_client.get("/my")
    assert response.status_code == 302
    assert "/change-password" in response.headers["Location"]


def test_changing_the_password_clears_the_flag_and_lets_you_back_in(app, customer_client):
    with app.app_context():
        from rental.auth import find_user_by_username
        from rental.db import get_session

        db = get_session()
        find_user_by_username("maria").must_change_password = True
        db.commit()

    customer_client.post(
        "/change-password",
        data={
            "current_password": "secret123",
            "password": "brandnew123",
            "confirm_password": "brandnew123",
        },
    )

    with app.app_context():
        from rental.auth import find_user_by_username

        user = find_user_by_username("maria")
        assert user.must_change_password is False
        assert user.check_password("brandnew123")

    assert customer_client.get("/my").status_code == 200


def test_a_wrong_current_password_is_refused(customer_client):
    response = customer_client.post(
        "/change-password",
        data={
            "current_password": "wrong-password",
            "password": "brandnew123",
            "confirm_password": "brandnew123",
        },
    )
    assert b"current password is not correct" in response.data
```

Two of these request `/my`, which Task 11 creates. Write them against
`/vehicles` instead — an admin-guarded route that exists now — using
`admin_client` in place of `customer_client`, and assert the same two things: a
temporary password redirects to `/change-password`, and clearing it restores
access. The behaviour under test is the `before_request` gate, which is
route-independent, so nothing is lost and nothing is committed disabled.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_auth.py -q`
Expected: FAIL — 404 on `/forgot-password`.

- [ ] **Step 3: Add the two forms**

In `rental/forms.py`:

```python
class ForgotPasswordForm(FlaskForm):
    """Ask the office to reset a password. No email is sent; an admin services it."""

    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[
            DataRequired(message="Email is required."),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    submit = SubmitField("Request a reset")


class ChangePasswordForm(FlaskForm):
    """Change your own password, proving you know the current one."""

    current_password = PasswordField(
        "Current password", validators=[DataRequired(message="Enter your current password.")]
    )
    password = PasswordField(
        "New password",
        validators=[
            DataRequired(message="A new password is required."),
            Length(
                min=MIN_PASSWORD_LENGTH,
                message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(message="Please retype the new password."),
            EqualTo("password", message="The two passwords do not match."),
        ],
    )
    submit = SubmitField("Change password")
```

- [ ] **Step 4: Add the two routes**

In `rental/auth.py`, importing `ChangePasswordForm`, `ForgotPasswordForm` from `.forms` and `utcnow` from `.models`:

```python
@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Record that someone wants their password reset.

    No email is sent and no token is minted: an admin sees the flag on the
    Customers page and issues a temporary password. The confirmation is worded
    identically whether or not the address exists, so the form cannot be used to
    discover which addresses have accounts.
    """
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = find_user_by_email(form.email.data)
        if user is not None:
            user.reset_requested_at = utcnow()
            get_session().commit()
        flash(
            "If that address has an account, you have asked the office to reset it. "
            "Staff will issue you a temporary password.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", form=form)


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change your own password. Forced when an admin has issued a temporary one."""
    user = current_user()
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if not user.check_password(form.current_password.data):
            form.current_password.errors.append("That current password is not correct.")
        else:
            user.set_password(form.password.data)
            user.must_change_password = False
            user.reset_requested_at = None
            get_session().commit()
            flash("Your password has been changed.", "success")
            return redirect(home_for(user))

    return render_template("change_password.html", form=form, forced=user.must_change_password)
```

- [ ] **Step 5: Add the forced-change hook**

In `rental/__init__.py`, call `register_password_change_gate(app)` inside `create_app` after the blueprints are registered, and define:

```python
def register_password_change_gate(app: Flask) -> None:
    """Hold anyone carrying a temporary password on the change-password page."""

    @app.before_request
    def force_password_change():
        user = auth.current_user()
        if user is None or not user.must_change_password:
            return None
        # Without the `static` exemption the change-password page would render
        # with no stylesheet, because the request for output.css would itself
        # be redirected.
        if request.endpoint in ("auth.change_password", "auth.logout", "static"):
            return None
        return redirect(url_for("auth.change_password"))
```

Add `request` to the `from flask import ...` line.

- [ ] **Step 6: Write the two templates**

`rental/templates/forgot_password.html` and `rental/templates/change_password.html`, both extending `base.html` and reusing the centred-card markup `signup.html` already uses: a `.card` with a `.page-title`, fields rendered with `.field-label` / `.field` / `.field-error`, and a `.btn.btn-primary` submit. Task 9 moves both into `templates/auth/`.

`forgot_password.html` explains the flow honestly, since there is no email: "We don't send reset emails. Tell us your address and the office will issue you a temporary password." Add a link back to `auth.login`.

On `change_password.html`, when `forced` is true, render an `.alert.alert-warning` above the form: "You are using a temporary password. Choose a new one to continue."

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_auth.py -q`
Expected: PASS, none skipped.

- [ ] **Step 8: Run the whole suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add password reset requests and forced password change"
```

---

### Task 8: `flask reset-db`, the new seed, and a required `create-admin --email`

**Files:**
- Modify: `rental/cli.py`
- Test: `tests/test_cli.py` (create)

**Interfaces:**
- Consumes: every model from Tasks 3–6
- Produces: `reset_db_command` (`flask reset-db`), `seed_everything(db, admin_password, demo_password) -> dict[str, int]`, and a rewritten `SAMPLE_VEHICLES` / new `SAMPLE_CUSTOMERS`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
"""The database CLI: reset-db, seed and create-admin."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from rental.db import get_session
from rental.models import Maintenance, RentalRates, User, Vehicle

ARGS = ("--yes", "--password", "adminpass1", "--demo-password", "demopass1")


def run(app, *args):
    return app.test_cli_runner().invoke(args=list(args))


def test_reset_db_seeds_a_usable_demo_database(app):
    result = run(app, "reset-db", *ARGS)
    assert result.exit_code == 0

    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Vehicle)) == 10
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 1
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "customer")) == 3
        assert db.scalar(select(func.count()).select_from(Maintenance)) == 1
        assert RentalRates.current(db).insurance_fee_per_day == Decimal("300.00")


def test_the_seeded_maintenance_vehicle_is_marked_under_maintenance(app):
    run(app, "reset-db", *ARGS)

    with app.app_context():
        db = get_session()
        record = db.scalars(select(Maintenance)).first()
        assert db.get(Vehicle, record.vehicle_id).status == "MAINTENANCE"


def test_the_requirements_demo_vehicles_are_present_with_their_rates(app):
    run(app, "reset-db", *ARGS)

    with app.app_context():
        db = get_session()
        vios = db.scalars(select(Vehicle).where(Vehicle.model == "Vios")).one()
        assert vios.daily_rate == Decimal("1500.00")
        assert vios.vehicle_type == "Sedan"

        hiace = db.scalars(select(Vehicle).where(Vehicle.model == "HiAce")).one()
        assert hiace.seats == 12
        assert hiace.transmission == "Manual"
        assert hiace.daily_rate == Decimal("3500.00")


def test_the_seeded_admin_can_sign_in(app):
    run(app, "reset-db", *ARGS)

    response = app.test_client().post(
        "/login", data={"username": "admin", "password": "adminpass1"}
    )
    assert response.status_code == 302


def test_seeding_twice_adds_nothing_the_second_time(app):
    run(app, "reset-db", *ARGS)
    result = run(app, "seed", "--password", "adminpass1", "--demo-password", "demopass1")

    with app.app_context():
        assert get_session().scalar(select(func.count()).select_from(Vehicle)) == 10
    assert result.exit_code == 0


def test_reset_db_refuses_a_non_sqlite_database_without_yes(app):
    app.config["DATABASE_URL"] = "postgresql+psycopg://user:pw@example.com/db"
    result = run(app, "reset-db", "--password", "adminpass1", "--demo-password", "demopass1")
    assert result.exit_code != 0
    assert "refusing" in result.output.lower()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — `Error: No such command 'reset-db'.`

- [ ] **Step 3: Rewrite the sample data**

In `rental/cli.py`, replace `SAMPLE_VEHICLES` and add `SAMPLE_CUSTOMERS`. Tuple order: plate, brand, model, year, type, seats, transmission, fuel, daily rate, hourly rate, colour, status, description.

```python
# Ten vehicles for demos and screenshots. The first four are the ones the
# requirements name by rate; the rest fill out the body styles so the storefront
# filters have something to bite on.
SAMPLE_VEHICLES = [
    ("ABC 1234", "Toyota", "Vios", 2024, "Sedan", 5, "Automatic", "Gasoline", "1500.00", "250.00", "Silver", "AVAILABLE", "Economical city sedan, easy to park."),
    ("XYZ 5678", "Mitsubishi", "Mirage", 2023, "Hatchback", 5, "Automatic", "Gasoline", "1300.00", "220.00", "Red", "AVAILABLE", "Our most fuel-efficient hatchback."),
    ("JKL 2468", "Toyota", "Innova", 2023, "MPV", 7, "Automatic", "Diesel", "2500.00", "400.00", "Black", "AVAILABLE", "Seven seats, ideal for family trips."),
    ("MNO 1357", "Toyota", "HiAce", 2022, "Van", 12, "Manual", "Diesel", "3500.00", None, "White", "AVAILABLE", "Twelve-seater van for group travel."),
    ("PQR 8642", "Honda", "Civic", 2024, "Sedan", 5, "Automatic", "Gasoline", "2000.00", "320.00", "Blue", "AVAILABLE", "Comfortable executive sedan."),
    ("STU 9753", "Mitsubishi", "Montero Sport", 2023, "SUV", 7, "Automatic", "Diesel", "3000.00", "480.00", "Pearl White", "AVAILABLE", "Full-size SUV with plenty of luggage room."),
    ("VWX 3141", "Ford", "Ranger", 2023, "Pickup", 5, "Automatic", "Diesel", "2800.00", None, "Grey", "AVAILABLE", "Four-wheel-drive pickup for rough roads."),
    ("YZA 5926", "Suzuki", "Ertiga", 2022, "MPV", 7, "Manual", "Gasoline", "1800.00", "300.00", "Maroon", "AVAILABLE", "Compact seven-seater."),
    ("BCD 5358", "Nissan", "Urvan", 2021, "Van", 15, "Manual", "Diesel", "3800.00", None, "White", "AVAILABLE", "Fifteen-seater, driver available on request."),
    ("EFG 9793", "Hyundai", "Accent", 2022, "Sedan", 5, "Manual", "Diesel", "1400.00", "230.00", "White", "MAINTENANCE", "Currently in the workshop."),
]

SAMPLE_CUSTOMERS = [
    ("maria", "maria.santos@example.com", "Maria Santos", "0917 555 0101"),
    ("juan", "juan.delacruz@example.com", "Juan dela Cruz", "0917 555 0102"),
    ("ana", "ana.reyes@example.com", "Ana Reyes", "0917 555 0103"),
]
```

Update the imports at the top of `cli.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from flask import current_app

from .models import Base, Maintenance, RentalRates, User, Vehicle
```

- [ ] **Step 4: Write the seed routine and the two commands**

Replace `seed_command` with:

```python
def seed_everything(db, admin_password: str, demo_password: str) -> dict[str, int]:
    """Insert the demo fleet, the accounts and the fee schedule. Idempotent.

    Anything already present by its unique key is skipped, so running this over
    a partly-populated database tops it up rather than failing.
    """
    counts = {"vehicles": 0, "customers": 0, "admins": 0, "maintenance": 0}

    RentalRates.current(db)

    if db.scalars(select(User).where(User.username == "admin")).first() is None:
        admin = User(
            username="admin",
            email="admin@example.com",
            role="admin",
            full_name="Fleet Administrator",
        )
        admin.set_password(admin_password)
        db.add(admin)
        counts["admins"] += 1

    for username, email, full_name, phone in SAMPLE_CUSTOMERS:
        if db.scalars(select(User).where(User.username == username)).first() is not None:
            continue
        customer = User(
            username=username, email=email, role="customer", full_name=full_name, phone=phone
        )
        customer.set_password(demo_password)
        db.add(customer)
        counts["customers"] += 1

    for row in SAMPLE_VEHICLES:
        (plate, brand, model, year, vtype, seats, transmission, fuel,
         daily, hourly, color, status, description) = row
        if db.scalars(select(Vehicle).where(Vehicle.plate_number == plate)).first():
            continue
        db.add(
            Vehicle(
                plate_number=plate,
                brand=brand,
                model=model,
                year=year,
                vehicle_type=vtype,
                seats=seats,
                transmission=transmission,
                fuel_type=fuel,
                daily_rate=Decimal(daily),
                hourly_rate=Decimal(hourly) if hourly else None,
                color=color,
                status=status,
                description=description,
            )
        )
        counts["vehicles"] += 1

    db.commit()

    # The one vehicle seeded as MAINTENANCE gets the record that explains it, so
    # the seeded state agrees with the bookability rule rather than contradicting it.
    workshop = db.scalars(select(Vehicle).where(Vehicle.status == "MAINTENANCE")).first()
    if workshop is not None and db.scalars(select(Maintenance)).first() is None:
        today = date.today()
        db.add(
            Maintenance(
                vehicle_id=workshop.id,
                description="Scheduled brake replacement and aircon service.",
                start_date=today - timedelta(days=2),
                expected_end_date=today + timedelta(days=5),
                status="IN_PROGRESS",
                cost=Decimal("8500.00"),
            )
        )
        counts["maintenance"] += 1
        db.commit()

    return counts


@click.command("seed")
@click.option("--password", prompt=True, hide_input=True, help="Password for the admin account.")
@click.option(
    "--demo-password",
    prompt=True,
    hide_input=True,
    help="Shared password for the three sample customers.",
)
@with_appcontext
def seed_command(password: str, demo_password: str):
    """Insert the demo fleet, accounts and fee schedule, skipping what exists."""
    counts = seed_everything(get_session(), password, demo_password)
    click.echo(
        f"Added {counts['vehicles']} vehicle(s), {counts['customers']} customer(s), "
        f"{counts['admins']} admin(s), {counts['maintenance']} maintenance record(s)."
    )


@click.command("reset-db")
@click.option("--yes", is_flag=True, help="Required to reset anything other than local SQLite.")
@click.option("--password", prompt=True, hide_input=True, help="Password for the admin account.")
@click.option(
    "--demo-password",
    prompt=True,
    hide_input=True,
    help="Shared password for the three sample customers.",
)
@with_appcontext
def reset_db_command(yes: bool, password: str, demo_password: str):
    """Drop every table, recreate them, and seed the demo data.

    This destroys data, so it refuses to touch anything but a local SQLite file
    unless --yes is passed explicitly.
    """
    url = current_app.config["DATABASE_URL"]
    if not url.startswith("sqlite") and not yes:
        raise click.ClickException(
            f"Refusing to drop every table on {url.split('@')[-1]} without --yes."
        )

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    click.echo("Tables dropped and recreated.")

    counts = seed_everything(get_session(), password, demo_password)
    click.echo(
        f"Seeded {counts['vehicles']} vehicle(s), {counts['customers']} customer(s), "
        f"{counts['maintenance']} maintenance record(s)."
    )
    click.echo("")
    click.echo("Sign in as:")
    click.echo("  admin    / the --password you just set   (Rental Management Dashboard)")
    for username, _email, full_name, _phone in SAMPLE_CUSTOMERS:
        click.echo(f"  {username:<8} / the --demo-password you just set   ({full_name})")
```

Register it in `register_cli`: `app.cli.add_command(reset_db_command)`.

Make `create_admin_command`'s email required — `@click.option("--email", prompt=True, help="Email address for the new account.")` — and give the user a role: `User(username=username, email=email, role="admin")`.

- [ ] **Step 5: Run the CLI tests**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 6: Run the whole suite and commit**

```bash
uv run pytest -q
git add -A
git commit -m "feat: add flask reset-db and a rental demo seed"
```

---

### Task 9: The stylesheet, the two layouts and the template reorganisation

Splits the one `base.html` into a shared shell plus a public layout and an admin layout, and moves the templates into folders matching the blueprints.

**Files:**
- Modify: `rental/static/src/input.css`, `rental/templates/base.html`, `rental/templates/partials/_icons.html`
- Create: `rental/templates/layout_public.html`, `layout_admin.html`, `partials/_public_nav.html`, `partials/_admin_nav.html`
- Move: templates into `auth/`, `admin/`
- Modify: every `render_template` call to match the new paths

**Interfaces:**
- Consumes: Task 6's `current_user` / `is_admin` / `is_customer` context variables
- Produces: `layout_public.html` and `layout_admin.html`, both extending `base.html` and both defining `main` and `content` blocks; the `.top-link`, `.vehicle-card`, `.vehicle-card-media`, `.spec-chip`, `.rate`, `.stat-card`, `.stat-label`, `.stat-value` component classes; the `money`, `calendar` and `users` icons

- [ ] **Step 1: Move the templates**

```bash
cd rental/templates
mkdir -p auth public customer admin
git mv login.html signup.html forgot_password.html change_password.html auth/
git mv vehicles_list.html vehicle_form.html vehicle_detail.html vehicle_delete.html search.html admin/
git mv dashboard.html admin/dashboard.html
git mv reports.html admin/reports.html
cd -
```

Update every `render_template("...")` call in `rental/auth.py`, `rental/vehicles.py` and `rental/reports.py` to the new paths (`"auth/login.html"`, `"admin/vehicles_list.html"`, and so on).

- [ ] **Step 2: Reduce `base.html` to the shared shell**

```html
{% from 'partials/_icons.html' import icon %}
{% from 'partials/_flashes.html' import flashes with context %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Vehicle Rental and Reservation System{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/output.css') }}">
</head>
<body>
{% block body %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Write `layout_public.html`**

```html
{% extends 'base.html' %}
{% from 'partials/_icons.html' import icon %}
{% from 'partials/_flashes.html' import flashes with context %}

{% block body %}
<header class="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
  <div class="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
    <a href="{{ url_for('public.landing') }}" class="flex items-center gap-2.5">
      <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-500 text-white">
        {{ icon('car', 'h-5 w-5') }}
      </span>
      <span class="leading-tight">
        <span class="block text-[15px] font-extrabold tracking-tight text-ink">Vehicle Rental</span>
        <span class="block text-[11px] font-medium text-muted">and Reservation System</span>
      </span>
    </a>
    <details class="relative sm:hidden">
      <summary class="list-none cursor-pointer p-2 text-muted">{{ icon('menu', 'h-6 w-6') }}</summary>
      <nav class="absolute right-0 z-40 mt-2 flex w-56 flex-col gap-1 rounded-xl border border-line bg-white p-2 shadow-lg">
        {% include 'partials/_public_nav.html' %}
      </nav>
    </details>
    <nav class="hidden items-center gap-1.5 sm:flex">
      {% include 'partials/_public_nav.html' %}
    </nav>
  </div>
</header>

<main class="min-h-screen">
  {% block main %}
    <div class="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">
      {{ flashes() }}
      {% block content %}{% endblock %}
    </div>
  {% endblock %}
</main>
{% endblock %}
```

`partials/_public_nav.html`:

```html
<a class="top-link" href="{{ url_for('public.landing') }}">Home</a>
<a class="top-link" href="{{ url_for('public.browse') }}">Browse Vehicles</a>
{% if is_customer %}
  <a class="top-link" href="{{ url_for('portal.dashboard') }}">My Dashboard</a>
  <form method="post" action="{{ url_for('auth.logout') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="top-link w-full text-left">Log out</button>
  </form>
{% elif is_admin %}
  <a class="top-link" href="{{ url_for('admin_dashboard.dashboard') }}">Admin Console</a>
  <form method="post" action="{{ url_for('auth.logout') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="top-link w-full text-left">Log out</button>
  </form>
{% else %}
  <a class="top-link" href="{{ url_for('auth.login') }}">Log in</a>
  <a class="btn btn-primary btn-sm" href="{{ url_for('auth.signup') }}">Create account</a>
{% endif %}
```

My Reservations, My Rentals and Profile are deliberately absent: those pages arrive in phase 3, and a link to a page that does not exist is exactly the dead control requirement 33 forbids.

- [ ] **Step 4: Write `layout_admin.html`**

Take the sidebar and the mobile `<details>` drop-down out of the old `base.html` verbatim into a `{% block body %}`, change the brand text to "Vehicle Rental" / "Rental Management", drop every `is_guest` branch, and include `partials/_admin_nav.html` in place of `_nav_links.html`. Keep `lg:ml-64` on `main`, and keep the `main` / `content` block structure so the admin templates carry on working unchanged.

`partials/_admin_nav.html`:

```html
{# The grouped admin navigation. Sections whose pages belong to a later phase
   are not rendered at all: a link to a page that does not exist is a dead
   control, which requirement 33 rules out. #}
{% from 'partials/_icons.html' import icon %}

{% macro section(label) %}
  <p class="px-3 pt-5 pb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">{{ label }}</p>
{% endmacro %}

{% macro link(endpoint, label, name) %}
  <a href="{{ url_for(endpoint) }}"
     class="nav-link {% if request.endpoint == endpoint %}nav-link-active{% endif %}"
     {% if request.endpoint == endpoint %}aria-current="page"{% endif %}>
    {{ icon(name) }}<span>{{ label }}</span>
  </a>
{% endmacro %}

{{ link('vehicles.dashboard', 'Dashboard', 'dashboard') }}

{{ section('Fleet Management') }}
{{ link('vehicles.list_vehicles', 'Vehicles', 'car') }}
{{ link('vehicles.add_vehicle', 'Add Vehicle', 'plus') }}
{{ link('vehicles.search', 'Search Fleet', 'search') }}

{{ section('Reports') }}
{{ link('reports.reports', 'Fleet Reports', 'report') }}
```

**These are deliberately the CURRENT endpoint names.** `admin_dashboard`,
`admin_fleet` and `admin_rates` are not registered until Task 11, and `url_for`
on an unregistered endpoint raises `BuildError`. Because every admin template
extends `layout_admin.html`, which includes this partial, using the Task 11
names here would break every admin page the moment this task landed. Task 11
renames them in the same task that registers those blueprints, and adds the
Financial / Rental Rates section then.

Delete `partials/_nav_links.html` once nothing includes it.

- [ ] **Step 5: Add the new icons**

In `partials/_icons.html`, add three branches before the closing `{%- endif -%}`:

```html
  {%- elif name == 'money' -%}
    <rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/>
    <path d="M6 12h.01M18 12h.01"/>
  {%- elif name == 'calendar' -%}
    <rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>
  {%- elif name == 'users' -%}
    <circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>
    <path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M17.5 20a6.5 6.5 0 0 0-2-4.7"/>
```

- [ ] **Step 6: Add the new component classes**

In `rental/static/src/input.css`, inside `@layer components`:

```css
  /* ---- Storefront ---------------------------------------------------- */
  .top-link {
    @apply rounded-lg px-3 py-2 text-sm font-semibold text-muted
           transition-colors hover:bg-slate-100 hover:text-ink;
  }

  .vehicle-card {
    @apply flex flex-col overflow-hidden rounded-xl border border-line bg-white transition;
    box-shadow: 0 1px 2px rgb(15 23 42 / 0.04), 0 10px 28px -18px rgb(15 23 42 / 0.25);
  }
  .vehicle-card:hover { @apply -translate-y-0.5 border-brand-500/40; }

  .vehicle-card-media {
    @apply flex aspect-[16/10] w-full items-center justify-center bg-slate-100;
  }

  .spec-chip {
    @apply inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-1
           text-xs font-medium text-slate-600;
  }

  .rate { @apply font-mono text-xl font-bold tracking-tight text-ink; }

  .stat-card  { @apply card p-5; }
  .stat-label { @apply text-xs font-semibold uppercase tracking-wider text-muted; }
  .stat-value { @apply mt-1.5 text-3xl font-bold tracking-tight text-ink; }
```

- [ ] **Step 7: Point every template at a layout**

Every template under `admin/` changes its first line to `{% extends 'layout_admin.html' %}`. `auth/login.html` and `auth/signup.html` keep their own full-bleed `body` block and extend `base.html` directly; `auth/forgot_password.html` and `auth/change_password.html` extend `layout_public.html`. `403.html`, `404.html` and `500.html` extend `layout_public.html`, because an error can reach an anonymous visitor.

`layout_public.html` references `public.landing`, `public.browse` and
`portal.dashboard`, which do not exist until Task 11. So **Task 9's suite will
fail with `BuildError` on any page using the public layout.** To keep this task
verifiable on its own, leave `403/404/500.html` and the two auth pages extending
`base.html`; Task 11 Step 6 switches them over.

**This is intentional and is not dead code.** `layout_public.html` and
`partials/_public_nav.html` are created in this task because Task 11 registers
five blueprints whose templates all extend them, and writing the layouts in the
same task as the routes would make that task far too large to review. They are
unreferenced for two tasks by design. Note this in the commit message so the
reason survives in the history.

- [ ] **Step 8: Run the suite**

Run: `uv run pytest -q`
Expected: all tests pass except the skipped ones. If a template raises `TemplateNotFound`, a `render_template` path was missed in Step 1.

- [ ] **Step 9: Rebuild the stylesheet and commit**

```bash
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: split the layout into a public storefront and an admin console"
```

---

### Task 10: Per-type vehicle silhouettes and the image macro

A vehicle with no photograph must still look deliberate. Eight committed SVGs, one per body style.

**Files:**
- Create: `rental/static/img/types/{sedan,hatchback,mpv,suv,pickup,van,truck,motorcycle}.svg`
- Create: `rental/templates/partials/_vehicle_image.html`

**Interfaces:**
- Consumes: Task 3's `Vehicle.image_url`, `Vehicle.type_slug`, `Vehicle.display_name`
- Produces: the Jinja macro `vehicle_image(vehicle, cls)` importable from `partials/_vehicle_image.html`

- [ ] **Step 1: Draw the eight silhouettes**

Each file is a flat two-tone side view on a transparent background, drawn on a `0 0 160 90` viewBox so they all share proportions. Use `#cbd5e1` for the body and `#94a3b8` for the wheels and glazing, which sit correctly on the `.vehicle-card-media` slate background. `rental/static/img/types/sedan.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90" role="img" aria-label="Sedan">
  <path fill="#cbd5e1" d="M18 58h124a6 6 0 0 0 6-6v-9a9 9 0 0 0-7-8.8l-19-4-14-9.5A14 14 0 0 0 100 18H66a14 14 0 0 0-8.6 3L42 34l-20 4a9 9 0 0 0-7 8.8V52a6 6 0 0 0 6 6Z"/>
  <path fill="#94a3b8" d="M68 23h30a9 9 0 0 1 5.6 2l10 8H68Zm-6 0v10H44l12-8a9 9 0 0 1 6-2Z"/>
  <circle cx="46" cy="58" r="11" fill="#94a3b8"/><circle cx="46" cy="58" r="5" fill="#f1f5f9"/>
  <circle cx="116" cy="58" r="11" fill="#94a3b8"/><circle cx="116" cy="58" r="5" fill="#f1f5f9"/>
</svg>
```

Draw the other seven in the same idiom, varying only the roofline and the wheelbase: `hatchback` (short rear overhang), `mpv` (tall, long roof), `suv` (tall, boxy, raised ride height), `pickup` (cab plus an open bed), `van` (flat front, full-height box), `truck` (cab plus a separate cargo body), `motorcycle` (two wheels, a frame triangle, handlebars). Keep every file under 1 KB.

- [ ] **Step 2: Write the macro**

`rental/templates/partials/_vehicle_image.html`:

```html
{# A vehicle's photograph, or the silhouette for its body style when it has none.
   Kept in one macro so the browse grid, the detail page and the admin table all
   fall back identically. #}

{% macro vehicle_image(vehicle, cls='h-full w-full object-cover') %}
  {% if vehicle.image_url %}
    <img src="{{ vehicle.image_url }}" alt="{{ vehicle.display_name }}" class="{{ cls }}" loading="lazy">
  {% else %}
    <img src="{{ url_for('static', filename='img/types/' ~ vehicle.type_slug ~ '.svg') }}"
         alt="{{ vehicle.vehicle_type }} illustration" class="h-3/5 w-3/5 object-contain opacity-80">
  {% endif %}
{% endmacro %}
```

- [ ] **Step 3: Check every type has a file**

Run:

```bash
uv run python -c "
from rental.models import VEHICLE_TYPES
import pathlib
missing = [t for t in VEHICLE_TYPES
           if not pathlib.Path(f'rental/static/img/types/{t.lower()}.svg').exists()]
print('MISSING:', missing)
"
```

Expected: `MISSING: []`

- [ ] **Step 4: Check each file is valid XML**

Run: `uv run python -c "
import glob, xml.etree.ElementTree as ET
for f in sorted(glob.glob('rental/static/img/types/*.svg')):
    ET.parse(f); print('ok', f)
"`
Expected: eight `ok` lines, no traceback.

- [ ] **Step 5: Run the suite and commit**

```bash
uv run pytest -q
git add -A
git commit -m "feat: add per-type vehicle silhouettes and the image macro"
```

---

### Task 11: Blueprint restructure — `public`, `portal`, `admin_fleet`, `admin_dashboard`, `admin_rates`

Moves the routes to their final URLs and registers the blueprints the navigation already points at. This is the task that turns `tests/test_roles.py` green.

**Files:**
- Create: `rental/public.py`, `rental/portal.py`, `rental/admin/__init__.py`, `rental/admin/fleet.py`, `rental/admin/dashboard.py`, `rental/admin/rates.py`
- Delete: `rental/vehicles.py`
- Modify: `rental/__init__.py`, `rental/reports.py`, `rental/forms.py`
- Create: `rental/templates/public/landing.html`, `public/browse.html`, `public/vehicle_detail.html`, `customer/dashboard.html`, `admin/rates.html`
- Rename: `tests/test_vehicles.py` → `tests/test_fleet.py`
- Test: `tests/test_roles.py`

**Interfaces:**
- Consumes: Tasks 6–10
- Produces these endpoints, which the navigation partials from Task 9 already call:
  - `public.landing` → `GET /`
  - `public.browse` → `GET /vehicles`
  - `public.vehicle_detail` → `GET /vehicles/<int:vehicle_id>`
  - `portal.dashboard` → `GET /my`
  - `admin_dashboard.dashboard` → `GET /admin`
  - `admin_fleet.list_vehicles` / `add_vehicle` / `view_vehicle` / `edit_vehicle` / `delete_vehicle` / `toggle_active` / `search` under `/admin/vehicles`
  - `admin_rates.rates` → `GET POST /admin/rates`
- Also produces, in `rental/admin/fleet.py`: `PER_PAGE = 10`, `GRID_PER_PAGE = 12`, `paginate(query, page, per_page=PER_PAGE)`, `get_vehicle_or_404(vehicle_id)`
- And in `rental/forms.py`: `RentalRatesForm`

- [ ] **Step 1: Split `vehicles.py` into `admin/fleet.py`**

`rental/admin/__init__.py` is an empty module with a docstring.

`rental/admin/fleet.py` takes `list_vehicles`, `view_vehicle`, `add_vehicle`, `edit_vehicle`, `delete_vehicle` and `search`, plus `get_vehicle_or_404`, `plate_already_used`, `copy_form_into_vehicle`, `apply_sorting` and `paginate`, verbatim apart from:

- `bp = Blueprint("admin_fleet", __name__, url_prefix="/admin/vehicles")`
- every route decorator becomes `@admin_required`, and its rule loses the `/vehicles` prefix: `@bp.route("")`, `@bp.route("/add", methods=["GET", "POST"])`, `@bp.route("/<int:vehicle_id>")`, `@bp.route("/<int:vehicle_id>/edit", methods=["GET", "POST"])`, `@bp.route("/<int:vehicle_id>/delete", methods=["GET", "POST"])`, `@bp.route("/search")`
- every `url_for("vehicles.list_vehicles")` becomes `url_for("admin_fleet.list_vehicles")`
- `SORTABLE_COLUMNS` gains `"rate": Vehicle.daily_rate`
- imports become relative one level further up: `from ..auth import admin_required`, `from ..db import get_session`, and so on
- `search()`'s status check becomes `if status in VEHICLE_STATUSES`

`paginate` gains a per-page argument, because the storefront grid uses 12 and the admin table 10:

```python
PER_PAGE = 10
GRID_PER_PAGE = 12


def paginate(query, page: int, per_page: int = PER_PAGE):
    """Run the query for one page of results and return (rows, page, total_pages, total).

    Counting and slicing are done in SQL rather than in Python, so a large table
    never has to be loaded into memory -- important on a serverless host.
    """
    db = get_session()
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)
    rows = db.scalars(query.limit(per_page).offset((page - 1) * per_page)).all()
    return rows, page, total_pages, total
```

Add the new route:

```python
@bp.route("/<int:vehicle_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(vehicle_id: int):
    """Disable a vehicle, or bring a disabled one back.

    A disabled vehicle keeps its history but leaves the storefront and cannot be
    booked at all, which is what requirement 16's "Disable Vehicle" means. POST
    only, so it cannot be triggered by following a link.
    """
    vehicle = get_vehicle_or_404(vehicle_id)
    vehicle.is_active = not vehicle.is_active
    get_session().commit()
    flash(
        f"Vehicle {vehicle.plate_number} was "
        f"{'re-enabled' if vehicle.is_active else 'disabled'}.",
        "success",
    )
    return redirect(url_for("admin_fleet.view_vehicle", vehicle_id=vehicle.id))
```

Then `git rm rental/vehicles.py`.

- [ ] **Step 2: Write `admin/dashboard.py`**

```python
"""The Rental Management Dashboard: what the fleet is doing right now."""

from __future__ import annotations

from datetime import date, datetime, time

from flask import Blueprint, render_template
from sqlalchemy import func, select

from ..auth import admin_required
from ..db import get_session
from ..models import VEHICLE_STATUSES, Rental, Reservation, Vehicle

bp = Blueprint("admin_dashboard", __name__, url_prefix="/admin")


# An empty rule registers exactly "/admin". @bp.route("/") would register
# "/admin/", and a request for "/admin" would then answer 308 rather than 200.
@bp.route("")
@admin_required
def dashboard():
    """Fleet counts by status, plus today's operational numbers and revenue.

    Every figure is a real query. Reservation and rental counts are legitimately
    zero until phase 3 gives the system a way to create one; these are the final
    queries and start reporting the moment it does.
    """
    db = get_session()

    total = db.scalar(select(func.count()).select_from(Vehicle)) or 0
    grouped = db.execute(
        select(Vehicle.status, func.count(Vehicle.id)).group_by(Vehicle.status)
    ).all()
    counts = {status: 0 for status in VEHICLE_STATUSES}
    for status, count in grouped:
        counts[status] = count

    today_start = datetime.combine(date.today(), time.min)
    today_end = datetime.combine(date.today(), time.max)

    pending = db.scalar(
        select(func.count()).select_from(Reservation).where(Reservation.status == "PENDING")
    ) or 0
    pickups_today = db.scalar(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.status == "CONFIRMED")
        .where(Reservation.pickup_at.between(today_start, today_end))
    ) or 0
    returns_today = db.scalar(
        select(func.count())
        .select_from(Rental)
        .where(Rental.status == "ACTIVE")
        .where(Rental.expected_return.between(today_start, today_end))
    ) or 0
    revenue = db.scalar(
        select(func.coalesce(func.sum(Rental.total_amount), 0)).where(Rental.status == "COMPLETED")
    ) or 0

    return render_template(
        "admin/dashboard.html",
        total=total,
        counts=counts,
        pending=pending,
        pickups_today=pickups_today,
        returns_today=returns_today,
        revenue=revenue,
    )
```

- [ ] **Step 3: Write `admin/rates.py` and `RentalRatesForm`**

```python
"""The fee schedule every rental calculation reads."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from ..auth import admin_required
from ..db import get_session
from ..forms import RentalRatesForm
from ..models import RentalRates

bp = Blueprint("admin_rates", __name__, url_prefix="/admin/rates")


@bp.route("", methods=["GET", "POST"])
@admin_required
def rates():
    """Show and save the one fee schedule row.

    These live in the database rather than in the templates so an admin can
    change them without a deploy (requirement 21).
    """
    db = get_session()
    current = RentalRates.current(db)
    form = RentalRatesForm(obj=current)

    if form.validate_on_submit():
        current.additional_driver_fee_per_day = form.additional_driver_fee_per_day.data
        current.insurance_fee_per_day = form.insurance_fee_per_day.data
        current.late_fee_per_day = form.late_fee_per_day.data
        db.commit()
        flash("Rental rates were updated.", "success")
        return redirect(url_for("admin_rates.rates"))

    return render_template("admin/rates.html", form=form, rates=current)
```

In `rental/forms.py`, adding `InputRequired` to the `wtforms.validators` import:

```python
class RentalRatesForm(FlaskForm):
    """The system-wide fee schedule. Nothing in a template hardcodes these."""

    # InputRequired rather than DataRequired: zero is a legitimate fee, and
    # DataRequired would reject it as missing.
    additional_driver_fee_per_day = DecimalField(
        "Additional driver, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    insurance_fee_per_day = DecimalField(
        "Insurance, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    late_fee_per_day = DecimalField(
        "Late return, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    submit = SubmitField("Save rates")
```

- [ ] **Step 4: Write `public.py` and `portal.py` as working stubs**

Both get their full content in Tasks 12–14 and 17. For now, enough to register and answer 200:

`rental/public.py`:

```python
"""The public storefront: anyone may reach these pages, signed in or not."""

from __future__ import annotations

from flask import Blueprint, abort, render_template

from .db import get_session
from .models import Vehicle

bp = Blueprint("public", __name__)


@bp.route("/")
def landing():
    return render_template("public/landing.html")


@bp.route("/vehicles")
def browse():
    return render_template("public/browse.html", vehicles=[], total=0)


@bp.route("/vehicles/<int:vehicle_id>")
def vehicle_detail(vehicle_id: int):
    vehicle = get_session().get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    return render_template("public/vehicle_detail.html", vehicle=vehicle)
```

`rental/portal.py`:

```python
"""The customer's own area. Every page here is scoped to the signed-in customer."""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import customer_required

bp = Blueprint("portal", __name__, url_prefix="/my")


@bp.route("")
@customer_required
def dashboard():
    return render_template("customer/dashboard.html")
```

Create the five templates — `public/landing.html`, `public/browse.html`, `public/vehicle_detail.html`, `customer/dashboard.html`, `admin/rates.html` — each extending the right layout with a `.page-title`, so every route renders. Tasks 12–14, 17 and 18 fill them in.

- [ ] **Step 5: Register the blueprints**

In `rental/__init__.py`:

```python
from . import auth, cli, db, portal, public, reports
from .admin import dashboard as admin_dashboard
from .admin import fleet as admin_fleet
from .admin import rates as admin_rates
```

```python
    app.register_blueprint(auth.bp)
    app.register_blueprint(public.bp)
    app.register_blueprint(portal.bp)
    app.register_blueprint(admin_dashboard.bp)
    app.register_blueprint(admin_fleet.bp)
    app.register_blueprint(admin_rates.bp)
    app.register_blueprint(reports.bp)
```

Change the CSRF error handler's redirect target to `url_for("public.landing")` — reachable by everyone, including a visitor whose session has just expired.

Now that the blueprints are registered, update `partials/_admin_nav.html` to the
new endpoint names. Task 9 deliberately left it pointing at the old ones, because
`url_for` on an unregistered endpoint raises `BuildError` and every admin page
extends the layout that includes this partial:

```html
{{ link('admin_dashboard.dashboard', 'Dashboard', 'dashboard') }}

{{ section('Fleet Management') }}
{{ link('admin_fleet.list_vehicles', 'Vehicles', 'car') }}
{{ link('admin_fleet.add_vehicle', 'Add Vehicle', 'plus') }}
{{ link('admin_fleet.search', 'Search Fleet', 'search') }}

{{ section('Financial') }}
{{ link('admin_rates.rates', 'Rental Rates', 'money') }}

{{ section('Reports') }}
{{ link('reports.reports', 'Fleet Reports', 'report') }}
```

Then split `home_for()` in `rental/auth.py` so each role lands in its own place. Task 6 deliberately left it pointing at a single
endpoint because these blueprints were not registered yet:

```python
def home_for(user: User) -> str:
    """Where a freshly signed-in person belongs: their console or their portal."""
    return url_for("admin_dashboard.dashboard") if user.is_admin else url_for("portal.dashboard")
```

After this change, sign in as each role and confirm the landing page differs;
`tests/test_auth.py`'s login-redirect assertions cover it.

`rental/reports.py` moves under the admin console: give its blueprint `url_prefix="/admin/reports"`, change its routes to `@bp.route("")` and `@bp.route("/export.csv")`, and guard both with `@admin_required`.

- [ ] **Step 6: Finish Task 9's layout switch and remove its transitional wrapper**

Now that `public.landing` and `public.browse` exist, switch `403.html`,
`404.html`, `500.html`, `auth/forgot_password.html` and
`auth/change_password.html` to `{% extends 'layout_public.html' %}`.

Task 9 could not do this, because those five had to keep extending the reduced
`base.html`, whose `{% block body %}` is empty — a `{% block content %}` override
renders nothing when the parent never references that block. So Task 9 gave each
of the five its own `body` block reproducing what the old base supplied:

```html
{% block body %}
<main class="min-h-screen">
  <div class="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">
    {{ flashes() }}
    {% block content %}{% endblock %}
  </div>
</main>
{% endblock %}
```

`layout_public.html` already supplies exactly that skeleton, so switching each
file means **deleting its outer `body`/`main`/padded-div wrapper and its
`flashes()` call entirely**, keeping only the `{% block content %}` body. Leaving
the wrapper in place would nest a second `<main>` and render the flash messages
twice.

That wrapper is duplicated five times right now. Remove every copy. Confirm none
survives:

```bash
grep -rln 'block body' rental/templates/
```

Expected: only `layout_public.html` and `layout_admin.html` (plus
`auth/login.html` and `auth/signup.html`, which legitimately own their full-bleed
page body and do not use the padded column).

Then check for a doubled `<main>` on a rendered error page:

```bash
uv run python -c "
from rental import create_app
app = create_app({'DATABASE_URL':'sqlite://','SECRET_KEY':'x'})
html = app.test_client().get('/nope').get_data(as_text=True)
print('main elements:', html.count('<main'))
"
```

Expected: `main elements: 1`.

- [ ] **Step 7: Create `tests/test_roles.py`**

Task 6 deferred the role matrix to this task, because it asserts on routes that
only exist now. Create `tests/test_roles.py` with the matrix given in Task 6
Step 1, and move the four decorator tests Task 6 put in `tests/test_auth.py`
(`test_guest_mode_is_gone` and the three `/vehicles` guard tests) into it,
retargeting the three at `/admin/vehicles`.

Retarget Task 7's two forced-password-change tests at `/my` with
`customer_client`, which is what they were always meant to exercise.

While you are in `tests/test_auth.py`, strengthen
`test_a_wrong_current_password_is_refused`. As written it asserts only that the
error message appears, which proves the response but not the outcome — a
refactor that moved `set_password` above the verification would still pass it.
Make it assert the password did not change:

```python
def test_a_wrong_current_password_is_refused(app, customer_client):
    response = customer_client.post(
        "/change-password",
        data={
            "current_password": "wrong-password",
            "password": "brandnew123",
            "confirm_password": "brandnew123",
        },
    )
    assert b"current password is not correct" in response.data

    # The message is not the point -- the point is that nothing was written.
    with app.app_context():
        from rental.auth import find_user_by_username

        user = find_user_by_username("maria")
        assert user.check_password("secret123")
        assert not user.check_password("brandnew123")
```

Run: `uv run pytest tests/test_roles.py tests/test_auth.py -q`
Expected: PASS — every parametrised case.

- [ ] **Step 8: Move the fleet tests to their new URLs**

```bash
git mv tests/test_vehicles.py tests/test_fleet.py
sed -i 's#"/vehicles/add"#"/admin/vehicles/add"#g; s#"/vehicles"#"/admin/vehicles"#g; s#f"/vehicles/#f"/admin/vehicles/#g; s#"/search"#"/admin/vehicles/search"#g' tests/test_fleet.py
```

Replace `auth_client` with `admin_client` throughout, and change `test_dashboard_shows_totals` to request `/admin` and assert on "Rental Management Dashboard" rather than "All Vehicles". In `tests/test_reports.py`, the report URLs become `/admin/reports` and `/admin/reports/export.csv`, and `auth_client` becomes `admin_client`.

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass, none skipped.

- [ ] **Step 10: Rebuild the stylesheet and commit**

```bash
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: split the routes into public, portal and admin blueprints"
```

---

### Task 12: The public landing page

**Files:**
- Modify: `rental/public.py`, `rental/templates/public/landing.html`
- Create: `rental/templates/partials/_vehicle_card.html`
- Test: `tests/test_public.py` (create)

**Interfaces:**
- Consumes: Task 11's `public.landing`, Task 10's `vehicle_image` macro
- Produces: `landing()` passes `featured: list[Vehicle]` (up to three) and
  `available_count: int`; the macro `vehicle_card(vehicle)` in
  `partials/_vehicle_card.html`, which Task 13's browse grid also uses

- [ ] **Step 1: Write the failing test**

Create `tests/test_public.py`:

```python
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_public.py -q`
Expected: FAIL — the placeholder template has none of that copy.

- [ ] **Step 3: Fill in the route**

```python
@bp.route("/")
def landing():
    """The storefront's front door: the pitch, the feature cards, three vehicles.

    The featured vehicles are real rows rather than decoration, so the page is
    never selling something the fleet does not have.
    """
    db = get_session()
    featured = db.scalars(
        select(Vehicle)
        .where(Vehicle.is_active.is_(True))
        .where(Vehicle.status == "AVAILABLE")
        .order_by(Vehicle.daily_rate.asc())
        .limit(3)
    ).all()
    available_count = db.scalar(
        select(func.count())
        .select_from(Vehicle)
        .where(Vehicle.is_active.is_(True))
        .where(Vehicle.status == "AVAILABLE")
    ) or 0

    return render_template(
        "public/landing.html", featured=featured, available_count=available_count
    )
```

Add `func`, `select` to the imports in `public.py`.

- [ ] **Step 4: Write the template**

`rental/templates/public/landing.html` extends `layout_public.html` and overrides `main` so the hero can run full width. Sections, in order:

1. **Hero** — a `bg-navy-800 text-white` panel with `py-16 sm:py-24`. An `<h1 class="text-4xl font-extrabold tracking-tight sm:text-5xl">` reading "Rent the Right Vehicle for Your Journey"; a lead paragraph "Browse available vehicles, check availability, and reserve online."; two buttons — `Browse Vehicles` (`.btn.btn-primary`, to `public.browse`) and `Make a Reservation` (`.btn.btn-ghost`, also to `public.browse`, because a reservation begins by choosing a vehicle, so it is a real destination). Below them: `{{ available_count }} vehicle{{ '' if available_count == 1 else 's' }} available now`.
2. **Feature cards** — `grid gap-5 sm:grid-cols-2 lg:grid-cols-4` of `.card`s, each with an icon, a heading and the sentence verbatim from requirement 25:
   - *Easy Reservation* — "Reserve a vehicle online in a few steps." (`calendar`)
   - *Vehicle Availability* — "Check whether a vehicle is available for your selected dates." (`check`)
   - *Automatic Calculation* — "The system automatically calculates your rental cost." (`money`)
   - *Fleet Management* — "Administrators can manage vehicles, reservations, rentals, and maintenance." (`wrench`)
3. **Featured vehicles** — heading "Starting from our best rates", then `grid gap-5 sm:grid-cols-2 lg:grid-cols-3` of `{{ vehicle_card(vehicle) }}`, importing the macro written in Step 4b below.
4. **Closing strip** — the tagline "Online reservation + vehicle availability + automatic rental calculation" and a `Browse Vehicles` button.

Set `{% block title %}Vehicle Rental and Reservation System{% endblock %}`.

- [ ] **Step 4b: Write the vehicle card partial**

`rental/templates/partials/_vehicle_card.html`, matching the layout requirement 5
sketches. It is written here rather than in Task 13 so the markup exists in
exactly one place from the moment it is first needed:

```html
{% from 'partials/_vehicle_image.html' import vehicle_image %}

{% macro vehicle_card(vehicle) %}
<article class="vehicle-card">
  <div class="vehicle-card-media">{{ vehicle_image(vehicle) }}</div>
  <div class="flex flex-1 flex-col gap-3 p-5">
    <div>
      <h3 class="text-base font-bold tracking-tight text-ink">{{ vehicle.brand }} {{ vehicle.model }}</h3>
      <p class="text-sm text-muted">{{ vehicle.vehicle_type }} &middot; {{ vehicle.year }}</p>
    </div>

    <div class="flex flex-wrap gap-1.5">
      <span class="spec-chip">{{ vehicle.seats }} Seats</span>
      <span class="spec-chip">{{ vehicle.transmission }}</span>
      <span class="spec-chip">{{ vehicle.fuel_type }}</span>
    </div>

    <div class="mt-auto flex items-end justify-between gap-3 pt-2">
      <p>
        <span class="rate">₱{{ '{:,.0f}'.format(vehicle.daily_rate) }}</span>
        <span class="text-sm text-muted">/ day</span>
      </p>
      <span class="pill {{ vehicle.badge_class }}">{{ vehicle.status }}</span>
    </div>

    <a class="btn btn-primary w-full" href="{{ url_for('public.vehicle_detail', vehicle_id=vehicle.id) }}">
      View Details
    </a>
  </div>
</article>
{% endmacro %}
```

There is no **Reserve Now** button. It appears in phase 3 with the booking flow
behind it; rendering it now would be a dead control.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_public.py -q`
Expected: PASS

- [ ] **Step 6: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the public landing page"
```

---

### Task 13: The public browse grid with filters and pagination

**Files:**
- Modify: `rental/public.py`, `rental/templates/public/browse.html`
- Test: `tests/test_public.py`

**Interfaces:**
- Consumes: Task 11's `paginate(query, page, per_page)` and `GRID_PER_PAGE`;
  Task 12's `vehicle_card(vehicle)` macro in `partials/_vehicle_card.html`
- Produces: `browse()` reading `type`, `transmission`, `seats`, `min_rate`, `max_rate`, `page` from the query string

- [ ] **Step 1: Write the failing test**

Append to `tests/test_public.py`:

```python
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_public.py -q`
Expected: FAIL — the placeholder browse template lists nothing.

- [ ] **Step 3: Fill in the route**

```python
@bp.route("/vehicles")
def browse():
    """The storefront grid: every active vehicle, narrowed by the filter form.

    Filters are plain GET parameters so a filtered grid can be bookmarked and
    shared. Date-based availability filtering arrives with the booking engine in
    phase 3; these filters are the ones that depend only on the vehicle itself.
    """
    vehicle_type = request.args.get("type", "")
    transmission = request.args.get("transmission", "")
    seats = request.args.get("seats", type=int)
    min_rate = request.args.get("min_rate", type=float)
    max_rate = request.args.get("max_rate", type=float)
    page = request.args.get("page", 1, type=int)

    query = select(Vehicle).where(Vehicle.is_active.is_(True))
    if vehicle_type in VEHICLE_TYPES:
        query = query.where(Vehicle.vehicle_type == vehicle_type)
    if transmission in TRANSMISSIONS:
        query = query.where(Vehicle.transmission == transmission)
    if seats:
        query = query.where(Vehicle.seats >= seats)
    if min_rate is not None:
        query = query.where(Vehicle.daily_rate >= Decimal(str(min_rate)))
    if max_rate is not None:
        query = query.where(Vehicle.daily_rate <= Decimal(str(max_rate)))

    query = query.order_by(Vehicle.daily_rate.asc(), Vehicle.brand.asc())
    vehicles, page, total_pages, total = paginate(query, page, GRID_PER_PAGE)

    return render_template(
        "public/browse.html",
        vehicles=vehicles,
        total=total,
        page=page,
        total_pages=total_pages,
        vehicle_type=vehicle_type,
        transmission=transmission,
        seats=seats,
        min_rate=min_rate,
        max_rate=max_rate,
        filtered=bool(vehicle_type or transmission or seats or min_rate or max_rate),
    )
```

Add to `public.py`'s imports: `from decimal import Decimal`, `request` from flask, `TRANSMISSIONS` and `VEHICLE_TYPES` from `.models`, and `from .admin.fleet import GRID_PER_PAGE, paginate`.

- [ ] **Step 5: Write the browse template**

`public/browse.html` extends `layout_public.html`:

- `<h1 class="page-title">Available Vehicles</h1>`, then `{{ total }} vehicle{{ '' if total == 1 else 's' }}`.
- A filter `<form method="get">` in a `.card`, laid out `grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5`:
  - **Type** — a select whose first option is blank with the label "All types", then `VEHICLE_TYPES`
  - **Transmission** — blank "All", then `TRANSMISSIONS`
  - **Minimum seats** — blank "Any", then 2, 4, 5, 7, 12, 15
  - **Min rate** and **Max rate** — `<input type="number" class="field" step="50" min="0">`
  Each control re-renders its current value (`{% if vehicle_type == t %}selected{% endif %}`, `value="{{ min_rate or '' }}"`) so a filtered page round-trips. A `Search Vehicles` `.btn.btn-primary` submit, and when `filtered`, a `Clear` `.btn.btn-ghost` linking back to `public.browse`.
- The grid: `grid gap-5 sm:grid-cols-2 lg:grid-cols-3`, each cell `{{ vehicle_card(vehicle) }}`.
- When `vehicles` is empty, this `.card` instead of the grid:

```html
<div class="card p-10 text-center">
  <p class="text-base font-semibold text-ink">No vehicles match those filters.</p>
  <p class="mt-1.5 text-sm text-muted">Try widening your price range, or clearing a filter.</p>
  <a class="btn btn-primary mt-5" href="{{ url_for('public.browse') }}">Show all vehicles</a>
</div>
```

- Include `partials/_pagination.html` underneath, which already preserves the query string.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_public.py -q`
Expected: PASS

- [ ] **Step 7: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the public browse grid with filters"
```

---

### Task 14: The public vehicle detail page

**Files:**
- Modify: `rental/public.py`, `rental/templates/public/vehicle_detail.html`
- Test: `tests/test_public.py`

**Interfaces:**
- Consumes: Task 10's `vehicle_image` macro, Task 4's `RentalRates.current`, Task 6's `current_role`
- Produces: `vehicle_detail(vehicle_id)` passing `vehicle` and `rates`; 404s an inactive vehicle for anyone who is not an admin

- [ ] **Step 1: Write the failing test**

Append to `tests/test_public.py`:

```python
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_public.py -q`
Expected: FAIL — the placeholder template shows none of it, and a disabled vehicle still returns 200.

- [ ] **Step 3: Fill in the route**

```python
@bp.route("/vehicles/<int:vehicle_id>")
def vehicle_detail(vehicle_id: int):
    """One vehicle's public page.

    A disabled vehicle is 404 for a visitor -- it is not part of the fleet on
    offer -- but stays reachable for an admin, who follows this link from the
    console to see what a customer would see.
    """
    db = get_session()
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    if not vehicle.is_active and current_role() != "admin":
        abort(404)

    return render_template(
        "public/vehicle_detail.html", vehicle=vehicle, rates=RentalRates.current(db)
    )
```

Add `from .auth import current_role` and `RentalRates` to the imports.

- [ ] **Step 4: Write the template**

`public/vehicle_detail.html` extends `layout_public.html`. A `grid gap-8 lg:grid-cols-[3fr_2fr]` that stacks on small screens.

**Left column:**
- A `.card` with the image in an `aspect-[16/10]` frame: `{{ vehicle_image(vehicle) }}`.
- `<h1 class="page-title">{{ vehicle.display_name }}</h1>`, with the type and the status pill beneath: `<span class="pill {{ vehicle.badge_class }}">{{ vehicle.status }}</span>`.
- A specification block — Category, Year, Seats, Transmission, Fuel type, Plate number — as a `grid grid-cols-2 gap-4 sm:grid-cols-3` of `.stat-label` / value pairs.
- `{% if vehicle.description %}` the description in a `.card`.

**Right column** — a `lg:sticky lg:top-24` `.card`:
- The rate: `<span class="rate">₱{{ '{:,.2f}'.format(vehicle.daily_rate) }}</span> <span class="text-muted">/ day</span>`, and when `vehicle.hourly_rate`, a second line `₱{{ '{:,.2f}'.format(vehicle.hourly_rate) }} / hour`.
- An **Optional extras** list reading the fees straight off `rates`, so nothing is hardcoded:
  `Additional driver — ₱{{ '{:,.2f}'.format(rates.additional_driver_fee_per_day) }} / day`
  `Insurance — ₱{{ '{:,.2f}'.format(rates.insurance_fee_per_day) }} / day`
- Availability messaging driven by the vehicle's state:

```html
{% if vehicle.status == 'MAINTENANCE' %}
  <div class="alert alert-warning mt-4">
    <span>Currently unavailable. This vehicle is under maintenance.</span>
  </div>
{% endif %}
```

- Where the booking widget will go — which must not look like a disabled control:

```html
{% if is_customer %}
  <p class="mt-4 text-sm text-muted">Online booking opens soon. Call the office to reserve this vehicle.</p>
  <a class="btn btn-ghost mt-3 w-full" href="{{ url_for('public.browse') }}">Browse more vehicles</a>
{% else %}
  <p class="mt-4 text-sm text-muted">Create an account to reserve a vehicle online.</p>
  <a class="btn btn-primary mt-3 w-full" href="{{ url_for('auth.signup') }}">Create account</a>
  <a class="btn btn-ghost mt-2 w-full" href="{{ url_for('auth.login') }}">Log in</a>
{% endif %}
```

The date picker and **Reserve Now** land in phase 3.

- Set `{% block title %}{{ vehicle.display_name }} · Vehicle Rental{% endblock %}`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_public.py -q`
Expected: PASS

- [ ] **Step 6: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the public vehicle detail page"
```

---

### Task 15: Admin fleet CRUD with the new fields and disable/enable

The vehicle table and forms finish their move from an inventory register to a rental fleet.

**Files:**
- Modify: `rental/templates/partials/_vehicle_table.html`, `rental/templates/admin/vehicle_detail.html`, `admin/vehicle_form.html`, `admin/search.html`, `rental/templates/partials/_vehicle_form_fields.html`
- Test: `tests/test_fleet.py`

**Interfaces:**
- Consumes: Task 11's `admin_fleet` blueprint including `toggle_active`, Task 3's `VehicleForm` fields
- Produces: no new Python interfaces

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fleet.py`:

```python
def test_the_fleet_table_shows_the_daily_rate(admin_client, sample_vehicle):
    assert "₱2,200.00".encode() in admin_client.get("/admin/vehicles").data


def test_adding_a_vehicle_without_a_rate_is_refused(admin_client):
    response = admin_client.post("/admin/vehicles/add", data=dict(NEW_VEHICLE, daily_rate=""))
    assert response.status_code == 200
    assert b"Daily rate is required." in response.data


def test_a_negative_rate_is_refused(admin_client):
    response = admin_client.post("/admin/vehicles/add", data=dict(NEW_VEHICLE, daily_rate="-50"))
    assert b"cannot be negative" in response.data


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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: FAIL — the table has no rate column.

- [ ] **Step 3: Update the fleet table**

In `partials/_vehicle_table.html`, the columns become Plate, Vehicle, Type, Seats, Rate, Status, Actions.

The Vehicle cell carries the brand and model with the year beneath:

```html
<td>
  <p class="font-semibold text-ink">{{ vehicle.brand }} {{ vehicle.model }}</p>
  <p class="text-xs text-muted">{{ vehicle.year }}</p>
</td>
```

The rate cell:

```html
<td class="font-mono text-sm whitespace-nowrap">₱{{ '{:,.2f}'.format(vehicle.daily_rate) }}</td>
```

The status cell keeps the existing pill and gains a disabled marker:

```html
<td>
  <span class="pill {{ vehicle.badge_class }}">{{ vehicle.status }}</span>
  {% if not vehicle.is_active %}<span class="pill pill-slate">DISABLED</span>{% endif %}
</td>
```

Actions keep View / Edit / Delete, guarded by `is_admin`.

- [ ] **Step 4: Add the disable control to the detail page**

In `admin/vehicle_detail.html`, beside Edit and Delete:

```html
<form method="post" action="{{ url_for('admin_fleet.toggle_active', vehicle_id=vehicle.id) }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <button type="submit" class="btn {% if vehicle.is_active %}btn-ghost{% else %}btn-success{% endif %}">
    {% if vehicle.is_active %}Disable vehicle{% else %}Re-enable vehicle{% endif %}
  </button>
</form>
<p class="field-hint">
  A disabled vehicle leaves the storefront and cannot be booked. Its record and history are kept.
</p>
```

Add a "View as a customer" link to `public.vehicle_detail` alongside it.

- [ ] **Step 5: Group the form fields**

In `partials/_vehicle_form_fields.html`, group the fields under four `<fieldset>`s with legends styled like `.field-label`, so the form stops reading as one long column. Inside each, `grid grid-cols-1 gap-x-5 gap-y-4 sm:grid-cols-2`:

- **Vehicle** — plate number, brand, model, year, type, colour
- **Rental specification** — seats, transmission, fuel type
- **Rates and availability** — daily rate, hourly rate, status, image URL
- **Description** — the description textarea, full width (`sm:col-span-2`)

- [ ] **Step 6: Update the fleet search page**

`admin/search.html` keeps its text box and its status and type filters. The status select's options become `VEHICLE_STATUSES`, and the results table is the updated `_vehicle_table.html`. Confirm `admin/fleet.py`'s `search()` tests `if status in VEHICLE_STATUSES`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: PASS

- [ ] **Step 8: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: adapt the admin fleet console for rental vehicles"
```

---

### Task 16: The Rental Management Dashboard

**Files:**
- Modify: `rental/templates/admin/dashboard.html`
- Test: `tests/test_fleet.py`

**Interfaces:**
- Consumes: Task 11's `admin_dashboard.dashboard` and the six values it passes: `total`, `counts`, `pending`, `pickups_today`, `returns_today`, `revenue`
- Produces: no new Python interfaces

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fleet.py`:

```python
def test_the_admin_dashboard_counts_the_real_fleet(admin_client, sample_vehicle):
    response = admin_client.get("/admin")
    assert response.status_code == 200
    assert b"Rental Management Dashboard" in response.data
    assert b"Total Vehicles" in response.data
    assert b"Currently Rented" in response.data
    assert b"Pending Reservations" in response.data


def test_revenue_is_zero_until_a_rental_completes(admin_client, sample_vehicle):
    assert "₱0.00".encode() in admin_client.get("/admin").data
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: FAIL — the placeholder dashboard has none of that copy.

- [ ] **Step 3: Write the template**

`admin/dashboard.html` extends `layout_admin.html`:

- `<h1 class="page-title">Rental Management Dashboard</h1>` with a `mt-1 text-sm text-muted` subtitle: "Online reservation + vehicle availability + automatic rental calculation".
- **Fleet row** — `grid gap-4 sm:grid-cols-2 lg:grid-cols-5`, five `.stat-card`s using `.stat-label` and `.stat-value`:
  Total Vehicles (`total`), Available (`counts['AVAILABLE']`), Reserved (`counts['RESERVED']`), Currently Rented (`counts['RENTED']`), Under Maintenance (`counts['MAINTENANCE']`). The four status cards each carry their matching pill: `<span class="pill {{ STATUS_BADGES['AVAILABLE'] }}">AVAILABLE</span>`.
- **Operations row** — `mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4`: Pending Reservations (`pending`), Today's Pickups (`pickups_today`), Today's Returns (`returns_today`), Total Rental Revenue (`₱{{ '{:,.2f}'.format(revenue) }}`).
- One explanatory line underneath, because zeroes on a fresh system otherwise read as broken:

```html
<p class="mt-3 text-xs text-muted">
  Reservation and rental figures start reporting as soon as the first booking is made.
</p>
```

- **Quick actions** — a `.card` with buttons to Add Vehicle, Vehicles, Rental Rates and Fleet Reports. Only pages that exist.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: PASS

- [ ] **Step 5: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the Rental Management Dashboard"
```

---

### Task 17: The customer's My Rental Dashboard

**Files:**
- Modify: `rental/portal.py`, `rental/templates/customer/dashboard.html`
- Test: `tests/test_roles.py`

**Interfaces:**
- Consumes: Task 6's `current_user`, Task 11's `portal` blueprint
- Produces: `portal.dashboard()` passing `available`, `my_reservations`, `active_rental`, `total_rentals`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roles.py`:

```python
def test_the_customer_dashboard_greets_them_by_name(customer_client):
    assert b"Welcome, Maria Santos" in customer_client.get("/my").data


def test_the_customer_dashboard_counts_are_real_and_start_at_zero(customer_client, sample_vehicle):
    response = customer_client.get("/my")
    assert b"My Reservations" in response.data
    assert b"Available Vehicles" in response.data
    assert b"Total Rentals" in response.data


def test_the_customer_dashboard_offers_a_way_into_the_storefront(customer_client):
    assert b"Browse Vehicles" in customer_client.get("/my").data


def test_the_customer_dashboard_has_an_empty_reservations_state(customer_client):
    response = customer_client.get("/my")
    assert b"don&#39;t have any reservations yet" in response.data
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_roles.py -q`
Expected: FAIL — the placeholder template has none of that copy.

- [ ] **Step 3: Fill in the route**

```python
@bp.route("")
@customer_required
def dashboard():
    """The customer's own summary: what is on offer, and what they have booked.

    Every count is scoped to the signed-in customer. Reservation and rental
    figures are legitimately zero until phase 3 provides a way to create one.
    """
    db = get_session()
    user = current_user()

    available = db.scalar(
        select(func.count())
        .select_from(Vehicle)
        .where(Vehicle.is_active.is_(True))
        .where(Vehicle.status == "AVAILABLE")
    ) or 0
    my_reservations = db.scalar(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.user_id == user.id)
        .where(Reservation.status.in_(["PENDING", "CONFIRMED"]))
    ) or 0
    active_rental = db.scalar(
        select(func.count())
        .select_from(Rental)
        .where(Rental.customer_id == user.id)
        .where(Rental.status == "ACTIVE")
    ) or 0
    total_rentals = db.scalar(
        select(func.count()).select_from(Rental).where(Rental.customer_id == user.id)
    ) or 0

    return render_template(
        "customer/dashboard.html",
        available=available,
        my_reservations=my_reservations,
        active_rental=active_rental,
        total_rentals=total_rentals,
    )
```

Add to `portal.py`'s imports: `func`, `select` from sqlalchemy, `from .db import get_session`, `from .auth import current_user, customer_required`, and `from .models import Rental, Reservation, Vehicle`.

- [ ] **Step 4: Write the template**

`customer/dashboard.html` extends `layout_public.html`, because a customer stays inside the storefront chrome:

- `<h1 class="page-title">Welcome, {{ current_user.display_name }}</h1>` with a `mt-1 text-sm text-muted` subtitle "My Rental Dashboard".
- A `mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4` of four `.stat-card`s: Available Vehicles (`available`), My Reservations (`my_reservations`), Active Rental (`active_rental`), Total Rentals (`total_rentals`).
- A `.card` call to action: heading "Ready for your next trip?", the line "Browse the fleet, pick your dates, and reserve online.", and a `Browse Vehicles` `.btn.btn-primary` to `public.browse`.
- The empty state for the reservations that do not exist yet, worded as requirement 36 asks:

```html
<div class="card mt-6 p-10 text-center">
  <p class="text-base font-semibold text-ink">You don't have any reservations yet.</p>
  <p class="mt-1.5 text-sm text-muted">
    Browse our available vehicles and make your first reservation.
  </p>
  <a class="btn btn-primary mt-5" href="{{ url_for('public.browse') }}">Browse Vehicles</a>
</div>
```

The Find a Vehicle date search belongs to phase 3 and is not rendered here.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_roles.py -q`
Expected: PASS. If the empty-state assertion fails, check how Jinja escaped the apostrophe in "don't" and match the escaped form.

- [ ] **Step 6: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the customer rental dashboard"
```

---

### Task 18: The Rental Rates admin page

**Files:**
- Modify: `rental/templates/admin/rates.html`
- Test: `tests/test_fleet.py`

**Interfaces:**
- Consumes: Task 11's `admin_rates.rates` and `RentalRatesForm`
- Produces: no new Python interfaces

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fleet.py`:

```python
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


def test_a_negative_fee_is_refused(admin_client):
    response = admin_client.post(
        "/admin/rates",
        data={
            "additional_driver_fee_per_day": "-1",
            "insurance_fee_per_day": "300.00",
            "late_fee_per_day": "800.00",
        },
    )
    assert b"cannot be negative" in response.data


def test_a_customer_cannot_change_the_rates(customer_client):
    assert customer_client.post(
        "/admin/rates",
        data={
            "additional_driver_fee_per_day": "1.00",
            "insurance_fee_per_day": "1.00",
            "late_fee_per_day": "1.00",
        },
    ).status_code == 403
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: FAIL — the placeholder template renders no form.

- [ ] **Step 3: Write the template**

`admin/rates.html` extends `layout_admin.html`:

- `<h1 class="page-title">Rental Rates</h1>` and a subtitle: "These fees apply to every reservation. Each vehicle's own daily and hourly rate is set on the vehicle itself."
- A `.card` holding the form: `method="post"`, the CSRF hidden input, the three `DecimalField`s in a `grid gap-5 sm:grid-cols-3` rendered with `.field-label` / `.field` / `.field-error`, each hinted "per day" and prefixed `₱`.
- A `.btn.btn-primary` submit and a `Cancel` `.btn.btn-ghost` back to `admin_dashboard.dashboard`.
- Below the form, a `.card` worked example reading the live values, which demonstrates nothing is hardcoded:

```html
<h2 class="text-sm font-semibold text-ink">How a total is built</h2>
<dl class="mt-3 space-y-1.5 text-sm">
  <div class="flex justify-between"><dt class="text-muted">Base rental</dt>
    <dd class="font-mono">daily rate × days</dd></div>
  <div class="flex justify-between"><dt class="text-muted">Additional driver</dt>
    <dd class="font-mono">₱{{ '{:,.2f}'.format(rates.additional_driver_fee_per_day) }} × days</dd></div>
  <div class="flex justify-between"><dt class="text-muted">Insurance</dt>
    <dd class="font-mono">₱{{ '{:,.2f}'.format(rates.insurance_fee_per_day) }} × days</dd></div>
  <div class="flex justify-between"><dt class="text-muted">Late return</dt>
    <dd class="font-mono">₱{{ '{:,.2f}'.format(rates.late_fee_per_day) }} × late days</dd></div>
</dl>
<p class="mt-3 text-xs text-muted">
  Rental totals are calculated automatically when a customer reserves.
</p>
```

- [ ] **Step 3b: Strengthen a weak test you are sitting next to**

While you are in `tests/test_fleet.py`, fix `test_a_negative_rate_is_refused`.
As written it asserts only that an error message appeared in the response, which
proves the message and not the outcome — a regression that rendered the error
while still writing the row would pass it. Its sibling
`test_adding_a_vehicle_without_a_rate_is_refused` at least checks the status
code; this one checks neither that nor the database.

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_fleet.py -q`
Expected: PASS. If `test_saving_new_rates_persists_them` fails on the zero insurance fee, `RentalRatesForm` is still using `DataRequired` — switch those three fields to `InputRequired`.

- [ ] **Step 5: Run the suite, rebuild the stylesheet and commit**

```bash
uv run pytest -q
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git add -A
git commit -m "feat: add the rental rates admin page"
```

---

### Task 19: Branding sweep, README, and phase-1 verification

The last task. Nothing in the interface may still call this an inventory system.

**Files:**
- Modify: `README.md`, `rental/templates/auth/login.html`, `auth/signup.html`, `403.html`, `404.html`, `500.html`
- Modify: any file the grep sweep turns up

**Interfaces:**
- Consumes: everything
- Produces: nothing new

- [ ] **Step 1: Sweep for inventory language**

Run:

```bash
grep -rniE 'inventor' --include='*.py' --include='*.html' --include='*.css' --include='*.toml' --include='*.md' . \
  | grep -v '\.venv' | grep -v '__pycache__' | grep -v '\.git/' | grep -v '^\./docs/superpowers/'
```

Every hit must be rewritten. `docs/superpowers/` is excluded because the spec and this plan quote the old name deliberately. Use the substitutions requirement 35 gives: *Vehicle Inventory* → *Vehicle Rental*; *Inventory Management* → *Rental Management*; *Inventory Dashboard* → *Rental Dashboard*; *Add Vehicle to Inventory* → *Add Vehicle*; *Inventory Report* → *Rental Report*. "Fleet Management" is the right name for the admin vehicle section.

- [ ] **Step 1b: Fix the copy that names the renamed columns**

Task 2 renamed `Vehicle.make` to `brand`, but three pieces of user-visible copy
still describe the free-text search as matching on "make". The search now
matches `Vehicle.brand`, so this copy names a column that no longer exists.
Step 1's grep looks only for "inventor" and will not find these:

- `rental/templates/admin/dashboard.html` — the Search quick-action blurb
  "Find a vehicle by plate, make or model." becomes "...by plate, brand or model."
- `rental/templates/admin/search.html` — "Match on plate number, make or model,
  then narrow by status or type." becomes "...plate number, brand or model..."
- `rental/templates/admin/search.html` — the label `Plate, make or model`
  becomes `Plate, brand or model`

Leave `rental/templates/base.html`'s "Sign in to make changes" alone — that is
the ordinary verb, not the field.

Confirm afterwards:

```bash
grep -rn 'plate, make\|plate number, make\|by plate, make' --include='*.html' rental/
```

Expected: no output.

- [ ] **Step 1c: Clear two pieces of dead scaffolding**

Both were left deliberately by earlier tasks because the files were outside
their scope. This task touches everything, so they land here.

**The dead `STATUSES` alias.** `rental/__init__.py`'s context processor exposes
both `STATUSES` and `VEHICLE_STATUSES` pointing at the same constant. Task 6 kept
the alias because `admin/search.html` still read the old name; Task 15 switched
that template to `VEHICLE_STATUSES`, so nothing consumes the alias now. Confirm
and remove it:

```bash
grep -rn 'STATUSES' rental/templates/
```

Every hit should say `VEHICLE_STATUSES`. If so, delete the `"STATUSES"` key from
`inject_globals` and the stale comment beside it — the comment still points at
Task 9, which has long since passed without removing it.

**The DISABLED pill shares a colour with MAINTENANCE.** Both render `pill-slate`,
so a vehicle that is under maintenance *and* disabled shows two adjacent grey
pills distinguished only by their text. Give the disabled marker `pill-red`
instead, in both places it appears:

- `partials/_vehicle_table.html` — the status cell
- `rental/templates/admin/vehicle_detail.html` — beside the status pill

`pill-red` already exists in `input.css` and is already listed in the
`@source inline(...)` directive, so no CSS change and no new class are needed.
Red reads correctly here: MAINTENANCE is a temporary state the vehicle will come
back from, while disabled is a deliberate removal from service.

Verify afterwards:

```bash
grep -rn 'DISABLED' rental/templates/
```

Expected: both hits carry `pill-red`.

- [ ] **Step 2: Rewrite the login page**

`auth/login.html` keeps its full-bleed split layout and its photograph. The panel copy becomes:

- `<h1>` **Vehicle Rental and Reservation System**
- Subtitle: **Book your vehicle online with ease.**
- The username and password fields, unchanged.
- **Log in** — `.btn.btn-primary`, full width.
- **Create Account** — `.btn.btn-ghost`, full width, to `auth.signup`.
- **Browse Vehicles** — `.btn.btn-ghost`, full width, to `public.browse`.
- **Forgot password?** — a text link to `auth.forgot_password`.

All four destinations exist and work.

`auth/signup.html` gets the same heading treatment, and its form gains the `full_name` and `phone` fields added in Task 6.

- [ ] **Step 3: Rewrite the error pages**

- `403.html` — "This page belongs to a different kind of account." with Home and Log in buttons.
- `404.html` — "We couldn't find that page." with Home and Browse Vehicles.
- `500.html` — copy unchanged; confirm it extends `layout_public.html`.

- [ ] **Step 4: Rewrite the README**

Replace the title, the intro paragraph and the features table. The features table becomes the phase-1 feature set: Landing page, Browse Vehicles, Vehicle Detail, Sign up / Log in, Password reset request, My Rental Dashboard, Rental Management Dashboard, Fleet Management (CRUD, search, disable), Rental Rates, Fleet Reports.

Rewrite **Data model** from the spec's schema tables — all six models. Rewrite **Roles** for `admin` / `customer` and the three decorators. Update every path from `inventory/` to `rental/`, including the Tailwind commands and the project tree. Add a **Getting started** block:

```bash
uv sync
DATABASE_URL=sqlite:///rental.db uv run flask reset-db --password 'choose-one' --demo-password 'choose-one'
uv run flask run
```

Add a short **Roadmap** naming phases 2–4, so a reader knows booking is deliberately absent rather than broken.

- [ ] **Step 5: Verify the sweep is clean**

Run:

```bash
grep -rniE 'inventor' --include='*.py' --include='*.html' --include='*.md' . \
  | grep -v '\.venv' | grep -v '__pycache__' | grep -v '\.git/' | grep -v '^\./docs/'
```

Expected: no output.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: every test passes, none skipped. Record the count.

- [ ] **Step 7: Verify the app actually runs against a real database**

> **Pin `DATABASE_URL` on every command below.** `reset-db` drops every table,
> and `--yes` exists to bypass its non-SQLite guard. `load_dotenv()` searches
> upward from the package, so in a git worktree — which has no `.env` of its own
> — it finds the parent checkout's, which may carry a live production URL. A bare
> `flask reset-db --yes` there targets that remote database, not SQLite. Setting
> `DATABASE_URL` explicitly makes the target unambiguous and makes `--yes`
> unnecessary, so it is dropped. If any command here fails for want of a
> database, set `DATABASE_URL` — never add `--yes` to make the error go away.

```bash
rm -f /tmp/phase1-verify.db
export DATABASE_URL=sqlite:////tmp/phase1-verify.db
uv run flask reset-db --password 'demo-admin-pw' --demo-password 'demo-cust-pw'
uv run flask run --port 5001 &
sleep 3
for path in / /vehicles /vehicles/1 /login /signup /forgot-password; do
  printf '%s -> ' "$path"
  curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:5001$path"
done
curl -s -o /dev/null -w '/admin (anonymous) -> %{http_code}\n' "http://127.0.0.1:5001/admin"
kill %1
rm -f /tmp/phase1-verify.db
unset DATABASE_URL
```

Expected: `200` for the six public paths, `302` for `/admin`.

Then in a browser, sign in as `admin` and confirm: the dashboard shows 10 vehicles, 9 available and 1 under maintenance; `/admin/vehicles` lists them with rates; adding, editing and disabling a vehicle all work; `/admin/rates` saves. Sign in as `maria` and confirm `/my` greets her by name and `/admin` returns 403.

- [ ] **Step 8: Check the page at phone width**

With the server still running, open `/`, `/vehicles` and `/admin` at 360 px wide. Confirm there is no horizontal scrollbar, the public menu collapses into the `<details>` drop-down, the vehicle grid is one column, and the admin table scrolls inside its own container rather than pushing the page wide.

- [ ] **Step 9: Confirm the stylesheet is current**

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
git status --porcelain rental/static/css/output.css
```

Expected: no output — the committed stylesheet already matches the templates. If
it changed, commit it. This check is only meaningful because the Tailwind version
bump was taken once, in its own commit, before the feature tasks began.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: complete the rental system rebrand and rewrite the README"
```

---

## Phase 1 acceptance

Check these before declaring the phase done. They are the subset of requirement 40's checklist that phase 1 is responsible for.

**Authentication**
- [ ] Admin login works and lands on the Rental Management Dashboard
- [ ] Customer login works and lands on My Rental Dashboard
- [ ] A customer gets 403 on every admin page
- [ ] An admin gets 403 on the customer portal
- [ ] A disabled account cannot sign in
- [ ] A temporary password forces a change before anything else loads

**Public storefront**
- [ ] An anonymous visitor can reach `/`, `/vehicles` and `/vehicles/<id>`
- [ ] The landing page's every button leads somewhere real
- [ ] Browse filters by type, transmission, seats and rate range, and the filters round-trip
- [ ] The empty state offers a way out
- [ ] A vehicle with no photo shows its type silhouette, not a broken image

**Fleet**
- [ ] Admin can add, edit, disable and delete a vehicle
- [ ] A new vehicle appears on the customer-facing browse grid
- [ ] A disabled vehicle disappears from it and 404s for a visitor
- [ ] Duplicate plate numbers are refused with a message on the field

**Rates**
- [ ] Rental rates save, including a zero fee
- [ ] The saved fees appear on the vehicle detail page
- [ ] No fee is hardcoded in any template

**Data**
- [ ] `flask reset-db` produces a working demo database from nothing
- [ ] It refuses a non-SQLite URL without `--yes`
- [ ] The seeded maintenance vehicle's status agrees with its maintenance record
- [ ] Dashboard statistics all come from queries; none is a literal

**UI**
- [ ] No "Vehicle Inventory Management System" branding remains outside `docs/`
- [ ] Every rendered button leads somewhere that works
- [ ] The layout works at 360 px and at 1440 px
- [ ] No browser console errors on any page
- [ ] `uv run pytest -q` is green with nothing skipped
