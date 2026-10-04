# Vehicle Rental System — Phase 2: the domain core

**Date:** 2026-09-29
**Status:** Approved
**Follows:** `2026-09-28-vehicle-rental-system-design.md` (phases 1–4 architecture, phase 1 in full)
**Scope:** phase 2 only — three pure modules and the timezone correction they rest on.

## Problem

Phase 1 built the schema, the roles, the storefront and the admin console. It
deliberately stopped short of booking: nothing can create a reservation, and the
`reservations`, `rentals` and `maintenance` tables sit empty while the dashboards
count them honestly at zero.

The rules that will fill those tables — what a rental costs, whether a vehicle can
be booked for a date range, and which status changes are legal — are the part of
this system most likely to be subtly wrong. Phase 2 builds exactly those rules, as
pure Python, with no Flask and no database, so they can be tested exhaustively
before any UI depends on them.

## Why pure modules

The overlap rule and the price calculation each have one correct answer and many
plausible near-misses. A conflict check that is off by an endpoint, or a price that
makes a 23-hour rental cost more than a 25-hour one, will pass any test written
against the happy path and will be found by a customer.

Putting them in `rental/domain/` — plain values in, plain values out — means:

- They can be tested with a table of cases and no fixtures, so the awkward cases
  are cheap to cover rather than expensive.
- The rule lives in exactly one place. Requirement 8 demands validation on both the
  frontend and the backend; that becomes two callers of one function rather than
  two implementations that drift.
- Phase 3's routes stay thin, because the thinking has already happened.

## The timezone correction

This is small, but everything in phase 2 computes durations, so it comes first.

Phase 1 left three clocks in play, which a live check confirms:

```text
utcnow() produces : 2026-09-29 00:27:58+00:00   aware UTC
created_at stored : 2026-09-29 00:27:58         tzinfo stripped -> naive UTC
pickup_at stored  : 2026-10-01 09:00            naive, meaning 9am Manila
date.today()      : 2026-09-29                  server-local, used for "today"

utcnow() - pickup_at  ->  TypeError: can't subtract offset-naive and offset-aware
```

That `TypeError` is not hypothetical: the late-fee calculation must compute
`actual_return - expected_return`, and taking "now" from `utcnow()` would raise
against a naive column. Separately, `date.today()` is the *server's* date, so
"today's pickups" is wrong for the eight hours each day when Manila and UTC differ.

**The system operates in a single timezone: Philippine time.** Customers enter
local times, admins read local times, and "today" means today in Manila. Every
datetime is stored naive and compared naive. No conversion happens anywhere.

A new `rental/clock.py` is the only place the zone is named:

```python
# The Philippines has not observed DST since 1978, so a fixed offset is exact.
# Preferred over ZoneInfo("Asia/Manila") because it needs no tz database present
# in the serverless runtime.
PH = timezone(timedelta(hours=8))


def now() -> datetime:
    """The current local time, naive, for storage and comparison."""
    return datetime.now(PH).replace(tzinfo=None)


def today() -> date:
    """The current local date. What 'today's pickups' means."""
    return now().date()
```

Relying on the server's local clock would make development (Manila) and production
(Vercel, UTC) disagree — the divergence that hides a bug until deploy.

`models.utcnow` is replaced by `clock.now`, which means every call site moves. There
are more than the obvious one:

| Site | Change | Why it matters |
| --- | --- | --- |
| `models.py` — nine column defaults | `utcnow` → `clock.now` | `created_at` / `updated_at` become naive local, consistent with `pickup_at` |
| `auth.py:204` — `reset_requested_at` | `utcnow()` → `clock.now()` | An admin reading the reset queue sees a local timestamp |
| `admin/dashboard.py:38-39` — today's window | `date.today()` → `clock.today()` | **The one that is currently wrong.** "Today's pickups" is presently the server's day |
| `cli.py:148` — seeded maintenance window | `date.today()` → `clock.today()` | Consistency; harmless either way for seed data |
| `forms.py:41` — `max_year()` | `date.today()` → `clock.today()` | Consistency; the two differ only in the hours around New Year |

Only the dashboard is a live defect. The rest move so that one module owns the
answer to "what time is it" and a future reader does not have to work out which
clock a given line meant.

**Assumption, recorded deliberately:** one timezone, one country. A second branch
abroad would need this revisited. That is a real constraint and the right trade for
a single-office business; the alternative costs a conversion at every form and every
template for no present benefit.

## `rental/domain/pricing.py`

### Duration

```python
@dataclass(frozen=True)
class Duration:
    hours: int          # whole hours, rounded up, minimum 1
    full_days: int      # hours // 24
    extra_hours: int    # hours % 24
    billable_days: int  # ceil(hours / 24), minimum 1 -- what per-day fees charge


def duration_between(pickup_at: datetime, return_at: datetime) -> Duration
```

Part-hours round up: a rental is billed for the hour it begins. A zero or negative
span raises `ValueError` — that is a validation failure the caller should have
caught, not a price of nothing.

`hours` and `billable_days` are separate on purpose. The base rental may be billed
hourly for the remainder of a day, while an optional extra like insurance is
charged per calendar day. Conflating them is how a 25-hour rental ends up charging
one day of insurance.

### Quote

```python
@dataclass(frozen=True)
class Quote:
    duration: Duration
    daily_rate: Decimal
    hourly_rate: Decimal | None
    base_amount: Decimal
    additional_fees: Decimal
    total_amount: Decimal
    lines: tuple[tuple[str, str, Decimal], ...]   # (label, detail, amount)


def quote(
    pickup_at, return_at, *,
    daily_rate, hourly_rate, rates,
    want_additional_driver=False, want_insurance=False,
) -> Quote
```

The base amount, exactly as the phase 1 design settled:

```text
full_days   = hours // 24
extra_hours = hours % 24

with an hourly rate:
    base = full_days x daily_rate + min(extra_hours x hourly_rate, daily_rate)

without one (hourly_rate is None -- the vehicle is daily-only):
    base = ceil(hours / 24) x daily_rate
```

The `min(..., daily_rate)` cap is what keeps the function monotonic: a longer rental
can never cost less than a shorter one. Without it, 23 hours would cost more than
25. This is the single most important line in the module and it gets its own test.

Optional extras are charged per `billable_days`:

```text
additional_fees = billable_days x (additional_driver_fee? + insurance_fee?)
total_amount    = base_amount + additional_fees
```

`lines` exists because requirement 7 shows a rental summary itemising each
component above the total. If a template assembles that list itself, the summary can
disagree with the total it sits above. Emitting both from one function makes that
impossible. Each line carries a label ("Additional driver"), a human detail
("₱500.00 × 3 days") and the amount, so the template only formats.

### Late charge

```python
def late_charge(expected_return, actual_return, late_fee_per_day) -> tuple[int, Decimal]
```

Returns `(late_hours, fee)`. An on-time or early return gives `(0, Decimal("0.00"))`.
Otherwise `late_hours` is the overrun rounded up, and the fee is
`ceil(late_hours / 24) x late_fee_per_day` — a rental four hours late owes one late
day, which matches how the charge is described to a customer.

### Money

One helper, used by everything:

```python
PESO = Decimal("0.01")

def money(value) -> Decimal:
    return Decimal(value).quantize(PESO, rounding=ROUND_HALF_UP)
```

Every amount a `Quote` exposes has passed through it. This also makes the README's
claim about quantisation true, which phase 1's final review found it was not.

## `rental/domain/availability.py`

```python
@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


def overlaps(a: Interval, b: Interval) -> bool:
    return a.start < b.end and a.end > b.start
```

Touching endpoints do not conflict: a rental returning at 10:00 leaves the vehicle
bookable from 10:00. **No turnaround buffer** — an admin needing cleaning time
confirms the next reservation for a later slot. Should that change, it becomes one
configurable value inside this function rather than a rewrite.

```python
@dataclass(frozen=True)
class Availability:
    ok: bool
    reason: str | None                    # "inactive" | "maintenance" | "conflict"
    message: str                          # customer-facing
    conflicts: tuple[Interval, ...]


def check(requested: Interval, *, is_active: bool, status: str,
          blocked: Sequence[Interval]) -> Availability
```

The order of checks, which is the design decision the phase 1 spec resolved:

1. `is_active` false → unavailable, reason `inactive`. Not part of the fleet on offer.
2. `status == "MAINTENANCE"` → unavailable, reason `maintenance`, whatever the dates.
3. Any `blocked` interval overlapping `requested` → unavailable, reason `conflict`,
   with the offending intervals returned.
4. Otherwise available.

`RESERVED` and `RENTED` are deliberately **not** blanket refusals. They describe the
vehicle now; bookability is a question about a date range. A vehicle rented this week
is bookable next month, which is exactly requirement 9's worked example.

**`check()` takes plain intervals, never ORM rows.** Phase 3 queries the pending and
confirmed reservations, the active rentals and the uncompleted maintenance windows
and converts them. That keeps query logic out of the domain and the rule testable
without a database.

The distinct `reason` matters: requirement 6 needs different copy for "under
maintenance" and "already booked for those dates", and a bare boolean cannot tell
them apart.

## `rental/domain/lifecycle.py`

The legal transitions, as a table:

```python
RESERVATION_TRANSITIONS = {
    "PENDING":   {"CONFIRMED", "REJECTED", "CANCELLED"},
    "CONFIRMED": {"CANCELLED", "COMPLETED"},
    "CANCELLED": set(),
    "REJECTED":  set(),
    "COMPLETED": set(),
}

RENTAL_TRANSITIONS = {"ACTIVE": {"COMPLETED"}, "COMPLETED": set()}


class TransitionError(ValueError): ...

def can_transition(table, current, target) -> bool
def assert_transition(table, current, target) -> None     # raises TransitionError
```

Terminal states have an empty set rather than being absent, so an unknown status is
a `KeyError` — a bug — while a terminal one is a clean refusal.

The business operations return every resulting status at once:

```python
@dataclass(frozen=True)
class StateChange:
    reservation_status: str
    rental_status: str | None
    vehicle_status: str


def confirm_reservation(reservation_status) -> StateChange
def reject_reservation(reservation_status) -> StateChange
def cancel_reservation(reservation_status) -> StateChange
def start_rental(reservation_status) -> StateChange
def complete_rental(reservation_status, rental_status) -> StateChange
```

Requirement 18 lists five things that must happen when a vehicle is returned, across
three tables. Encoding that as one pure function returning each resulting status
means a route cannot perform four of them. The mapping:

| Operation | Reservation | Rental | Vehicle |
| --- | --- | --- | --- |
| confirm | CONFIRMED | — | RESERVED |
| reject | REJECTED | — | AVAILABLE |
| cancel | CANCELLED | — | AVAILABLE |
| start rental | CONFIRMED | ACTIVE | RENTED |
| complete rental | COMPLETED | COMPLETED | AVAILABLE |

Each guards its precondition: `start_rental` refuses anything but `CONFIRMED`,
`complete_rental` refuses a rental that is not `ACTIVE`.

Returning the vehicle to `AVAILABLE` on cancel or reject is the correct default for
phase 2, which cannot see other bookings. Phase 4 recomputes the vehicle's status
from its remaining reservations when it wires these up — noted here so that is a
decision rather than a discovery.

## Testing

Table-driven, no Flask, no database, sub-second. Roughly 50 tests across three files.

`tests/test_pricing.py`
- The requirement 7 worked example: 3 days × ₱1,500 = ₱4,500, exactly.
- **Monotonicity**: for a range of durations, cost never decreases as duration grows.
  This is the test that would have caught the missing `min(..., daily_rate)` cap.
- The 23h / 24h / 25h boundary explicitly.
- A daily-only vehicle (`hourly_rate is None`) rounds a part day up.
- A zero rate produces a zero total rather than an error.
- Extras charge `billable_days`, not `full_days`.
- `lines` sums to `total_amount` — the property that makes the summary trustworthy.
- Late: on time, early, four hours over, exactly 24 hours over, three days over.
- A zero or reversed duration raises `ValueError`.

`tests/test_availability.py`
- Requirement 9's worked example both ways: 29 Sep–1 Oct conflicts with an existing
  28 Sep–2 Oct; 3–6 Oct does not.
- Touching endpoints do not conflict, at both ends.
- Containment in both directions, and identical intervals.
- `inactive` and `maintenance` refuse regardless of dates, and take precedence over
  a date conflict.
- A `RENTED` vehicle is still bookable for a non-overlapping range.
- No blocked intervals at all.

`tests/test_lifecycle.py`
- Every legal transition in both tables.
- Every illegal one raises `TransitionError`, including all four terminal states.
- Each operation returns the exact `StateChange` row from the table above.
- `start_rental` refuses a `PENDING` reservation; `complete_rental` refuses a
  `COMPLETED` rental.
- An unknown status raises `KeyError`, not a silent pass.

The existing 129 tests must stay green. The clock change touches `models.py` and
`admin/dashboard.py`, so the dashboard's "today" tests are the ones to watch.

## Out of scope for phase 2

No routes, no templates, no forms, no queries. Nothing calls these modules until
phase 3. Outside `rental/domain/` the only changes are the new `clock.py` and the
call sites in the table above — `models.py`, `auth.py`, `admin/dashboard.py`,
`cli.py` and `forms.py` — each a one-line substitution.

Specifically not built here: the booking flow, the availability *query* that
assembles blocked intervals from the database, the admin actions that drive the
lifecycle, and any recomputation of a vehicle's status from its remaining
reservations. Those are phases 3 and 4, and each is a caller of what this phase
delivers.
