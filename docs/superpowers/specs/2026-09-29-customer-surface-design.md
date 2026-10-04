# Phase 3 — The Customer Surface

**Status:** approved
**Precedes:** phase 4 (admin console, reports, CSV)
**Builds on:** `docs/superpowers/specs/2026-09-29-rental-domain-core-design.md`

## What this phase is for

Phases 1 and 2 built a rental system that cannot take a booking. The schema has
carried `Reservation` and `Rental` since phase 1, the dashboards count them, and
the counts are honestly zero. Phase 2 worked out what a rental costs, whether a
vehicle is free, and which state follows which — against unit tests, with no UI
in the way.

This phase connects the two. At the end of it a customer can find a vehicle for
their dates, see what it will cost, book it, and watch it through to a completed
rental; and an admin can confirm the booking, hand over the keys, and take the
vehicle back.

## Scope

| Half | Ships |
| --- | --- |
| Customer | Date-aware search, the booking widget and its live price preview, review and confirm, My Reservations, reservation detail, cancel, My Rentals, rental detail, the profile page, empty states |
| Admin | The reservation queue with confirm and reject, starting a rental at pickup, marking a rental returned with its late fee |

The admin half is pulled forward from phase 4 deliberately. Without it nothing
can create a `Rental`, so My Rentals would ship as a permanently empty page and
the late-fee logic — the most intricate thing phase 2 built — would go
undemonstrated until phase 4. Three admin actions close the loop.

Phase 4 keeps the rental management dashboard, the availability view,
maintenance, the customers page, revenue, and the three reports with CSV export.

### Not in this phase

No payments: reservation detail shows "Payment Status: Pending" and the system
does not pretend otherwise. No email: confirmation is a flash message and the
reservation appearing in My Reservations. No editing a booking's dates — cancel
and rebook. No admin-side creation of a reservation on a customer's behalf.

## Decisions taken

| Question | Decision |
| --- | --- |
| Logged-out visitor picks dates and hits Book | Show the widget and the real price to everyone; Book redirects to login carrying the dates, and returns to the same vehicle with them intact |
| What the browse grid shows once a vehicle has a future booking | With no dates chosen, every bookable vehicle reads as available and the status badge is informational. With dates chosen, each card answers for *those* dates |
| When a customer may cancel | Any time before `pickup_at`, whether PENDING or CONFIRMED. After pickup the button is gone and the page says to contact the office |
| Whether a PENDING reservation blocks others | Yes. First request holds the slot. PENDING, CONFIRMED and ACTIVE all block |

The last one is the reason this phase needs a locking strategy rather than a
hopeful re-read; see **Integrity**.

## Architecture

### The new boundary: `rental/scheduling.py`

`rental/domain/` takes plain values and returns plain values, and imports
neither Flask nor SQLAlchemy. Something must turn rows into those values.
Phase 2's final review was explicit that it must not be the domain package.

```text
rental/scheduling.py

  blocked_intervals(db, vehicle, *, exclude_reservation_id=None)
      -> list[Interval]
      Every PENDING or CONFIRMED reservation and every ACTIVE rental for this
      vehicle, as half-open intervals.

  current_rates(db) -> Rates
      The single RentalRates row as the domain's plain-value Rates.

  availability_for(db, vehicle, interval) -> Availability
      blocked_intervals + vehicle.is_active + vehicle.status -> domain check().

  quote_for(db, vehicle, interval, *, want_additional_driver, want_insurance)
      -> Quote
      current_rates + the vehicle's own rates -> domain quote().
```

Routes never import `rental.domain` directly. They call `scheduling`. This is
what satisfies the original requirement that validation happen on both the
front end and the back end: the live preview, the review page, and the commit
are three callers of one function, not three implementations that drift.

`scheduling.py` may import models and a session. It must not import Flask,
`request`, or `session` — it takes a `db` and plain arguments, so it can be
tested without an app context.

### Route modules

Following the existing package layout:

```text
rental/booking.py             pick dates, review, confirm, cancel   (customer)
rental/portal.py              extended: reservations, rentals, profile
rental/admin/reservations.py  the confirm / reject queue
rental/admin/rentals.py       start a rental, mark it returned
```

Templates live under `rental/templates/booking/` and `rental/templates/customer/`.
**Not** under a directory named `public`, which Vercel strips from the function
bundle; `tests/test_template_layout.py` enforces this.

## Routes

```text
GET  /vehicles/<id>?pickup=&return=&driver=&insurance=
         Detail page. With dates, a server-rendered verdict and itemised quote.
GET  /vehicles?pickup=&return=&…
         Browse grid, each card answering for those dates.
GET  /api/quote?vehicle=&pickup=&return=&driver=&insurance=
         JSON {available, reason, message, total, lines} for the live preview.
POST /book/<vehicle_id>            validate dates -> redirect to review
GET  /book/<vehicle_id>/review     itemised quote and the confirm button
POST /book/<vehicle_id>/confirm    creates the PENDING reservation
GET  /my/reservations
GET  /my/reservations/<id>
POST /my/reservations/<id>/cancel
GET  /my/rentals
GET  /my/rentals/<id>
GET  /my/profile
POST /my/profile
GET  /admin/reservations
POST /admin/reservations/<id>/confirm
POST /admin/reservations/<id>/reject
POST /admin/reservations/<id>/start      hand over the keys; creates the Rental
GET  /admin/rentals
POST /admin/rentals/<id>/return          records the return; adds any late fee
```

Every POST is CSRF-protected by the existing `CSRFProtect`. Every `/my/` route
is `@customer_required`; every `/admin/` route is `@admin_required`.

### The login round trip

`POST /book/<id>` from a logged-out visitor redirects to
`/login?next=<the review URL, with its query string>`. `auth.login` already
honours `next`; this phase adds a check that `next` is a relative path, so the
parameter cannot be used to bounce someone to another site. Signing up mid-flow
lands in the same place.

## The live price preview

The preview must not reimplement pricing in JavaScript. The hourly cap, the
per-billable-day extras and the fee table are phase 2's work, tested there; a
second implementation in the browser would be wrong the first time the rates
page changed.

Instead, `GET /api/quote` returns the server's answer and roughly forty lines of
vanilla JavaScript render it — debounced on change, with the previous figure
left in place while a request is in flight.

**The page works with JavaScript disabled.** The same figures are server-rendered
on load whenever the URL carries dates, so the preview is an enhancement rather
than the only path to a price.

`/api/quote` is public — it prices published rates against a published fleet and
reveals nothing a visitor cannot get from the detail page. It takes no session
and writes nothing.

## Integrity

"First request holds the slot" is only true if two simultaneous requests cannot
both win. The availability shown on the review page is already stale when the
customer clicks Confirm.

```python
with db.begin():
    db.execute(select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update())
    if not scheduling.availability_for(db, vehicle, interval).ok:
        flash("That vehicle was just booked for those dates.", "warning")
        return redirect(...)
    db.add(Reservation(...))
```

The row lock serialises booking attempts for one vehicle. Postgres honours it;
SQLite is single-writer, so the same guarantee holds there for a different
reason. Re-checking **inside** the transaction is the load-bearing part.

The same pattern guards `start` — a vehicle cannot be handed over twice.

### The quote is a snapshot

`confirm` recomputes the quote server-side rather than trusting anything posted,
then stores `daily_rate`, `hourly_rate`, `rental_hours`, `rental_days`,
`base_amount`, `additional_fees` and `total_amount` on the reservation. A later
edit to the fee table must never silently change what someone already booked.

`reservation_number` is assigned by the existing `assign_number()`.

## The lifecycle, wired

Each admin action calls the matching phase 2 function and applies the
`StateChange` it returns — reservation, rental and vehicle move together or not
at all, inside one transaction.

| Action | Domain call | Effect |
| --- | --- | --- |
| Confirm | `confirm_reservation` | reservation CONFIRMED, vehicle RESERVED |
| Reject | `reject_reservation` | reservation REJECTED, vehicle AVAILABLE |
| Cancel | `cancel_reservation` | reservation CANCELLED, vehicle AVAILABLE |
| Start | `start_rental` | Rental ACTIVE created, vehicle RENTED; the reservation stays CONFIRMED until the vehicle is back |
| Return | `complete_rental` | rental and reservation COMPLETED, vehicle AVAILABLE |

`TransitionError` is caught at the route boundary and flashed as a message
rather than surfacing as a 500 — it means the page was stale, which is a thing
that happens to two admins working at once.

### Returning the vehicle

`mark returned` sets `actual_return` to `clock.now()`, calls
`late_charge(expected_return, actual_return, rates.late_fee_per_day)`, adds any
fee to the rental's total, and applies `complete_rental`. The late fee appears
as its own line on the rental detail page: a customer seeing a larger total than
they booked is owed the reason.

### The vehicle status caveat

`cancel` and `return` set the vehicle to AVAILABLE even when it has other future
bookings. That is correct for today's meaning of the field — the vehicle's state
*right now* — and bookability is computed from date overlap regardless, so no
booking is wrongly allowed or blocked. Phase 4's availability view is where a
richer per-date status belongs. This is recorded so a phase 4 reader does not
mistake it for an oversight.

## Empty states

Every list ships an empty state that says what to do next rather than showing a
bare heading: My Reservations offers Browse Vehicles, My Rentals explains that a
rental appears once a booking is collected, and the admin queue says the queue
is clear. These are real states, not placeholders — a new customer sees them on
their first visit.

## Testing

Three layers, plus the walkthrough.

1. **`tests/test_scheduling.py`** — the bridge, against a seeded database:
   blocked intervals include PENDING, CONFIRMED and ACTIVE but not CANCELLED,
   REJECTED or COMPLETED; `exclude_reservation_id` omits the one being
   re-examined; rates map across correctly.
2. **Route tests per flow** — including the ones that must fail: booking a
   conflicting window, cancelling after pickup has passed, a customer opening
   another customer's reservation (404, not 403 — it should not confirm the
   record exists), confirming an already-confirmed reservation, starting a
   rental twice.
3. **`tests/test_booking_journey.py`** — the demo scenario end to end: browse
   with dates, book, admin confirms, admin starts, admin returns it late, the
   customer sees the completed rental with the late fee itemised.

### Two guards proven by breaking them

As in phase 2, a guard that has never been seen to fail is not known to work:

- Remove `with_for_update()` from the confirm path and show the concurrent
  booking test goes red.
- Remove the ownership filter from `/my/reservations/<id>` and show a customer
  can read another customer's booking.

Both are restored immediately, and both transcripts go in the task report.

## Global constraints

- No new runtime dependencies. The live preview is vanilla JavaScript; no
  framework, no build step.
- `rental/domain/` stays pure, and `scripts/check-domain-purity.py` still
  passes. `scheduling.py` is where the ORM meets the domain, and it is not in
  that package.
- Money stays `Decimal` through `money()`. No float touches a price.
- Every datetime is naive local, from `rental/clock.py`.
- Tailwind is rebuilt once, at the end, with the documented
  `SSL_CERT_FILE` workaround, and `rental/static/css/output.css` is committed.
- No template may live under a directory named `public`, `static`, `api`,
  `_next` or `.well-known`.
