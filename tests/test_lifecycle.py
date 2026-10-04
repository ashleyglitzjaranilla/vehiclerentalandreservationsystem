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

# `rental/domain/` may never import `rental.models` -- that is what
# scripts/check-domain-purity.py (and tests/test_domain_purity.py) enforce.
# But this test module lives in tests/, where importing it is not just legal
# but the whole point: lifecycle.py duplicates phase 1's status strings as
# literals rather than importing them, precisely to stay pure, and nothing
# else notices if the two copies drift apart. These tests are that guard.
from rental import models
from rental.domain.availability import MAINTENANCE as AVAILABILITY_MAINTENANCE_REASON


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


# -- the drift guard ---------------------------------------------------------
#
# lifecycle.py cannot import rental.models (that would break domain purity),
# so it re-spells RESERVATION_STATUSES, RENTAL_STATUSES and VEHICLE_STATUSES
# as literals. The reviewer's phase-2 regression: renaming "REJECTED" to
# "DECLINED" throughout rental/models.py, admin/fleet.py, reports.py and
# tests/test_models.py, while lifecycle.py went on speaking "REJECTED" --
# and all 204 tests passed, because nothing compared the two vocabularies.
# The phase-3 failure this allows: reject_reservation() returns
# StateChange("REJECTED", ...); the route writes "REJECTED" into a column
# whose vocabulary no longer contains it; the reservation renders with no
# badge and vanishes from every status filter, raising nothing.


def test_reservation_vocabulary_matches_models():
    """lifecycle's reservation statuses must be exactly models.RESERVATION_STATUSES."""
    lifecycle_only = set(RESERVATION_TRANSITIONS) - set(models.RESERVATION_STATUSES)
    models_only = set(models.RESERVATION_STATUSES) - set(RESERVATION_TRANSITIONS)
    assert not lifecycle_only and not models_only, (
        "lifecycle.RESERVATION_TRANSITIONS and models.RESERVATION_STATUSES have "
        f"drifted apart -- only in lifecycle.py: {sorted(lifecycle_only) or 'none'}; "
        f"only in models.py: {sorted(models_only) or 'none'}"
    )


def test_rental_vocabulary_matches_models():
    """lifecycle's rental statuses must be exactly models.RENTAL_STATUSES."""
    lifecycle_only = set(RENTAL_TRANSITIONS) - set(models.RENTAL_STATUSES)
    models_only = set(models.RENTAL_STATUSES) - set(RENTAL_TRANSITIONS)
    assert not lifecycle_only and not models_only, (
        "lifecycle.RENTAL_TRANSITIONS and models.RENTAL_STATUSES have drifted "
        f"apart -- only in lifecycle.py: {sorted(lifecycle_only) or 'none'}; "
        f"only in models.py: {sorted(models_only) or 'none'}"
    )


def test_every_vehicle_status_the_lifecycle_can_emit_is_a_real_status():
    """Every StateChange.vehicle_status the five operations can produce must be
    a member of models.VEHICLE_STATUSES -- a route trusts these literally."""
    emitted = {
        confirm_reservation("PENDING").vehicle_status,
        reject_reservation("PENDING").vehicle_status,
        cancel_reservation("CONFIRMED").vehicle_status,
        start_rental("CONFIRMED").vehicle_status,
        complete_rental("CONFIRMED", "ACTIVE").vehicle_status,
    }
    unknown = emitted - set(models.VEHICLE_STATUSES)
    assert not unknown, (
        "lifecycle.py emits a vehicle status models.VEHICLE_STATUSES does not "
        f"recognise: {sorted(unknown)} (known: {models.VEHICLE_STATUSES})"
    )


def test_the_maintenance_reason_constant_names_a_real_vehicle_status():
    """availability.MAINTENANCE is spelled lower-case ("maintenance") while
    models.VEHICLE_STATUSES spells the same status upper-case ("MAINTENANCE").
    This asserts the two still name the same status, case aside."""
    assert AVAILABILITY_MAINTENANCE_REASON.upper() in models.VEHICLE_STATUSES, (
        f"availability.MAINTENANCE = {AVAILABILITY_MAINTENANCE_REASON!r} does not "
        f"correspond to any status in models.VEHICLE_STATUSES = {models.VEHICLE_STATUSES}"
    )
