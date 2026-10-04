"""What a rental costs. Pure arithmetic -- no app, no database, no clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from rental.domain.pricing import Duration, Quote, Rates, duration_between, late_charge, money, quote

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


def test_the_capped_hourly_remainder_is_described_as_a_day_not_hours():
    """The itemised line must match the amount it sits beside.

    A 23-hour rental's remainder is capped at the daily rate (see
    test_the_hourly_remainder_is_capped_at_a_full_day), so the amount is one
    full day's charge. Before this fix the line still read "0 day(s) + 23
    hour(s)" next to that amount -- a customer would see "0 days" beside a
    full day's charge. Once the cap applies the line must say what actually
    happened: a whole day was billed.
    """
    q = price(at(hours=23), hourly="250.00")
    label, detail, amount = q.lines[0]
    assert label == "Base rental"
    assert amount == Decimal("1500.00")
    assert detail == "₱1,500.00 x 1 day(s)"
    assert "hour(s)" not in detail


def test_an_uncapped_hourly_remainder_still_names_the_hours():
    """The uncapped wording is unchanged: it is accurate, so it stands."""
    q = price(at(hours=25), hourly="250.00")
    _, detail, _ = q.lines[0]
    assert detail == "₱1,500.00 x 1 day(s) + 1 hour(s)"


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
