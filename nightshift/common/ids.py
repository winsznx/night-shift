"""Semantic action IDs and correlation IDs (PRD §16).

The whole exactly-once story rests on one rule: **a semantic action ID never contains a
timestamp, a retry counter, or a request ID.** Two callers describing the same real-world
effect must derive byte-identical IDs, so the second one finds the first one's receipt.
"""

from __future__ import annotations

import secrets
import uuid

from nightshift.common.canonical import sha256_hex
from nightshift.schemas.enums import ActionType, FaultClass, ResponderRole, ResponsePhase

__all__ = [
    "action_id_for",
    "close_action_id",
    "containment_action_id",
    "correlation_id",
    "dispatch_action_id",
    "event_id",
    "impact_action_id",
    "opaque_token",
    "release_hold_action_id",
    "reservation_action_id",
    "scan_action_id",
    "transfer_action_id",
    "work_order_action_id",
]


def reservation_action_id(incident_id: str, destination_freezer_id: str, group_id: str) -> str:
    return sha256_hex("reservation", incident_id, destination_freezer_id, group_id)


def work_order_action_id(incident_id: str, failed_freezer_id: str, fault_class: FaultClass) -> str:
    return sha256_hex("work_order", incident_id, failed_freezer_id, str(fault_class.value))


def dispatch_action_id(
    incident_id: str, response_phase: ResponsePhase, responder_role: ResponderRole
) -> str:
    return sha256_hex("dispatch", incident_id, str(response_phase.value), str(responder_role.value))


def transfer_action_id(incident_id: str, container_id: str, destination_slot_id: str) -> str:
    return sha256_hex("transfer", incident_id, container_id, destination_slot_id)


def close_action_id(incident_id: str, reconciliation_snapshot_hash: str) -> str:
    return sha256_hex("close", incident_id, reconciliation_snapshot_hash)


def containment_action_id(incident_id: str, freezer_id: str) -> str:
    return sha256_hex("containment", incident_id, freezer_id)


def release_hold_action_id(incident_id: str, freezer_id: str) -> str:
    return sha256_hex("release_hold", incident_id, freezer_id)


def impact_action_id(incident_id: str, snapshot_hash: str) -> str:
    return sha256_hex("impact", incident_id, snapshot_hash)


def scan_action_id(incident_id: str, container_id: str, phase: str) -> str:
    """Pickup and destination scans are separately idempotent (D12 duplicate scan)."""
    return sha256_hex("scan", incident_id, container_id, phase)


def release_reservation_action_id(incident_id: str, reservation_id: str) -> str:
    return sha256_hex("release_reservation", incident_id, reservation_id)


def transition_action_id(incident_id: str, to_state: str, cause_key: str) -> str:
    return sha256_hex("transition", incident_id, to_state, cause_key)


def repair_status_action_id(incident_id: str, work_order_id: str, status: str) -> str:
    return sha256_hex("repair_status", incident_id, work_order_id, status)


_DERIVERS = {
    ActionType.CAPACITY_RESERVE: reservation_action_id,
    ActionType.WORK_ORDER_CREATE: work_order_action_id,
    ActionType.DISPATCH_RESPONDER: dispatch_action_id,
    ActionType.CUSTODY_COMMIT: transfer_action_id,
    ActionType.INCIDENT_CLOSE: close_action_id,
    ActionType.CONTAINMENT_HOLD: containment_action_id,
    ActionType.RELEASE_HOLD: release_hold_action_id,
    ActionType.IMPACT_SNAPSHOT: impact_action_id,
    ActionType.CAPACITY_RELEASE: release_reservation_action_id,
    ActionType.REPAIR_STATUS: repair_status_action_id,
    ActionType.INCIDENT_TRANSITION: transition_action_id,
}


def action_id_for(action_type: ActionType, *args: object) -> str:
    """Dispatch to the deriver for ``action_type``.

    Kept as an explicit table rather than string formatting so adding an effectful
    action without giving it a semantic key is a hard failure, not a silent one.
    """
    try:
        deriver = _DERIVERS[action_type]
    except KeyError:  # pragma: no cover - guarded by the ActionType enum
        raise KeyError(f"no semantic action id deriver registered for {action_type}") from None
    return deriver(*args)  # type: ignore[arg-type]


def dedupe_key(site_id: str, freezer_id: str, window_key: str) -> str:
    """Sensor-event dedupe key for D3 (same source event delivered twice)."""
    return sha256_hex("incident_dedupe", site_id, freezer_id, window_key)


def correlation_id(prefix: str = "corr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def event_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def opaque_token(nbytes: int = 24) -> str:
    """Unguessable responder task token (threat model: forged responder event)."""
    return secrets.token_urlsafe(nbytes)


def deterministic_token(seed: str, *parts: str) -> str:
    """Seeded token for reproducible drills. Never used for live operational tokens."""
    return sha256_hex("token", seed, *parts)[:32]
