# Vehicle Rental and Reservation System

A web application for booking and managing a rental fleet, written as a
Python final project and built in phases. This is **phase 1**: the schema,
roles, the public storefront a visitor can browse, and an admin fleet console
— everything needed to stock a fleet and show it off, with the booking flow
itself arriving in a later phase. It is a classic server-rendered Flask app:
every page is a normal HTML page, there is no JavaScript framework, and the
only JavaScript in the whole project is the one-line `window.print()` on the
Reports page.

**Stack:** Python 3.12 · Flask · Jinja2 · SQLAlchemy 2.x · psycopg 3 ·
Flask-WTF · Tailwind CSS v4 · Neon Postgres (SQLite locally) ·
deployed on Vercel.

## Features

| Page | What it does |
|---|---|
| **Landing page** | The storefront's front door: the pitch, feature cards, and up to three real, currently-available vehicles ordered by price. |
| **Browse Vehicles** | The full grid of active vehicles, filterable by type, transmission, seat count and daily-rate range. Filters are plain `GET` parameters, so a filtered grid can be bookmarked and shared. |
| **Vehicle Detail** | One vehicle's public page: specs, description and rates. A vehicle with no photo shows its type silhouette instead of a broken image. A disabled vehicle 404s here for a visitor. |
| **Sign up / Log in** | Session-based sign in. New accounts are created as `customer` and signed in immediately. Passwords are stored as `werkzeug.security` hashes, never in plain text. A disabled account cannot sign in, and an account carrying a temporary password is held on the change-password page until it sets a new one. |
| **Password reset request** | No email is sent: a customer flags their account for a reset, and an admin issues a temporary password by hand. |
| **My Rental Dashboard** (`/my`) | A signed-in customer's own summary: vehicles currently available, their pending reservations, their active rental, and their rental history — every figure scoped to that customer. |
| **Rental Management Dashboard** (`/admin`) | Fleet counts by status, today's pickups and returns, pending reservations, total revenue, and quick links to every admin function. |
| **Fleet Management** (`/admin/vehicles`) | Add, edit, disable/re-enable and delete a vehicle, plus a dedicated search across plate number, brand and model with status and type filters. A duplicate plate number gives a friendly message on the field instead of a database error. Disabling keeps a vehicle's record and history while pulling it off the storefront. |
| **Rental Rates** (`/admin/rates`) | The system-wide fee schedule — additional driver, insurance and late-return fees, all per day. Nothing in a template hardcodes a fee; every page reads these values, including a legitimate zero. |
| **Fleet Reports** (`/admin/reports`) | Counts by status, by vehicle type and by year acquired, a print-friendly stylesheet with a Print button, and a CSV export of every vehicle. |

Flash messages confirm every action, and there are custom 403, 404 and 500 pages.

### Roles

Two roles, `admin` and `customer`, stored on the `User` row (no separate roles
table, no guest mode). `auth.current_role()` reads the role off the
signed-in user. Three decorators guard every other page:

- `login_required` — any signed-in account; anonymous visitors are redirected
  to the login page with `?next=`.
- `admin_required` — admins only; a customer gets a 403.
- `customer_required` — customers only; an admin gets a 403, because these
  pages show "your" reservations and rentals, and an admin has none.

Templates get `current_role`, `is_admin` and `is_customer` from the context
processor and use them to hide the actions the other role cannot take.

## Data model

Six tables. Money is stored as `Numeric(10, 2)` and handled as `decimal.Decimal`.
The one place a float appears is parsing the browse filter's rate bounds
(`min_rate`/`max_rate`) from the query string; they are immediately converted
with `Decimal(str(...))` before any comparison against a stored rate.

**users** — `id`, `username` (unique), `email` (unique, not null),
`password_hash`, `role` (`admin` or `customer`), `full_name`, `phone`,
`is_active` (drives "disable account"), `reset_requested_at` (set by the
forgot-password page), `must_change_password` (set when an admin issues a
temporary password), `created_at`.

**vehicles**

| Field | Type | Notes |
|---|---|---|
| `id` | int | primary key |
| `plate_number` | str | required, unique, stored trimmed and upper-cased |
| `brand` | str | required, e.g. Toyota |
| `model` | str | required, e.g. Vios |
| `year` | int | required, 1950 to next year |
| `vehicle_type` | str | Sedan, Hatchback, MPV, SUV, Pickup, Van, Truck, Motorcycle |
| `color` | str | optional |
| `status` | str | AVAILABLE, RESERVED, RENTED, MAINTENANCE — the vehicle's state right now, not the same thing as its future availability |
| `seats` | int | required, default 5 |
| `transmission` | str | Automatic or Manual |
| `fuel_type` | str | Gasoline, Diesel, Electric, Hybrid |
| `daily_rate` | Numeric(10,2) | required |
| `hourly_rate` | Numeric(10,2) | optional — null means daily-only, a part day rounds up |
| `image_url` | str | optional — blank falls back to the per-type silhouette |
| `is_active` | bool | default true — false is what "Disable Vehicle" does |
| `date_acquired` | date | optional |
| `description` | text | optional |
| `created_at` / `updated_at` | datetime | set automatically |

**rental_rates** — exactly one row, id 1: `additional_driver_fee_per_day`,
`insurance_fee_per_day`, `late_fee_per_day` (all Numeric(10,2)), `updated_at`.
`RentalRates.current(session)` returns it, creating it with defaults if the
table is empty, so no page has to handle its absence.

**reservations** — a customer's request to rent one vehicle over one date
range: `id`, `reservation_number` (`RES-00001`), `user_id`, `vehicle_id`,
`pickup_at` / `return_at` (one datetime per endpoint, so overlap comparison
has a single comparable value), `pickup_location` / `return_location`,
`want_additional_driver` / `want_insurance`, `rental_hours` / `rental_days`,
a snapshot of `daily_rate` / `hourly_rate` at booking time (so a later rate
change never alters an existing quote), `base_amount` / `additional_fees` /
`total_amount`, `status` (PENDING, CONFIRMED, CANCELLED, COMPLETED,
REJECTED), `created_at` / `updated_at`.

**rentals** — a confirmed reservation that has actually been picked up:
`id`, `rental_number` (`RNT-00001`), `reservation_id` (unique — one rental
per reservation), `vehicle_id` / `customer_id` (denormalised for reporting),
`actual_pickup` / `expected_return` / `actual_return`, `rental_hours` /
`rental_days` / `late_hours`, `base_amount` / `late_fee` / `additional_fees`
/ `total_amount`, `status` (ACTIVE, COMPLETED), `created_at` / `updated_at`.

**maintenance** — a window during which a vehicle is off the road: `id`,
`vehicle_id`, `description`, `start_date` / `expected_end_date` /
`actual_end_date`, `status` (SCHEDULED, IN_PROGRESS, COMPLETED), `cost`,
`created_at`. A row whose status is not `COMPLETED` blocks booking across
its window; a completed one blocks nothing.

Reservations, rentals, and the tables above them that reference future
booking (pending reservations, active rentals, today's pickups/returns) are
in the schema now so phase 1's dashboards can report real, if currently
empty, figures — the booking flow that populates them is phase 3.

## The domain core (phase 2)

`rental/domain/` holds three pure, framework-free modules built in phase 2:
`pricing.py` (quoting a rental, itemised, and late fees), `availability.py`
(whether a vehicle is bookable over a date range, from plain intervals) and
`lifecycle.py` (which reservation/rental/vehicle status changes are legal,
and what each business action changes). Nothing in `rental/domain/` imports
Flask, SQLAlchemy or `rental.models` — stdlib only — so every rule is tested
without a database or an app context. `scripts/check-domain-purity.py`
enforces that boundary by importing the domain modules in isolation and
failing if anything framework-shaped leaks in; it runs as part of the test
suite (`tests/test_domain_purity.py`), not just by hand. `rental/clock.py` is
the single source of "now" and "today" — a naive Philippine-time value read
the same way whether the server itself runs in Manila or in UTC — replacing
three clocks phase 1 left inconsistent. Phase 2 ships no way to create a
reservation; that arrives with the booking flow in phase 3.

## The booking flow (phase 3)

Everything from browsing with dates through a completed, possibly late,
rental, built on the phase 2 domain core. `rental/scheduling.py` is where the
ORM meets the domain: it loads a vehicle's other reservations, turns them
into the plain `Interval` values `rental/domain/availability.py` works with,
and calls `quote()` for pricing. Neither `rental/booking.py` nor
`rental/public.py` touches the domain directly — they go through
`scheduling`.

- **Browse and detail, date-aware** (`GET /vehicles`, `GET /vehicles/<id>`) —
  add `pickup`/`return` (and `insurance`) to either page's query string and
  every card, and the detail page's own price, is computed from that window
  server-side, with no JavaScript required. `GET /api/quote` returns the same
  quote as JSON, public and session-free, for the live preview that updates
  the price without a page reload; the page works identically with
  JavaScript disabled.
- **Reserve** (`POST /book/<id>`, `GET /book/<id>/review`,
  `POST /book/<id>/confirm`) — a logged-out visitor who picks dates and hits
  Book is sent to log in with `next` pointing at their review page, so the
  dates they chose survive the round trip. Confirming locks the vehicle's
  row, re-checks the window is still free inside that same transaction, and
  only then creates the `Reservation`, snapshotting its rates and assigning
  its `RES-00001`-style number so a later rate change never alters an
  existing quote.
- **My Reservations / My Rentals** (`/my/reservations`, `/my/rentals`, and
  each one's detail page, plus cancel-before-pickup on a reservation) — a
  customer's own bookings, present and past, with a 404 rather than a 403
  for one that belongs to someone else.
- **The three admin actions** on a reservation and its rental: confirm or
  reject a pending reservation (`POST /admin/reservations/<id>/confirm`,
  `.../reject`), start it as an active rental at pickup
  (`POST /admin/reservations/<id>/start`), and mark the rental returned
  (`POST /admin/rentals/<id>/return`), which charges `late_charge()` as its
  own line when the vehicle comes back late and frees the vehicle for its
  next booking. An illegal transition, such as starting a reservation twice,
  flashes a message instead of raising.
- **Profile** (`/my/profile`) — a customer's own account details.

Payments and email stay out of this phase: every reservation and rental
shows "Payment Status: Pending" and nothing here sends mail. Editing a
booking's dates and admin-side booking on a customer's behalf are also
absent. Phase 4 keeps the rental management dashboard, the availability
view, maintenance, the customers page, revenue, and the reporting suite.

## Getting started

Requires [uv](https://docs.astral.sh/uv/). With no `DATABASE_URL` set the app
uses a local SQLite file (`rental.db`), so you can run it with no database to
install.

```bash
uv sync
DATABASE_URL=sqlite:///rental.db uv run flask reset-db --password 'choose-one' --demo-password 'choose-one'
uv run flask run
```

`flask reset-db` drops every table, recreates them, and seeds a demo fleet of
ten vehicles, an admin account and three sample customers. It refuses to run
against anything other than local SQLite unless you pass `--yes`, so pointing
it at a remote database takes a deliberate extra step.

Pin `DATABASE_URL` on the command as shown rather than relying on whatever is
in your environment. `python-dotenv` searches upward for a `.env`, so a stray
or inherited one can silently point this command at a real database — and
`--yes` is exactly what would let it through. If the command complains it
cannot find a database, set `DATABASE_URL`; never add `--yes` to make the
error go away.

## Local setup

The three underlying CLI commands are ordinary Flask CLI commands, useful
when you want more control than `reset-db` gives you:

```bash
cp .env.example .env                    # then edit SECRET_KEY

uv run flask --app app init-db          # create the tables
uv run flask --app app create-admin     # prompts for username, email and password
uv run flask --app app seed             # insert the demo fleet, accounts and fee schedule

uv run flask --app app run              # http://127.0.0.1:5000
```

Tables are deliberately **never** created when the app starts up, because on
a serverless host the app is imported on every cold start. To set up the
production database, run the same commands locally with `DATABASE_URL`
pointing at Neon.

## CSS

Tailwind is used through the **standalone Tailwind CLI**, so Node and npm are
not needed anywhere. The CLI comes from the `pytailwindcss` dev dependency.

There is no component library. The interface is built from plain Tailwind
utilities plus a small set of project classes (`.card`, `.btn`, `.pill`,
`.field`, `.data-table`, `.nav-link`) defined in `input.css`.

```bash
# while working on templates
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --watch

# before committing
uv run tailwindcss -i rental/static/src/input.css -o rental/static/css/output.css --minify
```

`rental/static/css/output.css` is **committed to Git** on purpose: Vercel
then needs no build step at all, it just serves the file.

The palette, fonts and component classes all live in
`rental/static/src/input.css`: a dark navy sidebar, a light content area,
blue primary actions, and status pill colours kept far apart in hue so they
stay easy to tell apart, including when printed.

The first `tailwindcss` run downloads the CLI binary. If that fails with an SSL
certificate error, point Python at your system CA bundle:

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt uv run tailwindcss ...
```

## The login photograph

`rental/static/img/login-car.{webp,jpg}` is a photo by
[Olav Tvedt](https://unsplash.com/@olavtvedt) from
[Unsplash](https://unsplash.com/photos/-oVaYMgBMbs), used under the
[Unsplash License](https://unsplash.com/license) (free to use, no attribution
required — credited here anyway).

The 4000x6000, 3.1 MB original was optimised with ImageMagick down to
1200x1800:

```bash
magick original.jpg -auto-orient -resize 1200x1800^ -strip \
  -interlace Plane -sampling-factor 4:2:0 -quality 80 \
  rental/static/img/login-car.jpg

magick original.jpg -auto-orient -resize 1200x1800^ -strip \
  -quality 76 -define webp:method=6 \
  rental/static/img/login-car.webp
```

That gives a 52 KB WebP with a 139 KB JPEG fallback — 98% smaller than the
original. The page uses a `<picture>` element so browsers pick whichever they
support.

## Tests

```bash
uv run pytest
```

Run against an in-memory SQLite database and cover login and signup, the
role decorators and their 403s, browsing and filtering the storefront, the
vehicle detail page, adding/editing/disabling/deleting a fleet vehicle
(including the duplicate-plate and year-range errors), the admin and
customer dashboards, rental rates, search, and the reports page and CSV
export.

## Deploying to Vercel (Hobby tier)

1. Create a Postgres database at [neon.tech](https://neon.tech) and copy the
   **pooled** connection string (its host contains `-pooler`).
2. Push this repository to GitHub and import it at
   [vercel.com/new](https://vercel.com/new). No build command or framework
   preset is needed: Vercel finds the `app` object in the top-level `app.py`.
3. Add two environment variables in the Vercel project settings:
   - `DATABASE_URL` — the pooled Neon connection string
   - `SECRET_KEY` — a long random string
4. Deploy.
5. Create the tables and the first account by running the CLI commands from
   your own machine with `DATABASE_URL` set to the same Neon URL:

   ```bash
   DATABASE_URL='postgresql://...-pooler.../neondb?sslmode=require' \
     uv run flask --app app init-db
   ```

`requirements.txt` is generated with
`uv export --no-hashes --no-dev > requirements.txt` and committed as a fallback
for hosts that do not read `uv.lock`.

Step 3 is the one that bites, in two ways.

If `DATABASE_URL` is missing, the deployment still builds and still boots, and
the symptom is oddly specific: the landing page, the browse grid and every
vehicle detail page return 500, while the login, sign-up and forgot-password
pages render perfectly. The pages that work are the ones that never run a
query. The app now refuses to start rather than inventing an empty SQLite
file, so the logs name the cause instead of reporting
`no such table: vehicles`.

And setting the variable is not enough on its own. Vercel resolves environment
variables when a deployment is **created**, so a deployment built before the
variable existed never sees it however the dashboard looks afterwards —
**redeploy after adding it**. Variables are also scoped per environment: one
ticked for Development but not Production leaves production behaving exactly
as if it were unset.

### Why the database is configured the way it is

`rental/db.py` normalises `postgres://` and `postgresql://` URLs to
`postgresql+psycopg://` so the psycopg 3 driver is used, and builds the engine
with `poolclass=NullPool` and `pool_pre_ping=True`. Serverless functions are
short-lived and must not hold connections open between requests, and
`pool_pre_ping` throws away a connection Neon has already closed instead of
raising an error on the next query.

## Project layout

```
app.py                       entry point: exposes `app` for Vercel
rental/
  __init__.py                app factory, config, blueprints, error pages
  clock.py                   the single source of "now" and "today" (Philippine time, naive)
  db.py                      engine, sessions, get_database_url()
  models.py                  User, Vehicle, RentalRates, Reservation, Rental, Maintenance
  forms.py                   Login/Signup/Vehicle/Rates/password forms
  auth.py                    signup, login, logout, password reset, the role decorators
  public.py                  landing, browse, vehicle detail
  portal.py                  the customer's own dashboard (/my)
  admin/
    dashboard.py               the Rental Management Dashboard
    fleet.py                   vehicle CRUD, disable/re-enable, search
    rates.py                   the rental rates form
  reports.py                  fleet reports page and CSV export
  cli.py                     init-db, create-admin, seed, reset-db
  domain/                    pure, framework-free rules (phase 2): pricing.py,
                              availability.py, lifecycle.py — stdlib only, no
                              Flask/SQLAlchemy/rental.models
  templates/                 base.html, layout_public.html, layout_admin.html,
                              public/, customer/, admin/, auth/, partials/
  static/
    src/input.css            Tailwind source: theme tokens + component classes
    css/output.css           built and committed
scripts/
  check-domain-purity.py     fails if rental/domain/ imports anything but the standard library
tests/                       pytest suite (in-memory SQLite)
```

## Roadmap

This is phase 1 of four. Booking is deliberately absent here, not broken:

- **Phase 2 — Domain core.** Pure, test-first modules for pricing, date-overlap
  availability and the lifecycle transitions reservations, rentals and
  vehicles move through. No routes, no templates.
- **Phase 3 — Customer surface.** Date-aware search, the vehicle detail
  booking widget, reserve/cancel, My Reservations, My Rentals, and the
  customer profile page.
- **Phase 4 — Admin console and reports.** Reservation management (confirm /
  reject / cancel), active rentals with mark-as-returned, the availability
  view, maintenance CRUD, the customers page with admin-assisted password
  resets, revenue, and the full reporting suite with date filters.
