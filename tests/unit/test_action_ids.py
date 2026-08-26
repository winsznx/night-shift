"""Semantic action IDs are the whole exactly-once story (PRD §16)."""

from __future__ import annotations

from nightshift.common.ids import (
    close_action_id,
    correlation_id,
    dispatch_action_id,
    opaque_token,
    reservation_action_id,
    transfer_action_id,
    work_order_action_id,
)
from nightshift.schemas.enums import FaultClass, ResponderRole, ResponsePhase


def test_reservation_id_is_stable_across_retries():
    a = reservation_action_id("INC-1", "F-03", "PG-1")
    b = reservation_action_id("INC-1", "F-03", "PG-1")
    assert a == b and len(a) == 64


def test_reservation_id_changes_with_destination():
    assert reservation_action_id("INC-1", "F-03", "PG-1") != reservation_action_id(
        "INC-1", "F-04", "PG-1"
    )


def test_reservation_id_changes_with_group():
    assert reservation_action_id("INC-1", "F-03", "PG-1") != reservation_action_id(
        "INC-1", "F-03", "PG-2"
    )


def test_work_order_id_keyed_on_fault_class():
    assert work_order_action_id("INC-1", "F-17", FaultClass.COMPRESSOR_FAILURE) != (
        work_order_action_id("INC-1", "F-17", FaultClass.DOOR_SEAL)
    )


def test_dispatch_id_keyed_on_phase_and_role():
    base = dispatch_action_id("INC-1", ResponsePhase.TRANSFER, ResponderRole.LAB_TECH)
    assert base != dispatch_action_id("INC-1", ResponsePhase.REPAIR, ResponderRole.LAB_TECH)
    assert base != dispatch_action_id(
        "INC-1", ResponsePhase.TRANSFER, ResponderRole.FACILITIES_TECH
    )


def test_transfer_id_keyed_on_container_and_slot():
    a = transfer_action_id("INC-1", "C-001", "F-03-SLOT-1")
    assert a != transfer_action_id("INC-1", "C-001", "F-03-SLOT-2")
    assert a != transfer_action_id("INC-1", "C-002", "F-03-SLOT-1")


def test_close_id_changes_with_reconciliation_hash():
    assert close_action_id("INC-1", "a" * 64) != close_action_id("INC-1", "b" * 64)


def test_action_ids_contain_no_time_component():
    """The defining property: identical inputs at different wall-clock times collide."""
    import time

    first = reservation_action_id("INC-1", "F-03", "PG-1")
    time.sleep(0.01)
    assert reservation_action_id("INC-1", "F-03", "PG-1") == first


def test_correlation_and_tokens_are_unique():
    assert len({correlation_id() for _ in range(200)}) == 200
    assert len({opaque_token() for _ in range(200)}) == 200
