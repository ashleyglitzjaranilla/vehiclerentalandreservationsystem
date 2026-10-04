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


def money(value: Decimal | int | str) -> Decimal:
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


def _hourly_remainder_hit_the_daily_cap(
    duration: Duration, daily_rate: Decimal, hourly_rate: Decimal
) -> bool:
    """True when the part-day hourly charge was capped at a full day's rate.

    When this is true the remainder is billed as a whole day, not by the hour,
    and the summary line must say so -- otherwise it names an hour count next
    to an amount that is not an hourly charge at all.
    """
    return money(hourly_rate * duration.extra_hours) > money(daily_rate)


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

    if (
        hourly_rate is None
        or duration.extra_hours == 0
        or _hourly_remainder_hit_the_daily_cap(duration, daily_rate, hourly_rate)
    ):
        # Either there is no hourly component, there is no remainder to
        # describe, or the remainder was capped at a full day's rate -- in
        # every one of these cases the amount below is exactly
        # `daily_rate x billable_days`, so that is what the line must say.
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
