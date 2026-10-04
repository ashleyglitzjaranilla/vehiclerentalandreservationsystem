# Rental Domain Core — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three pure modules the booking engine will rest on — pricing, availability and lifecycle — with no Flask and no database, and correct the timezone inconsistency they depend on.

**Architecture:** A new `rental/domain/` package holding plain-value-in, plain-value-out functions. Nothing imports Flask, a session, or a model class. A new `rental/clock.py` becomes the single place the business timezone is defined, replacing three inconsistent sources of "now". No routes, templates or forms change; nothing calls the domain modules until phase 3.

**Tech Stack:** Python 3.12 · dataclasses · `decimal.Decimal` · `datetime` · pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-29-rental-domain-core-design.md`

## Global Constraints

- **No new runtime or dev dependencies.** `pyproject.toml`'s lists must not grow.
- **Prove purity with `uv run python scripts/check-domain-purity.py`.** A plain `import rental.domain.x` executes `rental/__init__.py` first -- the phase-1 app factory, which imports Flask and SQLAlchemy at module scope -- so it reports a leak whatever the domain module does. The script imports through a stub parent package so the answer means something, and it checks every module in `rental/domain/`, so it needs no editing as the package grows.
- **`rental/domain/` is pure.** No `flask`, no `sqlalchemy`, no import from `rental.models`, `rental.db` or any blueprint. A domain module must be importable with nothing but the standard library and testable without an app context. This is the constraint the whole phase exists to create — if a task needs a model, the design is wrong.
- **Money is `decimal.Decimal`, quantised to two places, half-up**, through the single `money()` helper. No float ever participates in a money calculation.
- **Every datetime is naive.** The system operates in one timezone. Never construct an aware datetime outside `rental/clock.py`, and never compare across the two.
- **Run tests with** `uv run pytest -q`. Every task ends with the whole suite green and nothing skipped. Baseline is 129.
- **Count the tests you add; do not trust the totals in this plan.** Each task states an expected total as a cross-check, but that arithmetic has been wrong before. If your count disagrees with the stated total, report both numbers and carry on — a mismatch usually means the plan miscounted, occasionally means a test was silently skipped, and is worth a sentence either way.
- **Pin `DATABASE_URL`** on any `flask` command: `DATABASE_URL=sqlite:////tmp/scratch.db uv run flask ...`. In a worktree, `python-dotenv` searches upward and can find a parent checkout's live database URL. Never pass `--yes` to `reset-db` to make an error go away — set the URL instead.
- **No Tailwind rebuild.** This phase changes no template and no CSS. `rental/static/css/output.css` must be untouched by every commit.
- **No routes, templates or forms.** If a task seems to need one, stop and report — it belongs to phase 3.

---

### Task 1: `rental/clock.py` and the call sites it replaces

The foundation. Everything after this computes durations, so the three competing clocks have to become one first.

**Files:**
- Create: `rental/clock.py`
- Create: `tests/test_clock.py`
- Modify: `rental/models.py` (remove `utcnow`, repoint nine column defaults)
- Modify: `rental/auth.py:22` (import) and `:204` (call)
- Modify: `rental/admin/dashboard.py:38-39`
- Modify: `rental/cli.py:148`
- Modify: `rental/forms.py:41`

**Interfaces:**
- Consumes: nothing
- Produces: `rental.clock.now() -> datetime` (naive, Philippine local), `rental.clock.today() -> date`, `rental.clock.PH` (the fixed `timezone`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_clock.py`:

```python
"""The single source of 'now'. Naive, Philippine local, server-independent."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from rental import clock


def test_now_is_naive():
    """Everything stored and compared is naive; an aware value poisons arithmetic."""
    assert clock.now().tzinfo is None


def test_now_is_philippine_time_regardless_of_the_server_clock():
    """It must be UTC+8 even when the server runs in UTC, as Vercel does."""
    expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
    assert abs((clock.now() - expected).total_seconds()) < 5


def test_today_is_the_local_date():
    assert clock.today() == clock.now().date()
    assert isinstance(clock.today(), date)


def test_now_subtracts_cleanly_from_a_stored_datetime():
    """The regression this module exists for.

    The old utcnow() returned an aware datetime while the columns store naive
    ones, so `utcnow() - reservation.expected_return` raised TypeError. The
    late-fee calculation does exactly that subtraction.
    """
    stored = datetime(2026, 10, 1, 9, 0)
    assert isinstance(clock.now() - stored, timedelta)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_clock.py -q`
Expected: FAIL — `ImportError: cannot import name 'clock' from 'rental'`

- [ ] **Step 3: Write the module**

Create `rental/clock.py`:

```python
"""The one place the business timezone is defined.

The system operates in a single timezone: Philippine time. A customer entering
9am means 9am, an admin reads 9am, and "today" means today in Manila. Every
datetime is stored naive and compared naive, so nothing converts anywhere.

Phase 1 left three clocks in play -- an aware UTC `utcnow()`, the naive value it
became once stored, and the server's own local date for "today". Subtracting one
from another raises TypeError, and "today's pickups" was the server's day rather
than the business's.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# A fixed offset rather than ZoneInfo("Asia/Manila"): the Philippines has not
# observed DST since 1978, so the offset is exact, and this needs no tz database
# to be present in the serverless runtime.
PH = timezone(timedelta(hours=8))


def now() -> datetime:
    """The current local time, naive, for storage and comparison.

    Deliberately not `datetime.now()`: that returns the *server's* local time,
    which is Manila in development and UTC on Vercel -- the kind of divergence
    that hides a bug until deploy.
    """
    return datetime.now(PH).replace(tzinfo=None)


def today() -> date:
    """The current local date. This is what "today's pickups" means."""
    return now().date()
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_clock.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Repoint `rental/models.py`**

Delete the `utcnow` function (around line 31) and its `timezone` import, then import the clock and repoint all nine column defaults.

Change the datetime import line from:

```python
from datetime import date, datetime, timezone
```

to:

```python
from datetime import date, datetime
```

Add below the sqlalchemy imports:

```python
from .clock import now
```

Delete:

```python
def utcnow() -> datetime:
    """Return the current UTC time (used as the default for timestamp columns)."""
    return datetime.now(timezone.utc)
```

Then replace every `default=utcnow` with `default=now` and every `onupdate=utcnow` with `onupdate=now`. There are nine columns across `User`, `Vehicle`, `RentalRates`, `Reservation`, `Rental` and `Maintenance`. Verify with:

```bash
grep -n 'utcnow' rental/models.py
```
Expected: no output.

- [ ] **Step 6: Repoint the four other call sites**

`rental/auth.py` — change the import on line 22 from `from .models import User, utcnow` to:

```python
from .clock import now
from .models import User
```

and line 204's `user.reset_requested_at = utcnow()` to `user.reset_requested_at = now()`.

`rental/admin/dashboard.py` — this is the one that was actually wrong. Change the import line `from datetime import date, datetime, time` to `from datetime import datetime, time`, add `from ..clock import today`, and change lines 38-39:

```python
    today_start = datetime.combine(today(), time.min)
    today_end = datetime.combine(today(), time.max)
```

`rental/cli.py` line 148 — `today = date.today()` becomes `today = clock_today()`, importing it as `from .clock import today as clock_today` to avoid shadowing the local variable. If that reads awkwardly, rename the local variable to `start` instead and use `today()` directly; either is fine, say which you chose.

`rental/forms.py` line 41 — inside `max_year()`, `return date.today().year + 1` becomes `return today().year + 1`, with `from .clock import today` added and the now-unused `date` import removed if nothing else in the file uses it (check first — `DateField` is unrelated).

- [ ] **Step 7: Confirm no source of "now" survives outside the clock**

```bash
grep -rn 'utcnow\|date\.today()\|datetime\.now()' rental/ --include='*.py' | grep -v __pycache__
```
Expected: hits only inside `rental/clock.py`. Anything else is a call site you missed.

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest -q`
Expected: 133 passed (129 + 4 new), nothing skipped.

If `test_the_admin_dashboard_counts_the_real_fleet` or the revenue test fails, read the failure before changing anything — the dashboard's "today" window just moved by eight hours and that is the point of the change, but no existing test should depend on the old behaviour.

- [ ] **Step 9: Verify the app still boots and the dashboard renders**

```bash
rm -f /tmp/t1clock.db
DATABASE_URL=sqlite:////tmp/t1clock.db uv run flask reset-db --password p1 --demo-password p2 >/dev/null
DATABASE_URL=sqlite:////tmp/t1clock.db uv run python -c "
import re
from rental import create_app
app = create_app()
c = app.test_client()
tok = re.search(r'name=\"csrf_token\"[^>]*value=\"([^\"]+)\"', c.get('/login').get_data(as_text=True)).group(1)
c.post('/login', data={'username':'admin','password':'p1','csrf_token':tok})
r = c.get('/admin')
print('dashboard ->', r.status_code)
print('figures:', re.findall(r'stat-value[^>]*>([^<]+)<', r.get_data(as_text=True)))
"
rm -f /tmp/t1clock.db
```
Expected: 200, and nine figures with no blanks.

- [ ] **Step 10: Confirm the stylesheet is untouched and commit**

```bash
git status --porcelain rental/static/css/output.css
```
Expected: no output.

```bash
git add rental/clock.py tests/test_clock.py rental/models.py rental/auth.py rental/admin/dashboard.py rental/cli.py rental/forms.py
git commit -m "feat: give the system one clock, in Philippine local time"
```

---

### Task 2: `domain/pricing.py` — duration and money

The primitives every price rests on. Built first and alone, because the day/hour boundary is where the arithmetic is easiest to get subtly wrong.

**Files:**
- Create: `rental/domain/__init__.py`
- Create: `rental/domain/pricing.py`
- Create: `tests/test_pricing.py`

**Interfaces:**
- Consumes: nothing (pure stdlib)
- Produces:
  - `rental.domain.pricing.PESO: Decimal`
  - `money(value) -> Decimal`
  - `Duration` frozen dataclass with `hours: int`, `full_days: int`, `extra_hours: int`, `billable_days: int`
  - `duration_between(pickup_at: datetime, return_at: datetime) -> Duration`, raising `ValueError` on a non-positive span

- [ ] **Step 1: Write the failing test**

Create `tests/test_pricing.py`:

```python
"""What a rental costs. Pure arithmetic -- no app, no database, no clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from rental.domain.pricing import Duration, duration_between, money

PICKUP = datetime(2026, 10, 1, 9, 0)


def at(**kwargs) -> datetime:
    """The return time, offset from a fixed pickup."""
    return PICKUP + timedelta(**kwargs)


def test_money_quantises_to_two_places():
    assert money(Decimal("1500")) == Decimal("1500.00")
    assert money("1500.4") == Decimal("1500.40")


def test_money_rounds_half_up():
    """Half-up, not banker's rounding: a customer expects 0.125 to become 0.13."""
    assert money(Decimal("0.125")) == Decimal("0.13")
    assert money(Decimal("0.135")) == Decimal("0.14")


def test_the_requirements_worked_example_is_three_whole_days():
    d = duration_between(PICKUP, at(days=3))
    assert d == Duration(hours=72, full_days=3, extra_hours=0, billable_days=3)


def test_a_part_hour_rounds_up():
    """A rental is billed for the hour it begins."""
    assert duration_between(PICKUP, at(minutes=1)).hours == 1
    assert duration_between(PICKUP, at(hours=2, minutes=1)).hours == 3


def test_the_day_boundary():
    assert duration_between(PICKUP, at(hours=23)).full_days == 0
    assert duration_between(PICKUP, at(hours=24)).full_days == 1
    assert duration_between(PICKUP, at(hours=25)).full_days == 1
    assert duration_between(PICKUP, at(hours=25)).extra_hours == 1


def test_billable_days_rounds_a_part_day_up():
    """Per-day extras charge whole days even when the base is billed hourly."""
    assert duration_between(PICKUP, at(hours=1)).billable_days == 1
    assert duration_between(PICKUP, at(hours=24)).billable_days == 1
    assert duration_between(PICKUP, at(hours=25)).billable_days == 2


def test_a_minimum_of_one_hour_is_charged():
    assert duration_between(PICKUP, at(seconds=30)).hours == 1


def test_a_zero_or_reversed_span_is_refused():
    """A validation failure the caller should have caught, not a free rental."""
    with pytest.raises(ValueError):
        duration_between(PICKUP, PICKUP)
    with pytest.raises(ValueError):
        duration_between(PICKUP, at(hours=-1))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_pricing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rental.domain'`

- [ ] **Step 3: Create the package and the module**

Create `rental/domain/__init__.py`:

```python
"""The rules the booking engine rests on, as pure functions.

Nothing here imports Flask, a database session or a model class. Every module
takes plain values and returns plain values, so the rules can be tested
exhaustively without fixtures and live in exactly one place -- which is what
lets the same function validate on the frontend and on the backend without two
implementations drifting apart.
"""
```

Create `rental/domain/pricing.py`:

```python
"""What a rental costs.

The base amount, the optional extras and any late charge. Pure arithmetic: no
app context, no database, and no clock -- every time is passed in, so a test can
price a rental in 2019 or 2031 without mocking anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

PESO = Decimal("0.01")


def money(value) -> Decimal:
    """Quantise to two decimal places, rounding half up.

    Every amount this module returns has passed through here, so a total can
    never carry the long tail of a division.
    """
    return Decimal(value).quantize(PESO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Duration:
    """How long a rental runs, in the several shapes the pricing needs.

    `hours` and `billable_days` are separate on purpose. The base rental may bill
    the remainder of a day by the hour, while a per-day extra like insurance
    charges a whole day for that same remainder. Conflating them is how a
    25-hour rental ends up charging one day of insurance.
    """

    hours: int
    full_days: int
    extra_hours: int
    billable_days: int


def duration_between(pickup_at: datetime, return_at: datetime) -> Duration:
    """Measure a rental, rounding part hours up.

    Both datetimes must be naive -- the system stores and compares naive local
    times (see rental/clock.py). A non-positive span raises, because that is a
    validation failure the caller should already have refused, not a rental
    that costs nothing.
    """
    if return_at <= pickup_at:
        raise ValueError("A rental must end after it begins.")

    hours = max(1, math.ceil((return_at - pickup_at).total_seconds() / 3600))
    return Duration(
        hours=hours,
        full_days=hours // 24,
        extra_hours=hours % 24,
        billable_days=max(1, math.ceil(hours / 24)),
    )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_pricing.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Confirm the purity constraint holds**

This is the constraint the whole phase exists to create, so prove it rather than assume it:

```bash
uv run python scripts/check-domain-purity.py
```
Expected: `NONE`.

- [ ] **Step 6: Run the whole suite and commit**

```bash
uv run pytest -q
git status --porcelain rental/static/css/output.css
git add rental/domain tests/test_pricing.py
git commit -m "feat: add rental duration and money primitives"
```
Expected: 141 passed (133 + 8), stylesheet untouched.

---

### Task 3: `domain/pricing.py` — the quote and the late charge

The money. Builds on Task 2's primitives.

**Files:**
- Modify: `rental/domain/pricing.py` (append)
- Modify: `tests/test_pricing.py` (append)

**Interfaces:**
- Consumes: Task 2's `money`, `Duration`, `duration_between`
- Produces:
  - `Rates` frozen dataclass: `additional_driver_fee_per_day`, `insurance_fee_per_day`, `late_fee_per_day`, all `Decimal`
  - `Quote` frozen dataclass: `duration`, `daily_rate`, `hourly_rate`, `base_amount`, `additional_fees`, `total_amount`, `lines`
  - `quote(pickup_at, return_at, *, daily_rate, hourly_rate=None, rates, want_additional_driver=False, want_insurance=False) -> Quote`
  - `late_charge(expected_return, actual_return, late_fee_per_day) -> tuple[int, Decimal]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pricing.py`:

```python
from rental.domain.pricing import Quote, Rates, late_charge, quote

RATES = Rates(
    additional_driver_fee_per_day=Decimal("500.00"),
    insurance_fee_per_day=Decimal("300.00"),
    late_fee_per_day=Decimal("800.00"),
)


def price(return_at, *, daily="1500.00", hourly=None, driver=False, insurance=False) -> Quote:
    return quote(
        PICKUP, return_at,
        daily_rate=Decimal(daily),
        hourly_rate=Decimal(hourly) if hourly else None,
        rates=RATES,
        want_additional_driver=driver,
        want_insurance=insurance,
    )


def test_the_requirements_worked_example():
    """3 days x P1,500 = P4,500, exactly as the requirements state it."""
    q = price(at(days=3))
    assert q.base_amount == Decimal("4500.00")
    assert q.additional_fees == Decimal("0.00")
    assert q.total_amount == Decimal("4500.00")


def test_cost_never_decreases_as_the_rental_lengthens():
    """The property the hourly cap exists to protect.

    Without `min(extra_hours x hourly, daily)` a 23-hour rental costs more than
    a 25-hour one. This walks the whole boundary rather than spot-checking it.
    """
    previous = Decimal("0")
    for hours in range(1, 80):
        total = price(at(hours=hours), hourly="250.00").total_amount
        assert total >= previous, f"{hours}h cost less than {hours - 1}h"
        previous = total


def test_the_hourly_remainder_is_capped_at_a_full_day():
    """23 hourly hours would exceed the daily rate; the cap holds it there."""
    assert price(at(hours=23), hourly="250.00").base_amount == Decimal("1500.00")
    assert price(at(hours=24), hourly="250.00").base_amount == Decimal("1500.00")
    assert price(at(hours=25), hourly="250.00").base_amount == Decimal("1750.00")


def test_a_short_hourly_rental_is_billed_by_the_hour():
    assert price(at(hours=3), hourly="250.00").base_amount == Decimal("750.00")


def test_a_daily_only_vehicle_rounds_a_part_day_up():
    """hourly_rate is None -- the NULL the seed carries for three vehicles."""
    assert price(at(hours=3)).base_amount == Decimal("1500.00")
    assert price(at(hours=25)).base_amount == Decimal("3000.00")


def test_a_zero_rate_produces_a_zero_total():
    """Zero is a legitimate rate, not a missing one."""
    q = price(at(days=3), daily="0.00")
    assert q.total_amount == Decimal("0.00")


def test_extras_charge_billable_days_not_full_days():
    """A 25-hour rental owes two days of insurance, not one."""
    q = price(at(hours=25), hourly="250.00", insurance=True)
    assert q.additional_fees == Decimal("600.00")


def test_both_extras_add_together():
    q = price(at(days=3), driver=True, insurance=True)
    assert q.additional_fees == Decimal("2400.00")   # (500 + 300) x 3
    assert q.total_amount == Decimal("6900.00")      # 4500 + 2400


def test_the_summary_lines_sum_to_the_total():
    """What makes the itemised summary trustworthy.

    Requirement 7 shows each component above the total. If a template built that
    list itself it could disagree with the total it sits beneath; emitting both
    from one function makes that impossible.
    """
    q = price(at(days=3), driver=True, insurance=True)
    assert sum(amount for _, _, amount in q.lines) == q.total_amount


def test_the_summary_names_every_charge_taken():
    q = price(at(days=3), driver=True, insurance=True)
    labels = [label for label, _, _ in q.lines]
    assert labels == ["Base rental", "Additional driver", "Insurance"]


def test_an_untaken_extra_gets_no_line():
    q = price(at(days=3), driver=True)
    assert [label for label, _, _ in q.lines] == ["Base rental", "Additional driver"]


def test_an_on_time_or_early_return_owes_nothing():
    expected = at(days=3)
    assert late_charge(expected, expected, RATES.late_fee_per_day) == (0, Decimal("0.00"))
    assert late_charge(expected, expected - timedelta(hours=2), RATES.late_fee_per_day) == (
        0, Decimal("0.00"),
    )


def test_a_few_hours_late_owes_one_whole_day():
    """The charge is described to a customer in days, so it is billed in days."""
    expected = at(days=3)
    hours, fee = late_charge(expected, expected + timedelta(hours=4), RATES.late_fee_per_day)
    assert (hours, fee) == (4, Decimal("800.00"))


def test_exactly_one_day_late():
    expected = at(days=3)
    assert late_charge(expected, expected + timedelta(hours=24), RATES.late_fee_per_day) == (
        24, Decimal("800.00"),
    )


def test_two_days_and_a_bit_late_owes_three_days():
    expected = at(days=3)
    hours, fee = late_charge(expected, expected + timedelta(hours=49), RATES.late_fee_per_day)
    assert (hours, fee) == (49, Decimal("2400.00"))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_pricing.py -q`
Expected: FAIL — `ImportError: cannot import name 'Rates'`

- [ ] **Step 3: Append the implementation**

Append to `rental/domain/pricing.py`:

```python
@dataclass(frozen=True)
class Rates:
    """The system-wide fee schedule as plain values.

    Mirrors the RentalRates row without importing it: the domain never touches
    the ORM, so phase 3 builds one of these from the row it already loaded.
    """

    additional_driver_fee_per_day: Decimal
    insurance_fee_per_day: Decimal
    late_fee_per_day: Decimal


@dataclass(frozen=True)
class Quote:
    """A priced rental, and the itemisation that explains it."""

    duration: Duration
    daily_rate: Decimal
    hourly_rate: Decimal | None
    base_amount: Decimal
    additional_fees: Decimal
    total_amount: Decimal
    # (label, detail, amount) -- e.g. ("Insurance", "P300.00 x 3 days", 900.00).
    # The detail carries a currency symbol, which is presentation leaking one
    # level into the domain. Accepted deliberately: the alternative is a template
    # reassembling these strings, and a summary that can drift from its own total
    # is worse than a domain that knows the business trades in pesos.
    lines: tuple[tuple[str, str, Decimal], ...]


def _peso(amount: Decimal) -> str:
    """Format an amount for a summary line."""
    return f"₱{amount:,.2f}"


def _base_amount(duration: Duration, daily_rate: Decimal, hourly_rate: Decimal | None) -> Decimal:
    """The rental itself, before any extras.

    With an hourly rate the remainder of a part day is billed by the hour, but
    capped at the daily rate -- without that cap a 23-hour rental would cost more
    than a 25-hour one, and price would stop being monotonic in duration.

    Without one the vehicle is daily-only and any part day rounds up.
    """
    if hourly_rate is None:
        return money(daily_rate * duration.billable_days)

    remainder = min(money(hourly_rate * duration.extra_hours), money(daily_rate))
    return money(daily_rate * duration.full_days + remainder)


def quote(
    pickup_at: datetime,
    return_at: datetime,
    *,
    daily_rate: Decimal,
    hourly_rate: Decimal | None = None,
    rates: Rates,
    want_additional_driver: bool = False,
    want_insurance: bool = False,
) -> Quote:
    """Price a rental and itemise it.

    Optional extras are charged per `billable_days`, so a part day of insurance
    costs a whole day -- which is how the fee is described on the rates page.
    """
    duration = duration_between(pickup_at, return_at)
    daily_rate = money(daily_rate)
    hourly_rate = money(hourly_rate) if hourly_rate is not None else None

    base_amount = _base_amount(duration, daily_rate, hourly_rate)
    days = duration.billable_days

    if hourly_rate is None or duration.extra_hours == 0:
        base_detail = f"{_peso(daily_rate)} x {duration.billable_days} day(s)"
    else:
        base_detail = (
            f"{_peso(daily_rate)} x {duration.full_days} day(s) "
            f"+ {duration.extra_hours} hour(s)"
        )

    lines: list[tuple[str, str, Decimal]] = [("Base rental", base_detail, base_amount)]
    additional_fees = money(0)

    for taken, label, per_day in (
        (want_additional_driver, "Additional driver", rates.additional_driver_fee_per_day),
        (want_insurance, "Insurance", rates.insurance_fee_per_day),
    ):
        if not taken:
            continue
        amount = money(money(per_day) * days)
        additional_fees = money(additional_fees + amount)
        lines.append((label, f"{_peso(money(per_day))} x {days} day(s)", amount))

    return Quote(
        duration=duration,
        daily_rate=daily_rate,
        hourly_rate=hourly_rate,
        base_amount=base_amount,
        additional_fees=additional_fees,
        total_amount=money(base_amount + additional_fees),
        lines=tuple(lines),
    )


def late_charge(
    expected_return: datetime, actual_return: datetime, late_fee_per_day: Decimal
) -> tuple[int, Decimal]:
    """What a late return owes, as (late_hours, fee).

    An on-time or early return owes nothing. Otherwise the overrun rounds up to
    whole hours, and the fee charges whole days -- four hours late is one late
    day, which is how the charge is explained to a customer.
    """
    if actual_return <= expected_return:
        return 0, money(0)

    late_hours = math.ceil((actual_return - expected_return).total_seconds() / 3600)
    late_days = math.ceil(late_hours / 24)
    return late_hours, money(money(late_fee_per_day) * late_days)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pricing.py -q`
Expected: PASS, 23 tests.

If `test_cost_never_decreases_as_the_rental_lengthens` fails, the cap in `_base_amount` is wrong — that test exists precisely to catch it, so read the reported hour count rather than adjusting the test.

- [ ] **Step 5: Prove the monotonicity test can fail**

A test written to catch a missing cap is worthless if it passes without one. Temporarily remove the cap so the remainder is uncapped:

```python
    remainder = money(hourly_rate * duration.extra_hours)
```

Run `uv run pytest tests/test_pricing.py -q` and confirm the monotonicity test goes red with a specific hour count. Restore the `min(...)`, re-run, confirm green. Paste both outputs in your report.

- [ ] **Step 6: Confirm purity, run the suite, commit**

```bash
uv run python scripts/check-domain-purity.py
uv run pytest -q
git status --porcelain rental/static/css/output.css
git add rental/domain/pricing.py tests/test_pricing.py
git commit -m "feat: price a rental and itemise it"
```
Expected: `NONE`, 156 passed (141 + 15), stylesheet untouched.

---

### Task 4: `domain/availability.py`

Whether a vehicle can be booked for a date range. The overlap rule is four lines; getting the precedence and the endpoints right is the work.

**Files:**
- Create: `rental/domain/availability.py`
- Create: `tests/test_availability.py`

**Interfaces:**
- Consumes: nothing (pure stdlib)
- Produces:
  - `Interval` frozen dataclass: `start: datetime`, `end: datetime`
  - `overlaps(a: Interval, b: Interval) -> bool`
  - `Availability` frozen dataclass: `ok: bool`, `reason: str | None`, `message: str`, `conflicts: tuple[Interval, ...]`
  - `check(requested: Interval, *, is_active: bool, status: str, blocked: Sequence[Interval]) -> Availability`
  - Reason constants `INACTIVE`, `MAINTENANCE`, `CONFLICT`

- [ ] **Step 1: Write the failing test**

Create `tests/test_availability.py`:

```python
"""Whether a vehicle can be booked for a date range.

Every case here is a date-range question. A vehicle's `status` describes it now;
bookability is a different question, and conflating them is the mistake the
requirements' own worked example is designed to catch.
"""

from __future__ import annotations

from datetime import datetime

from rental.domain.availability import (
    CONFLICT,
    INACTIVE,
    MAINTENANCE,
    Interval,
    check,
    overlaps,
)


def span(d1: int, d2: int) -> Interval:
    """An interval over days in October 2026, at 09:00."""
    return Interval(datetime(2026, 10, d1, 9, 0), datetime(2026, 10, d2, 9, 0))


def ask(requested: Interval, *, is_active=True, status="AVAILABLE", blocked=()):
    return check(requested, is_active=is_active, status=status, blocked=blocked)


# -- the overlap predicate itself ------------------------------------------

def test_the_requirements_worked_example_conflicts():
    """Existing 28 Sep - 2 Oct; new 29 Sep - 1 Oct. Sits inside it."""
    existing = Interval(datetime(2026, 9, 28, 9, 0), datetime(2026, 10, 2, 9, 0))
    new = Interval(datetime(2026, 9, 29, 9, 0), datetime(2026, 10, 1, 9, 0))
    assert overlaps(new, existing) is True


def test_the_requirements_worked_example_does_not_conflict():
    """Same existing booking; new 3 - 6 Oct. Clear of it."""
    existing = Interval(datetime(2026, 9, 28, 9, 0), datetime(2026, 10, 2, 9, 0))
    assert overlaps(span(3, 6), existing) is False


def test_touching_endpoints_do_not_conflict():
    """A rental returning at 10:00 leaves the vehicle bookable from 10:00.

    No turnaround buffer by design -- an admin needing cleaning time confirms
    the next reservation for a later slot.
    """
    assert overlaps(span(3, 6), span(1, 3)) is False   # new starts as old ends
    assert overlaps(span(1, 3), span(3, 6)) is False   # old starts as new ends


def test_containment_conflicts_both_ways():
    assert overlaps(span(2, 3), span(1, 5)) is True    # new inside existing
    assert overlaps(span(1, 5), span(2, 3)) is True    # existing inside new


def test_identical_intervals_conflict():
    assert overlaps(span(1, 3), span(1, 3)) is True


def test_a_one_hour_sliver_of_overlap_conflicts():
    a = Interval(datetime(2026, 10, 1, 9, 0), datetime(2026, 10, 3, 10, 0))
    b = Interval(datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 6, 9, 0))
    assert overlaps(a, b) is True


# -- the check, and its precedence -----------------------------------------

def test_a_clear_vehicle_is_available():
    result = ask(span(3, 6))
    assert result.ok is True
    assert result.reason is None
    assert result.conflicts == ()


def test_no_blocked_intervals_at_all():
    assert ask(span(3, 6), blocked=()).ok is True


def test_a_disabled_vehicle_is_refused_whatever_the_dates():
    result = ask(span(3, 6), is_active=False)
    assert result.ok is False
    assert result.reason == INACTIVE


def test_a_vehicle_under_maintenance_is_refused_whatever_the_dates():
    result = ask(span(3, 6), status="MAINTENANCE")
    assert result.ok is False
    assert result.reason == MAINTENANCE
    assert "maintenance" in result.message.lower()


def test_an_overlapping_booking_is_refused_and_names_the_conflict():
    result = ask(span(2, 4), blocked=[span(1, 3)])
    assert result.ok is False
    assert result.reason == CONFLICT
    assert result.conflicts == (span(1, 3),)


def test_every_overlapping_interval_is_reported():
    result = ask(span(1, 10), blocked=[span(2, 3), span(20, 21), span(5, 6)])
    assert result.conflicts == (span(2, 3), span(5, 6))


def test_a_rented_vehicle_is_still_bookable_outside_its_dates():
    """The heart of the status-versus-availability split.

    A vehicle rented this week is bookable next month. A blanket refusal on
    status would make the requirements' own second worked example fail.
    """
    result = ask(span(20, 22), status="RENTED", blocked=[span(1, 3)])
    assert result.ok is True


def test_inactive_takes_precedence_over_a_date_conflict():
    """The most specific true reason, so the message is not misleading."""
    result = ask(span(2, 4), is_active=False, status="MAINTENANCE", blocked=[span(1, 3)])
    assert result.reason == INACTIVE


def test_maintenance_takes_precedence_over_a_date_conflict():
    result = ask(span(2, 4), status="MAINTENANCE", blocked=[span(1, 3)])
    assert result.reason == MAINTENANCE


def test_every_refusal_carries_a_message_a_customer_can_read():
    for kwargs in ({"is_active": False}, {"status": "MAINTENANCE"}, {"blocked": [span(1, 3)]}):
        result = ask(span(2, 4), **kwargs)
        assert result.ok is False
        assert result.message and result.message[0].isupper()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_availability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rental.domain.availability'`

- [ ] **Step 3: Write the module**

Create `rental/domain/availability.py`:

```python
"""Whether a vehicle can be booked for a particular date range.

The rule the requirements state, and the one thing the whole phase-1 design
turns on: a vehicle's `status` describes it *now*, while bookability is a
question about a *range*. A vehicle rented this week is bookable next month, so
RESERVED and RENTED are never blanket refusals -- only the dates decide.

This module takes plain intervals, never ORM rows. The caller queries the
pending and confirmed reservations, the active rentals and the uncompleted
maintenance windows and converts them, which keeps query logic out of the rule
and lets every case here be tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

#: A vehicle withdrawn from the fleet. Not on offer at all.
INACTIVE = "inactive"
#: Off the road. Refused whatever the dates, per the requirements.
MAINTENANCE = "maintenance"
#: Free in principle, but already spoken for over the requested range.
CONFLICT = "conflict"


@dataclass(frozen=True)
class Interval:
    """A half-open period: `start` inclusive, `end` exclusive.

    Half-open is what makes touching bookings legal -- a rental ending at 10:00
    and one starting at 10:00 do not overlap.
    """

    start: datetime
    end: datetime


def overlaps(a: Interval, b: Interval) -> bool:
    """True when two periods share any time at all.

    The textbook two-comparison form. Touching endpoints deliberately do not
    count: there is no turnaround buffer, so a return at 10:00 frees the vehicle
    from 10:00. Should that ever change, it changes here and nowhere else.
    """
    return a.start < b.end and a.end > b.start


@dataclass(frozen=True)
class Availability:
    """The answer, and enough detail for the caller to explain it.

    `reason` is for code to branch on; `message` is for a customer to read;
    `conflicts` lets the caller show which dates are already taken.
    """

    ok: bool
    reason: str | None = None
    message: str = "Vehicle available"
    conflicts: tuple[Interval, ...] = ()


def check(
    requested: Interval,
    *,
    is_active: bool,
    status: str,
    blocked: Sequence[Interval],
) -> Availability:
    """Decide whether `requested` can be booked.

    The checks run most-specific first, so the message a customer sees names the
    real obstacle rather than whichever one happened to be tested first.
    """
    if not is_active:
        return Availability(
            ok=False,
            reason=INACTIVE,
            message="This vehicle is not currently offered for rent.",
        )

    if status == "MAINTENANCE":
        return Availability(
            ok=False,
            reason=MAINTENANCE,
            message="Currently unavailable. This vehicle is under maintenance.",
        )

    conflicts = tuple(period for period in blocked if overlaps(requested, period))
    if conflicts:
        return Availability(
            ok=False,
            reason=CONFLICT,
            message=(
                "This vehicle is already reserved or rented during your "
                "selected dates."
            ),
            conflicts=conflicts,
        )

    return Availability(ok=True)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_availability.py -q`
Expected: PASS, 16 tests.

- [ ] **Step 5: Prove the endpoint rule can fail**

The touching-endpoints behaviour is one character away from wrong. Temporarily change `overlaps` to use `<=` and `>=`:

```python
    return a.start <= b.end and a.end >= b.start
```

Run `uv run pytest tests/test_availability.py -q` and confirm `test_touching_endpoints_do_not_conflict` goes red. Restore the strict comparisons, re-run, confirm green. Paste both outputs.

- [ ] **Step 6: Confirm purity, run the suite, commit**

```bash
uv run python scripts/check-domain-purity.py
uv run pytest -q
git status --porcelain rental/static/css/output.css
git add rental/domain/availability.py tests/test_availability.py
git commit -m "feat: decide whether a vehicle is bookable for a date range"
```
Expected: `NONE`, 172 passed (156 + 16), stylesheet untouched.

---

### Task 5: `domain/lifecycle.py`

Which status changes are legal, and what each business operation does to all three tables at once.

**Files:**
- Create: `rental/domain/lifecycle.py`
- Create: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: nothing (pure stdlib)
- Produces:
  - `RESERVATION_TRANSITIONS`, `RENTAL_TRANSITIONS` — `dict[str, set[str]]`
  - `TransitionError(ValueError)`
  - `can_transition(table, current, target) -> bool`
  - `assert_transition(table, current, target) -> None`
  - `StateChange` frozen dataclass: `reservation_status: str`, `rental_status: str | None`, `vehicle_status: str`
  - `confirm_reservation(reservation_status) -> StateChange`
  - `reject_reservation(reservation_status) -> StateChange`
  - `cancel_reservation(reservation_status) -> StateChange`
  - `start_rental(reservation_status) -> StateChange`
  - `complete_rental(reservation_status, rental_status) -> StateChange`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle.py`:

```python
"""Which status changes are legal, and what each operation changes.

Requirement 18 lists five things that must happen when a vehicle is returned,
across three tables. Returning every resulting status from one function is what
stops a route performing four of them.
"""

from __future__ import annotations

import pytest

from rental.domain.lifecycle import (
    RENTAL_TRANSITIONS,
    RESERVATION_TRANSITIONS,
    StateChange,
    TransitionError,
    assert_transition,
    can_transition,
    cancel_reservation,
    complete_rental,
    confirm_reservation,
    reject_reservation,
    start_rental,
)


# -- the transition tables --------------------------------------------------

@pytest.mark.parametrize(
    "current,target",
    [
        ("PENDING", "CONFIRMED"),
        ("PENDING", "REJECTED"),
        ("PENDING", "CANCELLED"),
        ("CONFIRMED", "CANCELLED"),
        ("CONFIRMED", "COMPLETED"),
    ],
)
def test_every_legal_reservation_transition(current, target):
    assert can_transition(RESERVATION_TRANSITIONS, current, target) is True


@pytest.mark.parametrize(
    "current,target",
    [
        ("PENDING", "COMPLETED"),   # cannot finish what was never confirmed
        ("CONFIRMED", "PENDING"),   # no going back
        ("CONFIRMED", "REJECTED"),  # reject is for pending requests only
        ("CANCELLED", "CONFIRMED"),
        ("REJECTED", "CONFIRMED"),
        ("COMPLETED", "CANCELLED"),
    ],
)
def test_every_illegal_reservation_transition(current, target):
    assert can_transition(RESERVATION_TRANSITIONS, current, target) is False
    with pytest.raises(TransitionError):
        assert_transition(RESERVATION_TRANSITIONS, current, target)


@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED", "COMPLETED"])
def test_terminal_reservation_states_go_nowhere(status):
    assert RESERVATION_TRANSITIONS[status] == set()


def test_the_rental_table():
    assert can_transition(RENTAL_TRANSITIONS, "ACTIVE", "COMPLETED") is True
    assert can_transition(RENTAL_TRANSITIONS, "COMPLETED", "ACTIVE") is False
    assert RENTAL_TRANSITIONS["COMPLETED"] == set()


def test_an_unknown_status_is_a_bug_not_a_refusal():
    """KeyError, not False: a typo must surface rather than silently deny."""
    with pytest.raises(KeyError):
        can_transition(RESERVATION_TRANSITIONS, "PENDIGN", "CONFIRMED")


def test_an_unknown_target_is_simply_illegal():
    assert can_transition(RESERVATION_TRANSITIONS, "PENDING", "NONSENSE") is False


# -- the operations ---------------------------------------------------------

def test_confirming_reserves_the_vehicle():
    assert confirm_reservation("PENDING") == StateChange(
        reservation_status="CONFIRMED", rental_status=None, vehicle_status="RESERVED",
    )


def test_rejecting_frees_the_vehicle():
    assert reject_reservation("PENDING") == StateChange(
        reservation_status="REJECTED", rental_status=None, vehicle_status="AVAILABLE",
    )


def test_cancelling_frees_the_vehicle():
    assert cancel_reservation("CONFIRMED") == StateChange(
        reservation_status="CANCELLED", rental_status=None, vehicle_status="AVAILABLE",
    )


def test_starting_a_rental_marks_the_vehicle_rented():
    assert start_rental("CONFIRMED") == StateChange(
        reservation_status="CONFIRMED", rental_status="ACTIVE", vehicle_status="RENTED",
    )


def test_completing_a_rental_closes_all_three():
    """The five-part return of requirement 18, as one value."""
    assert complete_rental("CONFIRMED", "ACTIVE") == StateChange(
        reservation_status="COMPLETED", rental_status="COMPLETED", vehicle_status="AVAILABLE",
    )


# -- the guards -------------------------------------------------------------

def test_a_rental_cannot_start_from_an_unconfirmed_reservation():
    with pytest.raises(TransitionError):
        start_rental("PENDING")


def test_a_rental_cannot_start_from_a_cancelled_reservation():
    with pytest.raises(TransitionError):
        start_rental("CANCELLED")


def test_a_completed_rental_cannot_be_completed_again():
    with pytest.raises(TransitionError):
        complete_rental("CONFIRMED", "COMPLETED")


def test_confirming_twice_is_refused():
    with pytest.raises(TransitionError):
        confirm_reservation("CONFIRMED")


def test_rejecting_a_confirmed_reservation_is_refused():
    """Once confirmed it is cancelled, not rejected -- they mean different things."""
    with pytest.raises(TransitionError):
        reject_reservation("CONFIRMED")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_lifecycle.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rental.domain.lifecycle'`

- [ ] **Step 3: Write the module**

Create `rental/domain/lifecycle.py`:

```python
"""Which status changes are legal, and what each operation changes.

A reservation, the rental that may grow out of it, and the vehicle all carry
their own status, and a single business action moves several at once. Requirement
18 lists five things that must happen when a vehicle comes back. Keeping that
mapping here, as a pure function returning every resulting status, means a route
cannot perform four of the five -- and the whole thing is testable without a
database.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Terminal states map to an empty set rather than being absent, so an unknown
#: status raises KeyError -- a bug -- while a finished one is a clean refusal.
RESERVATION_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CONFIRMED", "REJECTED", "CANCELLED"},
    "CONFIRMED": {"CANCELLED", "COMPLETED"},
    "CANCELLED": set(),
    "REJECTED": set(),
    "COMPLETED": set(),
}

RENTAL_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVE": {"COMPLETED"},
    "COMPLETED": set(),
}


class TransitionError(ValueError):
    """An illegal status change was attempted."""


def can_transition(table: dict[str, set[str]], current: str, target: str) -> bool:
    """True when `current` may become `target`.

    An unrecognised `current` raises KeyError on purpose: a mistyped status is a
    programming error and should surface, not quietly deny a legitimate action.
    """
    return target in table[current]


def assert_transition(table: dict[str, set[str]], current: str, target: str) -> None:
    """Raise TransitionError unless the change is legal."""
    if not can_transition(table, current, target):
        raise TransitionError(f"Cannot go from {current} to {target}.")


@dataclass(frozen=True)
class StateChange:
    """Every status an operation leaves behind.

    `rental_status` is None for operations that do not involve a rental.
    """

    reservation_status: str
    rental_status: str | None
    vehicle_status: str


def confirm_reservation(reservation_status: str) -> StateChange:
    """An admin accepts a pending request. The vehicle is now spoken for."""
    assert_transition(RESERVATION_TRANSITIONS, reservation_status, "CONFIRMED")
    return StateChange("CONFIRMED", None, "RESERVED")


def reject_reservation(reservation_status: str) -> StateChange:
    """An admin declines a pending request."""
    assert_transition(RESERVATION_TRANSITIONS, reservation_status, "REJECTED")
    return StateChange("REJECTED", None, "AVAILABLE")


def cancel_reservation(reservation_status: str) -> StateChange:
    """The customer or an admin calls it off, before or after confirmation."""
    assert_transition(RESERVATION_TRANSITIONS, reservation_status, "CANCELLED")
    return StateChange("CANCELLED", None, "AVAILABLE")


def start_rental(reservation_status: str) -> StateChange:
    """The customer collects the vehicle.

    The reservation stays CONFIRMED -- it is not finished until the vehicle
    comes back -- while the rental begins and the vehicle goes out.
    """
    if reservation_status != "CONFIRMED":
        raise TransitionError(
            f"A rental can only start from a CONFIRMED reservation, not {reservation_status}."
        )
    return StateChange("CONFIRMED", "ACTIVE", "RENTED")


def complete_rental(reservation_status: str, rental_status: str) -> StateChange:
    """The vehicle comes back. Requirement 18's five-part close, as one value."""
    assert_transition(RENTAL_TRANSITIONS, rental_status, "COMPLETED")
    assert_transition(RESERVATION_TRANSITIONS, reservation_status, "COMPLETED")
    return StateChange("COMPLETED", "COMPLETED", "AVAILABLE")
```

**A note on returning the vehicle to AVAILABLE on cancel and reject.** This module
cannot see the vehicle's other bookings, so AVAILABLE is the correct answer at
this level. Phase 4 recomputes a vehicle's status from its remaining reservations
when it wires these up. That is a decision, recorded here so it is not a later
discovery.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_lifecycle.py -q`
Expected: PASS, 27 tests.

- [ ] **Step 5: Confirm purity, run the suite, commit**

```bash
uv run python scripts/check-domain-purity.py
uv run pytest -q
git status --porcelain rental/static/css/output.css
git add rental/domain/lifecycle.py tests/test_lifecycle.py
git commit -m "feat: guard the reservation and rental lifecycle"
```
Expected: `NONE`, 199 passed (172 + 27), stylesheet untouched.

---

### Task 6: Phase 2 verification

The domain is built but nothing calls it. This task proves the three modules compose into the workflow phase 3 will drive, without adding any production code.

**Files:**
- Create: `tests/test_domain_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 2-5
- Produces: nothing — a test-only task

- [ ] **Step 1: Write the walkthrough**

Create `tests/test_domain_integration.py`:

```python
"""The three domain modules, exercised together.

Each module is unit-tested in isolation. This walks the requirements' own demo
scenario end to end -- browse, check, price, confirm, collect, return late --
using only the domain, to prove the pieces compose before phase 3 wires them to
routes. Still no app and no database.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from rental.domain.availability import CONFLICT, Interval, check
from rental.domain.lifecycle import (
    TransitionError,
    complete_rental,
    confirm_reservation,
    start_rental,
)
from rental.domain.pricing import Rates, late_charge, quote

RATES = Rates(
    additional_driver_fee_per_day=Decimal("500.00"),
    insurance_fee_per_day=Decimal("300.00"),
    late_fee_per_day=Decimal("800.00"),
)

# The requirements' scenario: a Toyota Vios at P1,500/day, 28 Sep to 1 Oct.
PICKUP = datetime(2026, 9, 28, 9, 0)
RETURN = datetime(2026, 10, 1, 9, 0)


def test_the_demo_scenario_end_to_end():
    requested = Interval(PICKUP, RETURN)

    # 1. The vehicle is free for those dates.
    availability = check(requested, is_active=True, status="AVAILABLE", blocked=[])
    assert availability.ok is True

    # 2. It prices at exactly what the requirements say.
    priced = quote(PICKUP, RETURN, daily_rate=Decimal("1500.00"), rates=RATES)
    assert priced.duration.billable_days == 3
    assert priced.total_amount == Decimal("4500.00")

    # 3. An admin confirms it; the vehicle is spoken for.
    confirmed = confirm_reservation("PENDING")
    assert confirmed.vehicle_status == "RESERVED"

    # 4. The customer collects it.
    collected = start_rental(confirmed.reservation_status)
    assert collected.vehicle_status == "RENTED"
    assert collected.rental_status == "ACTIVE"

    # 5. They bring it back two days late.
    actual_return = RETURN + timedelta(days=2)
    late_hours, fee = late_charge(RETURN, actual_return, RATES.late_fee_per_day)
    assert (late_hours, fee) == (48, Decimal("1600.00"))

    # 6. Everything closes and the vehicle goes back on the fleet.
    closed = complete_rental(collected.reservation_status, collected.rental_status)
    assert closed.reservation_status == "COMPLETED"
    assert closed.rental_status == "COMPLETED"
    assert closed.vehicle_status == "AVAILABLE"

    # The customer owes the rental plus the late days.
    assert priced.total_amount + fee == Decimal("6100.00")


def test_a_second_customer_is_refused_the_same_dates():
    """The conflict the first booking creates."""
    taken = Interval(PICKUP, RETURN)
    overlapping = Interval(datetime(2026, 9, 29, 9, 0), datetime(2026, 10, 1, 9, 0))

    result = check(overlapping, is_active=True, status="RENTED", blocked=[taken])
    assert result.ok is False
    assert result.reason == CONFLICT
    assert result.conflicts == (taken,)


def test_a_second_customer_may_book_after_it_comes_back():
    """Requirement 9's second worked example, through the real modules."""
    taken = Interval(PICKUP, RETURN)
    later = Interval(datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 6, 9, 0))

    result = check(later, is_active=True, status="RENTED", blocked=[taken])
    assert result.ok is True


def test_the_workflow_cannot_be_skipped():
    """A vehicle cannot be collected against a reservation nobody confirmed."""
    with pytest.raises(TransitionError):
        start_rental("PENDING")
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_domain_integration.py -q`
Expected: PASS, 4 tests. If the late-fee arithmetic disagrees, re-read Task 3's `late_charge` — two days late is exactly 48 hours, which is two late days at ₱800.

- [ ] **Step 3: Confirm the whole domain package is importable without a framework**

```bash
uv run python scripts/check-domain-purity.py
```
Expected: `pricing, availability, lifecycle` on the first line and `NONE` on the second. If a module is missing from that list, it was never created.

- [ ] **Step 4: Confirm the domain never reaches for the ORM**

```bash
grep -rn 'import' rental/domain/*.py | grep -vE 'from __future__|^rental/domain/[a-z_]*\.py:[0-9]+:(import (math|re)|from (dataclasses|datetime|decimal|typing))'
```
Expected: no output. Any hit is an import that should not be there — report it rather than deleting it, in case the design was wrong.

- [ ] **Step 5: Run the whole suite and commit**

```bash
uv run pytest -q
git status --porcelain rental/static/css/output.css
git add tests/test_domain_integration.py
git commit -m "test: walk the demo scenario through the domain modules"
```
Expected: 203 passed (199 + 4), stylesheet untouched.

---

## Phase 2 acceptance

- [ ] `rental/clock.py` is the only place a current time is produced; no `utcnow`, `date.today()` or `datetime.now()` survives elsewhere in `rental/`
- [ ] "Today's pickups" on the admin dashboard uses the business day, not the server's
- [ ] Subtracting a stored datetime from `clock.now()` does not raise
- [ ] `rental/domain/` imports no Flask, no SQLAlchemy and no model
- [ ] Every module in `rental/domain/` is importable and testable with no app context
- [ ] 3 days × ₱1,500 = ₱4,500, exactly
- [ ] Cost never decreases as duration grows, across the whole day boundary
- [ ] A daily-only vehicle (`hourly_rate is None`) rounds a part day up
- [ ] A zero rate produces a zero total rather than an error
- [ ] The summary lines sum to the total
- [ ] Touching intervals do not conflict; overlapping ones do, in both directions
- [ ] `inactive` and `maintenance` refuse regardless of dates and outrank a date conflict
- [ ] A RENTED vehicle is still bookable for a non-overlapping range
- [ ] Every illegal status transition raises `TransitionError`; an unknown status raises `KeyError`
- [ ] Completing a rental returns all three statuses in one value
- [ ] No route, template, form or stylesheet changed in this phase
- [ ] `uv run pytest -q` green with nothing skipped
