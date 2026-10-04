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
