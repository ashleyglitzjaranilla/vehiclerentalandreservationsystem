# Vehicle Rental and Reservation System

**Date:** 2026-09-28
**Status:** Approved
**Scope of this document:** the whole transformation at architecture level, plus
**phase 1 in full detail**. Phases 2–4 are outlined here and get their own specs.

## Problem

The app is a Vehicle Inventory Management System: an admin signs in and keeps a
table of vehicles up to date. It has no customers, no dates, no money and no
concept of a vehicle being booked.

It needs to become a Vehicle Rental and Reservation System, whose central
workflow is:

```text
Customer → search → availability → reservation → rental calculation
        → admin confirmation → rental → return
```

The existing vehicle CRUD is not thrown away. It becomes the Fleet Management
section of the admin console.

## Why this is phased

The requirement set is a public storefront, a reservation engine with conflict
detection, a rental lifecycle, a rates and fees system, a maintenance module,
three report types, a customer portal and a rebuilt admin console — roughly five
to eight times the current 1,000 lines. Landing it as one change means a long
stretch where nothing works.

Four phases. Each ends with the app running, the tests green, and every button
on screen doing something real.

| Phase | Scope | Ends with |
| --- | --- | --- |
| **1 · Foundation** | Schema, roles, `reset-db` + seed, branding, public browse, admin fleet CRUD, rental rates | A rental system an admin can stock and a visitor can browse. No booking. |
| **2 · Domain core** | `pricing`, `availability`, `lifecycle` — pure modules, test-first | Unit tests covering overlap, hourly/daily pricing, late fees, every transition. |
| **3 · Customer surface** | Date search, booking widget, reserve, My Reservations, My Rentals, profile | §32's customer half, end to end. |
| **4 · Admin console + reports** | Rental dashboard, reservations, active rentals, availability, maintenance, customers, revenue, reports + CSV | §32's admin half; full acceptance checklist. |

Phase 2 precedes phase 3 on purpose. The conflict and pricing rules are the part
most likely to be subtly wrong, and they are far cheaper to get right against
unit tests than by clicking through a UI.

## Architecture

`vehicles.py` is already 269 lines and would grow past 1,200. The package is
restructured, and renamed from `inventory` to `rental`:

```text
rental/
  domain/            pure Python — no Flask, no SQLAlchemy session
    pricing.py         duration and money
    availability.py    date-overlap rules
    lifecycle.py       legal state transitions and their guards
  models.py          User, Vehicle, Reservation, Rental, Maintenance, RentalRates
  auth.py            login, signup, logout, password reset, three decorators
  public.py          landing, browse, vehicle detail, availability check
  booking.py         create / view / cancel a reservation        (customer)
  portal.py          my reservations, my rentals, profile        (customer)
  admin/
    dashboard.py  fleet.py  reservations.py  rentals.py
    maintenance.py  customers.py  rates.py  reports.py
  forms.py  db.py  cli.py
  templates/
    layout_public.html  layout_admin.html  base.html
    public/  customer/  admin/  partials/
```

### The `domain/` boundary

The three domain modules take plain values — `datetime`, `Decimal`, lists of
intervals — and return plain values. No `request`, no `session`, no query.

This is the load-bearing decision of the whole design. It puts the conflict rule
in exactly one place, so §8's demand that validation happen on both the frontend
and the backend is satisfied by two callers of one function rather than by two
implementations that drift apart. It also means the rules can be tested
exhaustively without a database.

### What is reused

`db.py` and the per-request session handling are untouched. `auth.py` is
extended, not rewritten. The vehicle CRUD moves to `admin/fleet.py` with new
fields. `reports.py`'s CSV writer is generalised to serve three reports.
Tailwind stays as it is: v4, prebuilt `output.css` committed, no build step on
Vercel.

## Two contradictions in the requirements, and how they are resolved

### Vehicle status is not the same thing as availability

§9 says a vehicle reserved 28 Sep – 2 Oct is available 3–6 Oct. §8 says a
rented vehicle cannot be reserved, full stop. Both cannot hold.

- `Vehicle.status` is the vehicle's state **right now** — `AVAILABLE`,
  `RESERVED`, `RENTED`, `MAINTENANCE`. It is maintained by lifecycle transitions
  and shown as a badge.
- Bookability for a date range is **computed**, never read off `status`.
- `MAINTENANCE`, and a vehicle with `is_active = false`, block **all** booking.
  `RESERVED` and `RENTED` block **only overlapping dates**.

Without this split, §9's own worked example fails.

The overlap rule, applied against pending and confirmed reservations, active
rentals, and every maintenance window that is not yet completed:

```text
conflict  ⟺  existing_start < new_end  AND  existing_end > new_start
```

Touching endpoints do not conflict: a rental returning at 10:00 leaves the
vehicle bookable from 10:00.

### Hourly pricing must not have a cliff

Hourly rental was requested, but §7 and §8 only describe whole days. A naive
"under 24 hours bills hourly" rule makes a 23-hour rental cost more than a
25-hour one. Instead:

```text
hours       = pickup_at → return_at
full_days   = hours // 24
extra_hours = hours % 24

base_amount = full_days × daily_rate
            + min(extra_hours × hourly_rate, daily_rate)

minimum charge: 1 hour
```

`hourly_rate` is nullable per vehicle. When it is null the vehicle is daily-only
and any part-day rounds up to a whole day. This is monotonic — a longer rental
never costs less — and reproduces §7's worked example exactly for whole-day
rentals: 3 days × ₱1,500 = ₱4,500.

Optional extras are per day of the rental, counting a part-day as a day:

```text
fee_days         = ceil(hours / 24)
additional_fees  = fee_days × (additional_driver_fee? + insurance_fee?)
late_fee         = ceil(late_hours / 24) × late_fee_per_day
```

---

# Phase 1 — Foundation

## Schema

`flask reset-db` drops every table, recreates them and seeds demo data. The only
data in the live database today is seeded samples, so nothing of value is lost
and every demo starts from a known state. This also makes the column renames
below free.

Money is `Numeric(10, 2)`. All arithmetic happens in `Decimal` and is explicitly
quantised to two places; no float ever touches a peso amount.

### users

Existing: `id`, `username` (unique), `email` (unique), `password_hash`,
`created_at`. Added:

| Column | Type | Notes |
| --- | --- | --- |
| `role` | str(20) | `admin` or `customer`, not null |
| `full_name` | str(120) | nullable |
| `phone` | str(30) | nullable |
| `is_active` | bool | not null, default true — drives "disable account" (§19) |
| `reset_requested_at` | datetime | nullable — set by the forgot-password page |
| `must_change_password` | bool | not null, default false — set when an admin issues a temporary password |

`email` becomes not-null. Every account now arrives through `/signup` or the
seed, both of which supply one; the old nullable case only existed for accounts
made by `create-admin` before sign-up existed, and `reset-db` clears those.

### vehicles

Renames, so the column names match the requirements: `make` → `brand`,
`remarks` → `description`. Added:

| Column | Type | Notes |
| --- | --- | --- |
| `seats` | int | not null, default 5 |
| `transmission` | str(20) | `Automatic` or `Manual`, not null |
| `fuel_type` | str(20) | `Gasoline`, `Diesel`, `Electric`, `Hybrid`, not null |
| `daily_rate` | Numeric(10,2) | not null |
| `hourly_rate` | Numeric(10,2) | nullable — null means daily-only |
| `image_url` | str(500) | nullable |
| `is_active` | bool | not null, default true |

Statuses become `AVAILABLE`, `RESERVED`, `RENTED`, `MAINTENANCE`. The old
`Retired` status is not carried over; retiring a vehicle is `is_active = false`,
which is what §16's "Disable Vehicle" asks for and keeps the four statuses
meaning exactly what §9 says they mean.

`vehicle_type` gains `Hatchback` and `MPV`, giving: Sedan, Hatchback, MPV, SUV,
Pickup, Van, Truck, Motorcycle.

### rental_rates

One row, id 1. `RentalRates.current(session)` returns it, creating it with the
defaults below if the table is empty, so no code path has to handle its absence.

| Column | Type | Seeded |
| --- | --- | --- |
| `additional_driver_fee_per_day` | Numeric(10,2) | ₱500 |
| `insurance_fee_per_day` | Numeric(10,2) | ₱300 |
| `late_fee_per_day` | Numeric(10,2) | ₱800 |
| `updated_at` | datetime | |

Nothing in the frontend hardcodes a fee (§21). Templates read these values.

### reservations

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int | pk |
| `reservation_number` | str(20) | unique, `RES-00001` |
| `user_id` | int | fk users |
| `vehicle_id` | int | fk vehicles |
| `pickup_at` | datetime | not null |
| `return_at` | datetime | not null |
| `pickup_location` | str(120) | |
| `return_location` | str(120) | |
| `want_additional_driver` | bool | default false |
| `want_insurance` | bool | default false |
| `rental_hours` | int | computed duration |
| `rental_days` | int | whole days, for display |
| `daily_rate` | Numeric(10,2) | snapshot |
| `hourly_rate` | Numeric(10,2) | snapshot, nullable |
| `base_amount` | Numeric(10,2) | |
| `additional_fees` | Numeric(10,2) | |
| `total_amount` | Numeric(10,2) | |
| `status` | str(20) | `PENDING`, `CONFIRMED`, `CANCELLED`, `COMPLETED`, `REJECTED` |
| `created_at` / `updated_at` | datetime | |

Two deliberate deviations from §28:

- **One datetime per endpoint, not a date and a time column.** Overlap
  comparison is the single most important query in the system and it wants a
  comparable value. Forms still collect date and time separately and the UI
  still displays them separately; only storage differs.
- **Rates are snapshotted onto the reservation.** If an admin changes a
  vehicle's daily rate, an existing reservation's price must not silently
  change underneath the customer.

`reservation_number` is allocated as `RES-%05d` from the row id immediately
after the insert flushes, inside the same transaction, so it cannot collide.

### rentals

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int | pk |
| `rental_number` | str(20) | unique, `RNT-00001` |
| `reservation_id` | int | fk, unique — one rental per reservation |
| `vehicle_id` / `customer_id` | int | fk, denormalised for reporting. `customer_id` here and `user_id` on reservations both point at `users`; the asymmetry is §28's and is kept so the column names match the requirements |
| `actual_pickup` | datetime | not null |
| `expected_return` | datetime | not null |
| `actual_return` | datetime | nullable until returned |
| `rental_hours` / `rental_days` | int | |
| `late_hours` | int | default 0 |
| `base_amount` / `late_fee` / `additional_fees` / `total_amount` | Numeric(10,2) | |
| `status` | str(20) | `ACTIVE`, `COMPLETED` |
| `created_at` / `updated_at` | datetime | |

### maintenance

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int | pk |
| `vehicle_id` | int | fk vehicles |
| `description` | text | not null |
| `start_date` / `expected_end_date` | date | not null |
| `actual_end_date` | date | nullable |
| `status` | str(20) | `SCHEDULED`, `IN_PROGRESS`, `COMPLETED` |
| `cost` | Numeric(10,2) | nullable |
| `created_at` | datetime | |

A row whose status is not `COMPLETED` blocks booking across its window. A
completed one blocks nothing.

## Roles

```python
def current_user() -> User | None    # from session["user_id"], cached on g
def current_role() -> str | None     # "admin" | "customer" | None
```

Three decorators, replacing `viewer_required` / `editor_required`:

- `login_required` — any signed-in account; anonymous visitors are redirected to
  login with `?next=`.
- `admin_required` — `role == "admin"`, otherwise 403.
- `customer_required` — `role == "customer"`, otherwise 403. An admin browsing
  `/my/reservations` gets a 403, because those pages are scoped to the signed-in
  customer's own rows and an admin has none.

Public pages carry no decorator at all.

**Guest mode is retired.** `POST /guest` and the `session["guest"]` flag are
removed, along with `tests/test_guest.py`. Guest mode existed to let someone look
around without an account; the storefront now does that properly and publicly. An
existing guest session cookie has no `user_id`, so it simply reads as anonymous —
which now sees the public pages rather than a login wall.

Existing accounts become `role = "admin"`: they were the fleet staff. `/signup`
creates customers only; there is no way to create an admin through the web UI
(§29), only `flask create-admin`.

## Routes

| Route | Guard | Notes |
| --- | --- | --- |
| `GET /` | public | Landing page (§25) |
| `GET /vehicles` | public | Browse grid, 12 per page; filters: type, transmission, minimum seats, and a min/max `daily_rate` range |
| `GET /vehicles/<id>` | public | Detail page. No booking widget yet — phase 3. A vehicle with `is_active = false` is 404 here for a visitor or customer, and visible to an admin |
| `GET POST /login` | public | Redirects admin → `/admin`, customer → `/my` |
| `GET POST /signup` | public | Creates a customer |
| `POST /logout` | login_required | |
| `GET POST /forgot-password` | public | Records `reset_requested_at` |
| `GET POST /change-password` | login_required | Forced when `must_change_password` |
| `GET /my` | customer_required | Four stat cards, real counts |
| `GET /admin` | admin_required | Rental Management Dashboard |
| `GET /admin/vehicles` | admin_required | Table, sortable, paginated |
| `GET POST /admin/vehicles/add` | admin_required | |
| `GET /admin/vehicles/<id>` | admin_required | |
| `GET POST /admin/vehicles/<id>/edit` | admin_required | |
| `GET POST /admin/vehicles/<id>/delete` | admin_required | Confirmation page, then POST |
| `POST /admin/vehicles/<id>/toggle-active` | admin_required | Disable / re-enable |
| `GET POST /admin/rates` | admin_required | Rental Rates form |

Public browse and vehicle detail are in phase 1 rather than phase 3 so that the
landing page's **Browse Vehicles** button works the day it ships. §33 forbids
buttons that do nothing, and that applies between phases too.

When `must_change_password` is set, a `before_request` hook redirects every
request to the change-password page, exempting `/change-password`, `/logout` and
the `static` endpoint — without the static exemption the page would load with no
stylesheet.

## Dashboards

Every number is a real query. Reservation and rental counts are legitimately
zero in phase 1 because nothing can create one yet; the queries are the final
ones and start reporting as soon as phase 3 lands.

**`/admin` — Rental Management Dashboard.** Fleet cards: total vehicles,
available, reserved, currently rented, under maintenance — one `GROUP BY` over
`status` plus a total, as `dashboard()` does today. Operations cards: pending
reservations, today's pickups, today's returns, total rental revenue
(`SUM(total_amount)` over completed rentals).

**`/my` — My Rental Dashboard.** "Welcome, {full_name or username}". Cards:
available vehicles, my reservations, active rental, total rentals. A **Browse
Vehicles** call to action. The Find a Vehicle date search arrives in phase 3.

## Vehicle images

`image_url` holds either an absolute URL or a path under `static/`. The admin
vehicle form accepts one; there is no upload, because Vercel's filesystem is
read-only and an upload service is a dependency the demo does not need.

When `image_url` is blank, the vehicle renders a per-type SVG silhouette from
`static/img/types/{sedan,hatchback,mpv,suv,pickup,van,truck,motorcycle}.svg`.
These are committed, so they work offline and never 404, and they read as a
deliberate illustration rather than a broken image. Dropping real photographs
into `static/img/vehicles/` and pointing `image_url` at them is a later,
optional improvement that needs no code change.

## Templates

`base.html` keeps the head, the body, the flash rendering and the error pages.
Two layouts extend it:

- `layout_public.html` — a top navigation bar for the landing page, the browse
  grid, the vehicle detail page and the customer portal. Links: Home, Browse
  Vehicles, then either Log in / Create account, or My Reservations, My Rentals,
  Profile, Log out. Collapses to a `<details>` drop-down on small screens, the
  same no-JavaScript pattern the current top bar uses.
- `layout_admin.html` — the existing fixed sidebar, restructured to the grouped
  navigation in §15. Phase 1 renders only the sections it has built; the rest
  appear as their phases land, because a sidebar link to a page that does not
  exist is exactly the dead button §33 rules out.

The existing `card`, `btn`, `pill`, `field`, `data-table` and `alert` component
classes in `static/src/input.css` are kept and extended with a `vehicle-card`
and a rental-status pill palette. The five reservation statuses and two rental
statuses get badge colours alongside the four vehicle statuses, chosen in Python
and listed in the `@source inline(...)` directive so Tailwind keeps them in the
build — the pattern already established for `STATUS_BADGES`.

## Branding

`Vehicle Inventory Management System` → `Vehicle Rental and Reservation System`,
tagline "Online reservation + vehicle availability + automatic rental
calculation". The login page reads "Book your vehicle online with ease." and
offers Log in, Create Account, Browse Vehicles and Forgot Password.

The package renames from `inventory` to `rental`, which touches `app.py`,
`pyproject.toml` (project name, `pythonpath`), `.vercelignore`, the default
SQLite URL (`inventory.db` → `rental.db`) and every import. Mechanical, and
cheapest in phase 1 before the file count grows. A `grep -ri inventor` sweep
closes the phase, and the README is rewritten.

## Seed

`flask reset-db` — drop, create, seed. `--password` supplies the admin password
non-interactively, otherwise it prompts. `--demo-password` sets the shared
password for the sample customers and defaults to prompting; the command prints
the accounts it created so a demo can sign in.

Seeded: one admin; three customers with names and phone numbers; the
`rental_rates` row; ten vehicles including the four named in §38 — Toyota Vios
sedan ₱1,500, Mitsubishi Mirage hatchback ₱1,300, Toyota Innova MPV ₱2,500,
Toyota HiAce van manual 12 seats ₱3,500 — and one maintenance record — whose vehicle is seeded with status
`MAINTENANCE`, so the seeded state is self-consistent with the bookability rule.

Reservations and rentals are **not** seeded in phase 1. Their amounts must come
from `domain/pricing.py`, which phase 2 builds; writing precomputed totals by
hand now would be the one place in the system where a price was hardcoded.
Phase 3 extends the seed to create them through the real code path.

`flask init-db` is kept unchanged. `flask seed` is kept as a command but its
sample rows are rewritten: the existing ones have no `daily_rate`, `seats`,
`transmission` or `fuel_type` and would no longer insert. `reset-db` is the
destructive superset — drop, create, then the same seed routine — and it refuses
to run without `--yes` when `DATABASE_URL` points at anything other than SQLite.

`flask create-admin`'s `--email` becomes required rather than optional, since
`users.email` is now not-null.

## Testing

`conftest.py` gains `client` (anonymous), `customer_client` and `admin_client`
fixtures, replacing `guest_client`.

| File | Covers |
| --- | --- |
| `test_roles.py` | Every phase-1 route × anonymous / customer / admin. Public pages reachable anonymously; admin pages 403 for a customer; `/my` 403 for an admin; anonymous redirected to login with `?next=` |
| `test_auth.py` | Sign-up creates `role="customer"`; login redirects by role; forgot-password records `reset_requested_at`; `must_change_password` forces the redirect and clears on change; a disabled account cannot sign in |
| `test_models.py` | `RentalRates.current` creates and then reuses the single row; vehicle defaults; badge mapping covers every status |
| `test_fleet.py` | Adapted from `test_vehicles.py`: CRUD with the new required fields, duplicate plate, year bounds, `daily_rate` validation, toggle-active |
| `test_public.py` | Landing, browse and detail render anonymously; browse filters by type, transmission, seats and price; a disabled vehicle is absent from browse but still reachable by id for an admin |
| `test_cli.py` | `reset-db` produces a schema the app can serve and refuses a non-SQLite URL without `--yes` |

`test_guest.py` is deleted; its anonymous-redirect assertions move into
`test_roles.py`.

## Out of scope for phase 1

Creating a reservation, checking availability, calculating a price, the rental
lifecycle, the maintenance UI, the customers admin page, every report, revenue,
and CSV export. Those are phases 2–4. The tables and the rates they need exist
after phase 1, but nothing writes to them yet.

---

# Phases 2–4, outlined

Each gets its own spec before it is built.

## Phase 2 — Domain core

`domain/pricing.py` — duration in hours, days for display, `base_amount`,
`additional_fees`, `late_fee`, `total_amount`. Pure `Decimal` arithmetic.

`domain/availability.py` — the overlap predicate, a function turning a vehicle's
reservations, rentals and maintenance windows into a list of blocked intervals,
and the reasons a vehicle is unbookable regardless of dates (inactive, under
maintenance).

`domain/lifecycle.py` — the legal transitions and their guards:

```text
reservation:  PENDING → CONFIRMED | REJECTED | CANCELLED
              CONFIRMED → CANCELLED | (rental starts) → COMPLETED
rental:       ACTIVE → COMPLETED
vehicle:      AVAILABLE ⇄ RESERVED ⇄ RENTED,  any ⇄ MAINTENANCE
```

Returning a vehicle completes the rental, completes the reservation, sets the
vehicle to `AVAILABLE`, records `actual_return`, and recalculates the total with
any late fee (§18, §22).

Built test-first. No routes, no templates, no UI.

## Phase 3 — Customer surface

Date-aware search, the vehicle detail booking widget with its server-rendered
availability check and its small vanilla-JS live price preview, the reservation
review and confirm step, My Reservations, reservation detail, cancel, My
Rentals, the profile page, and the empty states and notifications from §36–37.

## Phase 4 — Admin console and reports

Reservation management with confirm / reject / cancel, active rentals with mark-
as-returned, the availability view, maintenance CRUD wired to bookability, the
customers page with the admin-assisted password reset, revenue,
the three reports with Today / This week / This month / Custom date filters and
CSV export, the full grouped sidebar, a responsive pass, and an end-to-end test
of §32's demo scenario.

## Not being built at all

No payment gateway — reservation detail shows "Payment Status: Pending" and the
system does not pretend otherwise (§13). No email: the forgot-password flow
records a request an admin services by issuing a temporary password. No weekly
rate tier. No file upload. No locations table — pickup and return locations are
a fixed list of branch names stored as text on the reservation.
