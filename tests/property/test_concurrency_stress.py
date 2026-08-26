"""Capacity conservation under real concurrency, repeated.

A single two-thread test that passes once tells you very little — it can pass by timing
luck. These run many concurrent reservation attempts against a deliberately scarce
destination, repeatedly, and assert the exact arithmetic every time: the number that
commit is exactly the number the freezer could hold, never one more.

This is the guarantee the whole capacity story rests on, so it is worth stressing rather
than sampling.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from fixtures.estate import build_estate, seed_repository
from nightshift.common.config import get_settings
from nightshift.common.store import MemoryStore
from nightshift.safety_kernel.invariants import n1_capacity_conservation
from nightshift.schemas.enums import AgentName
from services.common.identity import PRINCIPAL_HEADER, issue_principal_token
from services.common.repository import Repository

SECRET = get_settings().agent_shared_secret


def _world():
    """One repository behind the capacity and inventory services, as in production."""
    store = MemoryStore()
    repo = Repository(store, namespace="stress")
    seed_repository(repo, build_estate())
    for agent in AgentName:
        store.set(
            "agentRevisions",
            f"{agent.value}@rev-1",
            {"agent": agent.value, "revision_id": "rev-1", "state": "ACTIVE"},
        )

    from services.capacity.app import app as capacity_app
    from services.incident_control.app import app as incident_app
    from services.inventory.app import app as inventory_app

    for app in (capacity_app, inventory_app, incident_app):
        app.state.repository = repo
    return repo, {
        "capacity": TestClient(capacity_app),
        "inventory": TestClient(inventory_app),
        "incident": TestClient(incident_app),
    }


def _headers(agent: AgentName) -> dict[str, str]:
    return {PRINCIPAL_HEADER: issue_principal_token(agent, "rev-1", SECRET)}


def _open_and_contain(clients, freezer: str = "F-17") -> str:
    opened = (
        clients["incident"]
        .post(
            "/v1/incidents",
            json={
                "site_id": "SITE-1",
                "freezer_id": freezer,
                "window_key": "stress",
                "severity": "SEV1",
                "source_event_id": "evt-stress",
                "namespace": "stress",
            },
            headers=_headers(AgentName.INGESTOR),
        )
        .json()
    )
    incident_id = opened["incident_id"]
    clients["inventory"].post(
        "/v1/holds",
        json={"incident_id": incident_id, "freezer_id": freezer, "reason": "stress"},
        headers=_headers(AgentName.INGESTOR),
    )
    return incident_id


@pytest.mark.parametrize("attempt", range(8))
def test_exactly_the_available_slots_commit_under_concurrency(attempt):
    """Twelve threads race for six slots in two-slot chunks. Exactly three must win."""
    repo, clients = _world()
    incident_id = _open_and_contain(clients)

    destination = "F-22"
    free = repo.get_freezer(destination).free_slots
    assert free == 6, "fixture drift: this test is calibrated to F-22 having 6 free slots"

    per_request = 2
    expected_winners = free // per_request  # 3
    racers = 12

    results: list[dict] = []
    lock = threading.Lock()
    barrier = threading.Barrier(racers)

    def attempt_reservation(index: int) -> None:
        barrier.wait()  # release every thread at once, not staggered
        response = (
            clients["capacity"]
            .post(
                "/v1/reservations",
                json={
                    "incident_id": incident_id,
                    "destination_freezer_id": destination,
                    "placement_group_id": f"PG-STRESS-{index}",
                    "slots": per_request,
                },
                headers=_headers(AgentName.CAPACITY_BROKER),
            )
            .json()
        )
        with lock:
            results.append(response)

    threads = [threading.Thread(target=attempt_reservation, args=(i,)) for i in range(racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    committed = [r for r in results if r["receipt"]["status"] == "COMMITTED"]
    refused = [r for r in results if r["receipt"]["status"] == "REFUSED"]
    total = sum(
        res.held_slots for res in repo.list_reservations(destination_freezer_id=destination)
    )

    assert len(results) == racers

    # SAFETY — must hold on every run, without exception. Overbooking by one slot is
    # the failure this whole subsystem exists to prevent.
    assert len(committed) <= expected_winners, (
        f"{len(committed)} reservations committed against room for {expected_winners}"
    )
    assert total <= free, f"{total} slots reserved against {free} available"
    assert n1_capacity_conservation(repo.load_kernel_state(incident_id)).holds
    assert all(r["decision"]["invariant"] == "N1" for r in refused)

    # LIVENESS — with jittered retry and phantom detection this is exact in practice.
    # It is asserted after the safety checks so a regression reads as "overbooked",
    # not merely "fewer than expected won".
    assert len(committed) == expected_winners, (
        f"expected exactly {expected_winners} winners for {free} slots at "
        f"{per_request} each, got {len(committed)}"
    )
    assert len(committed) + len(refused) == racers


def test_a_single_slot_is_won_exactly_once():
    """The sharpest case: one slot, twenty racers, one winner."""
    repo, clients = _world()
    incident_id = _open_and_contain(clients)

    # Shrink F-11 to exactly one free slot.
    freezer = repo.get_freezer("F-11")
    repo.put(
        "freezers",
        "F-11",
        freezer.model_copy(update={"occupied_slots": freezer.total_slots - 1}),
    )
    assert repo.get_freezer("F-11").free_slots == 1

    racers = 20
    results: list[dict] = []
    lock = threading.Lock()
    barrier = threading.Barrier(racers)

    def attempt_reservation(index: int) -> None:
        barrier.wait()
        response = (
            clients["capacity"]
            .post(
                "/v1/reservations",
                json={
                    "incident_id": incident_id,
                    "destination_freezer_id": "F-11",
                    "placement_group_id": f"PG-ONE-{index}",
                    "slots": 1,
                },
                headers=_headers(AgentName.CAPACITY_BROKER),
            )
            .json()
        )
        with lock:
            results.append(response)

    threads = [threading.Thread(target=attempt_reservation, args=(i,)) for i in range(racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    committed = [r for r in results if r["receipt"]["status"] == "COMMITTED"]
    assert len(committed) == 1, f"{len(committed)} threads won a single slot"
    reserved = sum(r.held_slots for r in repo.list_reservations(destination_freezer_id="F-11"))
    assert reserved <= 1
    assert n1_capacity_conservation(repo.load_kernel_state(incident_id)).holds


def test_the_same_semantic_reservation_from_many_threads_creates_one_effect():
    """Twenty threads, identical semantics. One effect, nineteen replayed receipts."""
    repo, clients = _world()
    incident_id = _open_and_contain(clients)

    racers = 20
    results: list[dict] = []
    lock = threading.Lock()
    barrier = threading.Barrier(racers)
    body = {
        "incident_id": incident_id,
        "destination_freezer_id": "F-31",
        "placement_group_id": "PG-IDENTICAL",
        "slots": 3,
    }

    def attempt_reservation() -> None:
        barrier.wait()
        response = (
            clients["capacity"]
            .post("/v1/reservations", json=body, headers=_headers(AgentName.CAPACITY_BROKER))
            .json()
        )
        with lock:
            results.append(response)

    threads = [threading.Thread(target=attempt_reservation) for _ in range(racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every thread gets COMMITTED, because every thread's action really did commit —
    # once. Exactly one of them created the effect; the rest were handed the original
    # receipt. That distinction is the whole exactly-once guarantee, so assert it
    # rather than the weaker "at least one succeeded".
    originals = [r for r in results if not r["duplicate_returned"]]
    replayed = [r for r in results if r["duplicate_returned"]]

    assert all(r["receipt"]["status"] == "COMMITTED" for r in results)
    assert len(originals) == 1, f"{len(originals)} threads created an effect, expected 1"
    assert len(replayed) == racers - 1
    assert len(repo.list_reservations(destination_freezer_id="F-31")) == 1
    assert len({r["receipt"]["action_id"] for r in results}) == 1
    assert len({r["receipt"]["effect_ref"] for r in results}) == 1
    assert n1_capacity_conservation(repo.load_kernel_state(incident_id)).holds
