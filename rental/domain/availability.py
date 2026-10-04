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

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

#: A vehicle withdrawn from the fleet. Not on offer at all.
INACTIVE = "inactive"
#: Off the road. Refused whatever the dates, per the requirements.
MAINTENANCE = "maintenance"
#: Free in principle, but already spoken for over the requested range.
CONFLICT = "conflict"


@dataclass(frozen=True, order=True)
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
