"""Generate a deterministic synthetic research facility.

Same seed, same estate, byte for byte — the estate hash goes into every manifest, so a
verifier can tell whether two runs were even talking about the same world.

Scale is chosen to make the headline incident real work rather than a toy: eight ULT
freezers, ~120 container-level units, and several thousand nested specimen records
across multiple studies with different criticality.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nightshift.common.canonical import sha256_of
from nightshift.common.clock import now_iso, shift_iso
from nightshift.schemas.core import (
    Container,
    DoorEvent,
    Freezer,
    MaintenanceRecord,
    Responder,
    Site,
    TemperatureReading,
)
from nightshift.schemas.enums import FaultClass, FreezerState, ResponderRole

if TYPE_CHECKING:
    from services.common.repository import Repository

EPOCH = "2026-08-26T00:00:00.000Z"
"""Pinned epoch for deterministic drills and the published reference proof.

Live runs pass ``epoch=None`` so the estate's telemetry is genuinely fresh — otherwise
N4 would (correctly) refuse every destination as stale the moment the fixture aged past
the freshness window. The structural layout is seeded either way; only timestamps move.
"""

STUDIES = [
    ("STUDY-ATLAS", "Atlas cohort", 1),
    ("STUDY-BOREAL", "Boreal longitudinal", 1),
    ("STUDY-CIRRUS", "Cirrus pilot", 2),
    ("STUDY-DELTA", "Delta method development", 3),
    ("STUDY-EMBER", "Ember biomarker panel", 2),
]

RESPONDER_NAMES = [
    ("Avery Lin", ResponderRole.LAB_TECH),
    ("Jordan Reyes", ResponderRole.LAB_TECH),
    ("Sam Okafor", ResponderRole.FACILITIES_TECH),
    ("Priya Nandini", ResponderRole.FACILITIES_TECH),
    ("Casey Moreau", ResponderRole.ONCALL_MANAGER),
    ("Dana Whitfield", ResponderRole.VENDOR_ENGINEER),
]
"""Invented names for a synthetic roster. No real person is represented."""


@dataclass
class FreezerSpec:
    fid: str
    zone: str
    total_slots: int
    occupancy: float
    temp_c: float
    backup_qualified: bool
    state: FreezerState = FreezerState.HEALTHY


DEFAULT_FREEZERS = [
    FreezerSpec("F-17", "B2", 144, 0.83, -79.4, False),
    FreezerSpec("F-03", "B2", 144, 0.72, -79.8, True),
    FreezerSpec("F-08", "B1", 120, 0.91, -80.2, True),
    FreezerSpec("F-11", "B1", 96, 0.55, -78.9, True),
    FreezerSpec("F-22", "C1", 144, 0.96, -79.1, True),
    FreezerSpec("F-24", "C1", 96, 0.34, -68.5, False),
    FreezerSpec("F-31", "C2", 120, 0.61, -80.6, True),
    FreezerSpec("F-35", "C2", 72, 0.88, -79.9, True),
]
"""Deliberately uneven.

F-03 and F-31 have real headroom, F-22 and F-08 are nearly full, F-24 is cold-ish but
sitting above the ULT ceiling so the kernel refuses it as a destination even though a
naive "has free slots" reading would pick it. F-11 is the small-but-empty option. That
spread is what makes placement an actual decision instead of a lookup.
"""


@dataclass
class EstateFixture:
    seed: int
    site: Site
    freezers: list[Freezer]
    containers: list[Container]
    readings: list[TemperatureReading]
    door_events: list[DoorEvent]
    responders: list[Responder]
    specimen_total: int = 0
    meta: dict[str, object] = field(default_factory=dict)

    def as_documents(self) -> dict[str, dict[str, dict]]:
        return {
            "sites": {self.site.id: self.site.model_dump(mode="json")},
            "freezers": {f.id: f.model_dump(mode="json") for f in self.freezers},
            "containers": {c.id: c.model_dump(mode="json") for c in self.containers},
            "readings": {r.id: r.model_dump(mode="json") for r in self.readings},
            "doorEvents": {e.id: e.model_dump(mode="json") for e in self.door_events},
            "responders": {r.id: r.model_dump(mode="json") for r in self.responders},
        }


def build_estate(
    seed: int = 20260826, *, epoch: str | None = None, specs: list[FreezerSpec] | None = None
) -> EstateFixture:
    """Build the estate. ``epoch=None`` anchors telemetry to now; pass one to pin it."""
    rng = random.Random(seed)
    specs = specs or DEFAULT_FREEZERS
    epoch = epoch or now_iso()

    site = Site(id="SITE-1", name="Northgate Research Core (synthetic)", timezone="America/Chicago")

    freezers: list[Freezer] = []
    containers: list[Container] = []
    readings: list[TemperatureReading] = []
    door_events: list[DoorEvent] = []
    specimen_total = 0
    container_seq = 0

    for spec in specs:
        occupied = round(spec.total_slots * spec.occupancy)
        maintenance = _maintenance_for(rng, spec, epoch)
        freezer = Freezer(
            id=spec.fid,
            site_id=site.id,
            label=f"ULT {spec.fid}",
            model=rng.choice(["Synthetic ULT-700", "Synthetic ULT-500", "Synthetic CryoLine-9"]),
            zone=spec.zone,
            setpoint_c=-80.0,
            alarm_high_c=-65.0,
            total_slots=spec.total_slots,
            occupied_slots=occupied,
            state=spec.state,
            current_temp_c=spec.temp_c,
            last_reading_at=epoch,
            is_backup_qualified=spec.backup_qualified,
            maintenance=maintenance,
        )
        freezers.append(freezer)

        # Container-level units only exist where material actually sits. F-17 carries
        # the headline load; the others carry enough to make capacity math non-trivial.
        n_containers = _container_count(spec, occupied)
        for _ in range(n_containers):
            container_seq += 1
            study_id, _label, base_priority = STUDIES[rng.randrange(len(STUDIES))]
            priority = min(3, max(1, base_priority + rng.choice([-1, 0, 0, 0, 1])))
            specimens = rng.choice([49, 81, 81, 100, 100, 121])
            specimen_total += specimens
            containers.append(
                Container(
                    id=f"C-{container_seq:04d}",
                    freezer_id=spec.fid,
                    slot_id=(
                        f"{spec.fid}-R{(container_seq % 12) + 1:02d}-P{(container_seq % 6) + 1}"
                    ),
                    kind=rng.choice(["box", "box", "cryobox", "rack"]),
                    study_id=study_id,
                    owner_ref=f"owner-{study_id.lower()}",
                    priority_class=priority,
                    specimen_count=specimens,
                    required_temp_c=-80.0,
                )
            )

        readings.extend(_baseline_readings(rng, spec, epoch))
        door_events.extend(_baseline_door_events(rng, spec, epoch))

    responders = [
        Responder(
            id=f"RESP-{i + 1:02d}",
            display_name=name,
            role=role,
            on_call=(i in (0, 2, 4)),
            site_id=site.id,
        )
        for i, (name, role) in enumerate(RESPONDER_NAMES)
    ]

    return EstateFixture(
        seed=seed,
        site=site,
        freezers=freezers,
        containers=containers,
        readings=readings,
        door_events=door_events,
        responders=responders,
        specimen_total=specimen_total,
        meta={
            "epoch": epoch,
            "container_count": len(containers),
            "freezer_count": len(freezers),
            "study_count": len(STUDIES),
        },
    )


def _container_count(spec: FreezerSpec, occupied: int) -> int:
    """F-17 holds the headline impact set; others hold a proportional share."""
    if spec.fid == "F-17":
        return 42
    return max(4, occupied // 12)


def _maintenance_for(rng: random.Random, spec: FreezerSpec, epoch: str) -> list[MaintenanceRecord]:
    records = []
    for i in range(rng.randrange(1, 4)):
        days_ago = rng.randrange(20, 400)
        fault = rng.choice(
            [
                FaultClass.DOOR_SEAL,
                FaultClass.CONTROLLER_FAULT,
                FaultClass.COMPRESSOR_FAILURE,
                FaultClass.UNKNOWN,
            ]
        )
        records.append(
            MaintenanceRecord(
                id=f"MNT-{spec.fid}-{i + 1}",
                freezer_id=spec.fid,
                occurred_at=shift_iso(epoch, -days_ago * 86_400),
                summary={
                    FaultClass.DOOR_SEAL: "Door gasket replaced during preventive service",
                    FaultClass.CONTROLLER_FAULT: "Controller firmware updated after alarm latch",
                    FaultClass.COMPRESSOR_FAILURE: (
                        "Stage-2 compressor serviced, refrigerant topped"
                    ),
                    FaultClass.UNKNOWN: "Routine preventive maintenance completed",
                }[fault],
                fault_class=fault,
            )
        )
    return sorted(records, key=lambda r: r.occurred_at)


def _baseline_readings(
    rng: random.Random, spec: FreezerSpec, epoch: str, hours: int = 6
) -> list[TemperatureReading]:
    """A quiet six-hour baseline at five-minute resolution."""
    out = []
    points = hours * 12
    for i in range(points):
        offset = -(points - i) * 300
        jitter = rng.uniform(-0.35, 0.35)
        out.append(
            TemperatureReading(
                id=f"R-{spec.fid}-{i:04d}",
                freezer_id=spec.fid,
                celsius=round(spec.temp_c + jitter, 2),
                recorded_at=shift_iso(epoch, offset),
            )
        )
    return out


def _baseline_door_events(rng: random.Random, spec: FreezerSpec, epoch: str) -> list[DoorEvent]:
    out = []
    for i in range(rng.randrange(0, 3)):
        opened_offset = -rng.randrange(3600, 20_000)
        duration = rng.randrange(20, 110)
        out.append(
            DoorEvent(
                id=f"D-{spec.fid}-{i:02d}",
                freezer_id=spec.fid,
                opened_at=shift_iso(epoch, opened_offset),
                closed_at=shift_iso(epoch, opened_offset + duration),
                duration_s=duration,
                badge_ref=f"badge-synthetic-{rng.randrange(100, 999)}",
            )
        )
    return out


def estate_hash(fixture: EstateFixture) -> str:
    """Stable identity for a generated estate. Goes into every manifest."""
    return sha256_of(
        {
            "seed": fixture.seed,
            "site": fixture.site.model_dump(mode="json"),
            "freezers": [f.model_dump(mode="json") for f in fixture.freezers],
            "containers": [c.model_dump(mode="json") for c in fixture.containers],
            "responders": [r.model_dump(mode="json") for r in fixture.responders],
        }
    )


def seed_repository(repo: Repository, fixture: EstateFixture) -> None:
    """Write the estate into a repository. Idempotent — safe to re-run."""
    for collection, docs in fixture.as_documents().items():
        for doc_id, doc in docs.items():
            repo.store.set(collection, doc_id, doc)
