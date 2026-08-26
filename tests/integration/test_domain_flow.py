"""Phase 2 gate: drive a confirmed-failure incident through the real domain APIs.

These run in-process against ``MemoryStore`` with FastAPI's TestClient, so they
exercise the actual routes, the actual identity checks, and the actual effect commit
sequence — not a parallel harness.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from fixtures.estate import build_estate, seed_repository
from nightshift.common.config import get_settings
from nightshift.common.store import MemoryStore
from nightshift.schemas.enums import AgentName, FaultClass, ResponderRole, ResponsePhase
from services.common.identity import PRINCIPAL_HEADER, issue_principal_token
from services.common.repository import Repository

SECRET = get_settings().agent_shared_secret


def principal_headers(agent: AgentName, revision: str = "rev-1") -> dict[str, str]:
    return {PRINCIPAL_HEADER: issue_principal_token(agent, revision, SECRET)}


@pytest.fixture
def world():
    """One shared repository behind every service app, like one Firestore behind Cloud Run."""
    store = MemoryStore()
    repo = Repository(store, namespace="test")
    seed_repository(repo, build_estate())
    for agent in AgentName:
        store.set(
            "agentRevisions",
            f"{agent.value}@rev-1",
            {"agent": agent.value, "revision_id": "rev-1", "state": "ACTIVE"},
        )

    from services.capacity.app import app as capacity_app
    from services.custody.app import app as custody_app
    from services.facilities.app import app as facilities_app
    from services.incident_control.app import app as incident_app
    from services.inventory.app import app as inventory_app
    from services.telemetry.app import app as telemetry_app

    clients = {}
    for name, app in [
        ("telemetry", telemetry_app),
        ("inventory", inventory_app),
        ("capacity", capacity_app),
        ("facilities", facilities_app),
        ("custody", custody_app),
        ("incident", incident_app),
    ]:
        app.state.repository = repo
        clients[name] = TestClient(app)
    return repo, clients


def _open_incident(clients) -> str:
    r = clients["incident"].post(
        "/v1/incidents",
        json={
            "site_id": "SITE-1",
            "freezer_id": "F-17",
            "window_key": "2026-08-26T02",
            "severity": "SEV1",
            "source_event_id": "evt-sensor-1",
            "namespace": "test",
        },
        headers=principal_headers(AgentName.INGESTOR),
    )
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


def _contain(clients, incident_id: str):
    return clients["inventory"].post(
        "/v1/holds",
        json={"incident_id": incident_id, "freezer_id": "F-17", "reason": "sustained warming"},
        headers=principal_headers(AgentName.INGESTOR),
    )


def _snapshot_impact(clients, repo, incident_id: str):
    listing = clients["inventory"].get(
        "/v1/freezers/F-17/impacted",
        params={"incident_id": incident_id},
        headers=principal_headers(AgentName.IMPACT_ANALYST),
    ).json()
    return clients["inventory"].post(
        "/v1/impact",
        json={
            "incident_id": incident_id,
            "container_ids": [c["container_id"] for c in listing["containers"]],
            "inventory_complete": listing["enumeration_complete"],
        },
        headers=principal_headers(AgentName.INGESTOR),
    )


# --------------------------------------------------------------------------------------


def test_duplicate_sensor_delivery_yields_one_incident(world):
    """D3."""
    _repo, clients = world
    first = _open_incident(clients)
    body = {
        "site_id": "SITE-1", "freezer_id": "F-17", "window_key": "2026-08-26T02",
        "severity": "SEV1", "source_event_id": "evt-sensor-1-redelivered", "namespace": "test",
    }
    r = clients["incident"].post("/v1/incidents", json=body,
                                 headers=principal_headers(AgentName.INGESTOR))
    assert r.json()["joined_existing"] is True
    assert r.json()["incident_id"] == first


def test_containment_hold_blocks_normal_operations(world):
    """N13."""
    repo, clients = world
    incident_id = _open_incident(clients)
    assert _contain(clients, incident_id).json()["receipt"]["status"] == "COMMITTED"

    hold = clients["inventory"].get(
        "/v1/holds/F-17", headers=principal_headers(AgentName.IMPACT_ANALYST)
    ).json()
    assert hold["hold_active"] is True
    assert hold["normal_operations_permitted"] is False
    assert repo.get_freezer("F-17").state.value == "FAILED"


def test_containment_hold_is_idempotent(world):
    """N2 on a non-reservation effect."""
    _repo, clients = world
    incident_id = _open_incident(clients)
    first = _contain(clients, incident_id).json()
    second = _contain(clients, incident_id).json()
    assert first["duplicate_returned"] is False
    assert second["duplicate_returned"] is True
    assert first["receipt"]["action_id"] == second["receipt"]["action_id"]
    assert first["receipt"]["effect_ref"] == second["receipt"]["effect_ref"]


def test_impact_snapshot_is_computed_from_fixture_inventory(world):
    repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    result = _snapshot_impact(clients, repo, incident_id).json()
    assert result["receipt"]["status"] == "COMMITTED"

    impact = repo.get_impact(incident_id)
    assert impact is not None
    assert len(impact.container_ids) == 42
    assert impact.specimen_total == 3741
    assert len(impact.placement_groups) >= 2
    assert sum(g.slot_count for g in impact.placement_groups) == 42


def test_impact_snapshot_refused_when_inventory_incomplete(world):
    """D15."""
    _repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    r = clients["inventory"].post(
        "/v1/impact",
        json={"incident_id": incident_id, "container_ids": ["C-0001"],
              "inventory_complete": False},
        headers=principal_headers(AgentName.INGESTOR),
    ).json()
    assert r["receipt"]["status"] == "REFUSED"
    assert r["decision"]["invariant"] == "N11"


def test_reservation_is_idempotent_across_retries(world):
    """D5: the effect commits, the response is lost, the retry finds the receipt."""
    repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    _snapshot_impact(clients, repo, incident_id)
    group = repo.get_impact(incident_id).placement_groups[0]

    body = {
        "incident_id": incident_id, "destination_freezer_id": "F-31",
        "placement_group_id": group.id, "slots": group.slot_count,
    }
    hdr = principal_headers(AgentName.CAPACITY_BROKER)
    first = clients["capacity"].post("/v1/reservations", json=body, headers=hdr).json()
    assert first["receipt"]["status"] == "COMMITTED"
    assert first["duplicate_returned"] is False

    for _ in range(5):
        again = clients["capacity"].post("/v1/reservations", json=body, headers=hdr).json()
        assert again["duplicate_returned"] is True
        assert again["receipt"]["effect_ref"] == first["receipt"]["effect_ref"]

    assert len(repo.list_reservations(incident_id=incident_id)) == 1


def test_concurrent_reservations_cannot_overbook(world):
    """D4: two incidents race for the same destination; capacity is conserved."""
    repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    _snapshot_impact(clients, repo, incident_id)

    # F-22 has only 6 free slots in the fixture. Two 4-slot asks cannot both win.
    free = repo.get_freezer("F-22").free_slots
    assert free == 6

    hdr = principal_headers(AgentName.CAPACITY_BROKER)
    results: list[dict] = []
    lock = threading.Lock()

    def attempt(group_suffix: str) -> None:
        r = clients["capacity"].post(
            "/v1/reservations",
            json={
                "incident_id": incident_id, "destination_freezer_id": "F-22",
                "placement_group_id": f"PG-RACE-{group_suffix}", "slots": 4,
            },
            headers=hdr,
        ).json()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=attempt, args=(s,)) for s in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    committed = [r for r in results if r["receipt"]["status"] == "COMMITTED"]
    refused = [r for r in results if r["receipt"]["status"] == "REFUSED"]
    assert len(committed) == 1, results
    assert len(refused) == 1
    assert refused[0]["decision"]["invariant"] == "N1"

    total_reserved = sum(
        r.slots for r in repo.list_reservations(destination_freezer_id="F-22")
    )
    assert total_reserved <= free


def test_work_order_and_dispatch_are_idempotent(world):
    """D6."""
    repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    hdr = principal_headers(AgentName.DISPATCH_AGENT)

    wo_body = {
        "incident_id": incident_id, "freezer_id": "F-17",
        "fault_class": FaultClass.COMPRESSOR_FAILURE.value,
        "summary": "Sustained warming; compressor suspected",
    }
    a = clients["facilities"].post("/v1/work-orders", json=wo_body, headers=hdr).json()
    b = clients["facilities"].post("/v1/work-orders", json=wo_body, headers=hdr).json()
    assert a["receipt"]["status"] == "COMMITTED" and b["duplicate_returned"] is True
    assert len(repo.list_work_orders(incident_id)) == 1

    d_body = {
        "incident_id": incident_id, "responder_role": ResponderRole.LAB_TECH.value,
        "response_phase": ResponsePhase.TRANSFER.value, "container_ids": ["C-0001"],
    }
    c = clients["facilities"].post("/v1/dispatches", json=d_body, headers=hdr).json()
    d = clients["facilities"].post("/v1/dispatches", json=d_body, headers=hdr).json()
    assert c["receipt"]["status"] == "COMMITTED" and d["duplicate_returned"] is True
    assert len(repo.list_dispatches(incident_id)) == 1
    assert c["responder_path"].startswith("/respond/")


def test_forbidden_tool_is_denied_at_the_service(world):
    """D11: the Dispatch Agent reaching for inventory is refused server-side."""
    _repo, clients = world
    incident_id = _open_incident(clients)
    r = clients["inventory"].get(
        "/v1/freezers/F-17/impacted",
        params={"incident_id": incident_id},
        headers=principal_headers(AgentName.DISPATCH_AGENT),
    )
    assert r.status_code == 403
    detail = r.json()
    assert detail["invariant"] == "N7"
    assert detail["denial_reason"] == "IDENTITY_NOT_PERMITTED"
    assert detail["detail"]["required_domain"] == "inventory.scoped_read"


def test_sensitive_study_notes_are_unreachable_by_every_operational_agent(world):
    """The route exists and returns something real, and no agent can call it."""
    _repo, clients = world
    for agent in [
        AgentName.COMMANDER, AgentName.SIGNAL_INVESTIGATOR, AgentName.IMPACT_ANALYST,
        AgentName.CAPACITY_BROKER, AgentName.DISPATCH_AGENT, AgentName.CUSTODY_AGENT,
    ]:
        r = clients["inventory"].get(
            "/v1/study-notes/C-0001", headers=principal_headers(agent)
        )
        assert r.status_code == 403, f"{agent.value} unexpectedly reached study notes"


def test_unauthenticated_calls_hold_no_authority(world):
    _repo, clients = world
    r = clients["capacity"].post(
        "/v1/reservations",
        json={"incident_id": "INC-X", "destination_freezer_id": "F-03",
              "placement_group_id": "PG-1", "slots": 1},
    )
    assert r.status_code == 403
    assert r.json()["invariant"] == "N7"


def test_forged_principal_token_is_rejected(world):
    _repo, clients = world
    r = clients["capacity"].get(
        "/v1/capacity/F-03",
        headers={PRINCIPAL_HEADER: "capacity-broker:rev-1:9999999999:deadbeef"},
    )
    assert r.status_code == 401


def test_vendor_message_carrying_specimen_metadata_is_blocked(world):
    """The deterministic egress filter, independent of Model Armor."""
    _repo, clients = world
    incident_id = _open_incident(clients)
    r = clients["facilities"].post(
        "/v1/vendor-messages",
        json={
            "incident_id": incident_id, "work_order_id": "WO-1",
            "message": "Please retrieve container C-0001 from STUDY-ATLAS for analysis.",
        },
        headers=principal_headers(AgentName.DISPATCH_AGENT),
    ).json()
    assert r["blocked"] is True
    assert "container identifier" in r["findings"]
    assert "study identifier" in r["findings"]


def test_clean_vendor_message_is_sent(world):
    _repo, clients = world
    incident_id = _open_incident(clients)
    r = clients["facilities"].post(
        "/v1/vendor-messages",
        json={
            "incident_id": incident_id, "work_order_id": "WO-1",
            "message": "ULT F-17, model Synthetic ULT-700, zone B2, not holding setpoint. "
                       "Requesting compressor service.",
        },
        headers=principal_headers(AgentName.DISPATCH_AGENT),
    ).json()
    assert r["sent"] is True and r["blocked"] is False


def test_premature_close_is_refused_and_full_reconciliation_permits_it(world):
    """N5/N6 end to end through the real routes."""
    repo, clients = world
    incident_id = _open_incident(clients)
    _contain(clients, incident_id)
    _snapshot_impact(clients, repo, incident_id)

    cmd = principal_headers(AgentName.COMMANDER)
    early = clients["incident"].post(
        f"/v1/incidents/{incident_id}/close",
        json={"incident_id": incident_id, "reason": "looks done"}, headers=cmd,
    ).json()
    assert early["receipt"]["status"] == "REFUSED"
    assert early["decision"]["invariant"] == "N6"

    # Resolve every container the honest way.
    custody_hdr = principal_headers(AgentName.CUSTODY_AGENT)
    impact = repo.get_impact(incident_id)
    for cid in impact.container_ids:
        clients["custody"].post(
            "/v1/exceptions",
            json={"incident_id": incident_id, "container_id": cid,
                  "reason": "test disposition", "disposition": "QUARANTINED"},
            headers=custody_hdr,
        )

    # Walk the legal path while the hold is still active — CONTAINED requires it.
    # Everything was dispositioned by hand rather than transferred, so the incident
    # escalates and then reconciles: a real route through the graph, not a shortcut.
    for target in ["CONFIRMED", "CONTAINED", "ESCALATED"]:
        step = clients["incident"].post(
            f"/v1/incidents/{incident_id}/transitions",
            json={"incident_id": incident_id, "to_state": target, "reason": "test walk"},
            headers=cmd,
        ).json()
        assert step["receipt"]["status"] == "COMMITTED", (target, step["decision"])

    # Only now can the hold release, and only with a demonstrated recovery window.
    from nightshift.common.clock import shift_iso

    now = repo.get_incident(incident_id).last_evidence_at
    readings = [
        {"recorded_at": shift_iso(now, -2400), "celsius": -80.0},
        {"recorded_at": shift_iso(now, -60), "celsius": -80.2},
    ]
    release = clients["inventory"].post(
        "/v1/holds/F-17/release",
        json={"incident_id": incident_id, "freezer_id": "F-17",
              "validation_readings": readings},
        headers=principal_headers(AgentName.INGESTOR),
    ).json()
    assert release["receipt"]["status"] == "COMMITTED", release["decision"]

    step = clients["incident"].post(
        f"/v1/incidents/{incident_id}/transitions",
        json={"incident_id": incident_id, "to_state": "RECONCILING", "reason": "test walk"},
        headers=cmd,
    ).json()
    assert step["receipt"]["status"] == "COMMITTED", step["decision"]

    final = clients["incident"].post(
        f"/v1/incidents/{incident_id}/close",
        json={"incident_id": incident_id, "reason": "all containers reconciled"}, headers=cmd,
    ).json()
    assert final["receipt"]["status"] == "COMMITTED", final["decision"]
    assert repo.get_incident(incident_id).state.value == "CLOSED"
    assert repo.get_incident(incident_id).unresolved_count == 0


def test_transition_guards_refuse_unsupported_states(world):
    _repo, clients = world
    incident_id = _open_incident(clients)
    cmd = principal_headers(AgentName.COMMANDER)
    r = clients["incident"].post(
        f"/v1/incidents/{incident_id}/transitions",
        json={"incident_id": incident_id, "to_state": "CLOSED", "reason": "skip ahead"},
        headers=cmd,
    ).json()
    assert r["receipt"]["status"] == "REFUSED"


def test_commander_cannot_reserve_capacity(world):
    _repo, clients = world
    r = clients["capacity"].post(
        "/v1/reservations",
        json={"incident_id": "INC-X", "destination_freezer_id": "F-03",
              "placement_group_id": "PG-1", "slots": 1},
        headers=principal_headers(AgentName.COMMANDER),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["required_domain"] == "capacity.write"
