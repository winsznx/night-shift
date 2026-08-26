"""Sensor ingestion and the bounded field simulator.

Two jobs that both sit at the boundary between the synthetic world and the real system:

* **Ingestor** — turns a sensor event into an incident, deterministically. No agent is
  prompted to start an incident; the incident opens because telemetry crossed a
  threshold, which is what makes "no operator prompt starts the agents" true.
* **Field simulator** — emits exactly the scan events the responder web interface emits,
  because Claude cannot physically move a freezer box. Every event it produces is
  labelled ``simulated: true`` and it only runs in demo and drill namespaces.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from nightshift.common.clock import now_iso, shift_iso
from nightshift.common.ids import deterministic_token, event_id
from nightshift.schemas.core import TemperatureReading
from nightshift.schemas.enums import AgentName, FreezerState
from services.common.effects import record_event
from services.common.identity import issue_principal_token
from services.common.repository import Repository


@dataclass
class FailureProfile:
    """How a freezer fails, as a temperature curve."""

    freezer_id: str
    start_c: float = -79.0
    peak_c: float = -38.0
    minutes: int = 90
    interval_s: int = 300
    recovers: bool = False
    """A recovering profile produces the D1 transient/door-excursion shape."""
    door_event_s: int | None = None
    """When set, a door opens this many seconds into the curve to explain the rise."""


def inject_failure(
    repo: Repository, profile: FailureProfile, *, now: str | None = None, seed: int = 7
) -> list[TemperatureReading]:
    """Write a warming curve into authoritative telemetry.

    This is the only way an incident starts. It writes readings the same way a real
    sensor integration would; nothing downstream knows the difference.
    """
    rng = random.Random(seed)
    now = now or now_iso()
    points = max(2, (profile.minutes * 60) // profile.interval_s)
    readings: list[TemperatureReading] = []

    for i in range(points + 1):
        offset = -(points - i) * profile.interval_s
        progress = i / points
        # A recovering profile rises then falls: a door excursion that closes.
        shape = 1 - abs(2 * progress - 1) if profile.recovers else progress**1.4
        celsius = profile.start_c + (profile.peak_c - profile.start_c) * shape
        celsius += rng.uniform(-0.3, 0.3)
        reading = TemperatureReading(
            id=f"R-{profile.freezer_id}-INJ-{i:04d}",
            freezer_id=profile.freezer_id,
            celsius=round(celsius, 2),
            recorded_at=shift_iso(now, offset),
            source="sensor",
        )
        readings.append(reading)

    from nightshift.common.store import Write

    repo.store.set_many(
        [
            Write(collection="readings", doc_id=r.id, data=r.model_dump(mode="json"))
            for r in readings
        ]
    )

    freezer = repo.get_freezer(profile.freezer_id)
    if freezer is not None:
        latest = readings[-1]
        repo.put(
            "freezers",
            freezer.id,
            freezer.model_copy(
                update={
                    "current_temp_c": latest.celsius,
                    "last_reading_at": latest.recorded_at,
                    "state": (
                        FreezerState.SUSPECT
                        if profile.recovers
                        else (
                            FreezerState.FAILED
                            if latest.celsius > freezer.alarm_high_c
                            else FreezerState.SUSPECT
                        )
                    ),
                }
            ),
        )

    if profile.door_event_s is not None:
        from nightshift.schemas.core import DoorEvent

        opened = shift_iso(now, -profile.minutes * 60 + profile.door_event_s)
        door = DoorEvent(
            id=f"D-{profile.freezer_id}-INJ",
            freezer_id=profile.freezer_id,
            opened_at=opened,
            closed_at=shift_iso(opened, 240),
            duration_s=240,
            badge_ref="badge-synthetic-inject",
        )
        repo.store.set("doorEvents", door.id, door.model_dump(mode="json"))

    return readings


def ingest_sensor_event(
    repo: Repository,
    *,
    site_id: str,
    freezer_id: str,
    source_event_id: str | None = None,
    namespace: str = "demo",
    window_key: str | None = None,
) -> dict[str, Any]:
    """Open or join an incident for a sensor reading. Idempotent on the dedupe key.

    Calls the real Incident Control route through ASGI, so the ingestor gets the same
    identity checks and the same dedupe behaviour as any other caller.
    """
    from fastapi.testclient import TestClient

    from nightshift.common.config import get_settings
    from services.common.identity import PRINCIPAL_HEADER
    from services.incident_control.app import app as incident_app

    incident_app.state.repository = repo
    client = TestClient(incident_app, raise_server_exceptions=False)
    token = issue_principal_token(AgentName.INGESTOR, "rev-1", get_settings().agent_shared_secret)

    freezer = repo.get_freezer(freezer_id)
    severity = "SEV2"
    if freezer is not None and freezer.current_temp_c > freezer.alarm_high_c:
        severity = "SEV1"

    # The dedupe key is derived from the real-world condition — site, freezer, and the
    # hour bucket — not from the delivery id. Two deliveries of the same condition join.
    window = window_key or (freezer.last_reading_at[:13] if freezer else now_iso()[:13])

    response: Any = client.post(
        "/v1/incidents",
        json={
            "site_id": site_id,
            "freezer_id": freezer_id,
            "window_key": window,
            "severity": severity,
            "source_event_id": source_event_id or event_id("sensor"),
            "namespace": namespace,
        },
        headers={PRINCIPAL_HEADER: token},
    )
    body: dict[str, Any] = response.json()
    return body


# --------------------------------------------------------------------------------------
# Field simulator
# --------------------------------------------------------------------------------------


@dataclass
class FieldSimulator:
    """Emits the scan events a responder's phone would emit.

    Labelled SIMULATED FIELD EVENTS everywhere it surfaces. Deterministic under a seed so
    a drill replays identically. Refuses to run outside a demo or drill namespace.
    """

    repo: Repository
    incident_id: str
    task_token: str
    responder_id: str
    seed: str = "nightshift"
    contradict_container: str | None = None
    """Drill hook for D14: scan this container at the wrong destination."""
    skip_containers: tuple[str, ...] = ()
    """Drill hook for D13: leave these containers behind, unresolved."""

    def __post_init__(self) -> None:
        if not self.repo.namespace.startswith(("demo", "drill", "test")):
            raise PermissionError(
                f"field simulator refuses to run in namespace {self.repo.namespace!r}; "
                "simulated events are permitted only in demo and drill namespaces"
            )

    def scan_signature(self, container_id: str, phase: str) -> str:
        return deterministic_token(self.seed, self.incident_id, container_id, phase)

    def pickup_payload(
        self,
        container_id: str,
        source: str,
        destination: str,
        slot: str,
        reservation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "container_id": container_id,
            "responder_id": self.responder_id,
            "source_freezer": source,
            "destination_freezer": destination,
            "destination_slot": slot,
            "reservation_id": reservation_id,
            "scan_signature": self.scan_signature(container_id, "pickup"),
            "simulated": True,
        }

    def destination_payload(self, container_id: str, destination: str, slot: str) -> dict[str, Any]:
        actual = destination
        if self.contradict_container == container_id:
            actual = self._wrong_destination(destination)
        return {
            "incident_id": self.incident_id,
            "container_id": container_id,
            "responder_id": self.responder_id,
            "destination_freezer_id": actual,
            "destination_slot": slot,
            "scan_signature": self.scan_signature(container_id, "destination"),
            "simulated": True,
        }

    def _wrong_destination(self, planned: str) -> str:
        others = sorted(
            f.id for f in self.repo.list_freezers() if f.id != planned and f.is_backup_qualified
        )
        return others[0] if others else planned

    def announce(self) -> None:
        record_event(
            self.repo,
            self.incident_id,
            kind="field",
            source="field-simulator",
            summary="SIMULATED FIELD EVENTS — responder scans are generated, not physical",
            detail={
                "simulator": True,
                "seed": self.seed,
                "responder_id": self.responder_id,
                "namespace": self.repo.namespace,
            },
        )
