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
