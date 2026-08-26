"""Repository: documents in, ``KernelState`` out.

One job — be the single place that knows how authoritative state is laid out, so the
kernel can stay a pure function over a snapshot and the services can stay thin.

Namespace isolation is done with a collection prefix rather than a field filter. A
drill physically cannot read operational documents, which is a stronger guarantee than
remembering to add ``where namespace == ...`` to every query (PRD §27).
"""

from __future__ import annotations

from typing import Any

from nightshift.common.store import Store, TxnContext, build_store
from nightshift.safety_kernel.world import KernelState
from nightshift.schemas.core import (
    ActionReceipt,
    Container,
    ContainmentHold,
    Dispatch,
    DoorEvent,
    Freezer,
    ImpactSnapshot,
    Incident,
    IncidentEvent,
    Reservation,
    Responder,
    Site,
    TemperatureReading,
    Transfer,
    WorkOrder,
)

COLLECTIONS = {
    "sites": Site,
    "freezers": Freezer,
    "readings": TemperatureReading,
    "doorEvents": DoorEvent,
    "containers": Container,
    "responders": Responder,
    "incidents": Incident,
    "impactSnapshots": ImpactSnapshot,
    "receipts": ActionReceipt,
    "transfers": Transfer,
    "incidentEvents": IncidentEvent,
    "reservations": Reservation,
    "workOrders": WorkOrder,
    "dispatches": Dispatch,
    "holds": ContainmentHold,
}


class Repository:
    def __init__(self, store: Store, namespace: str = "demo") -> None:
        self.store = store
        self.namespace = namespace

    @classmethod
    def create(
        cls, backend: str, *, project: str = "", database: str = "(default)",
        namespace: str = "demo",
    ) -> Repository:
        prefix = f"ns_{namespace}__"
        return cls(build_store(backend, project=project, database=database, prefix=prefix),
                   namespace)

    # -- typed accessors -----------------------------------------------------------

    def get_site(self, site_id: str) -> Site | None:
        return self._get("sites", site_id, Site)

    def get_freezer(self, freezer_id: str) -> Freezer | None:
        return self._get("freezers", freezer_id, Freezer)

    def list_freezers(self) -> list[Freezer]:
        return [Freezer(**d) for d in self.store.query("freezers")]

    def get_container(self, container_id: str) -> Container | None:
        return self._get("containers", container_id, Container)

    def list_containers(self, **filters: Any) -> list[Container]:
        return [Container(**d) for d in self.store.query("containers", **filters)]

    def get_incident(self, incident_id: str) -> Incident | None:
        return self._get("incidents", incident_id, Incident)

    def list_incidents(self, **filters: Any) -> list[Incident]:
        return [Incident(**d) for d in self.store.query("incidents", **filters)]

    def get_reservation(self, reservation_id: str) -> Reservation | None:
        return self._get("reservations", reservation_id, Reservation)

    def get_receipt(self, action_id: str) -> ActionReceipt | None:
        return self._get("receipts", action_id, ActionReceipt)

    def get_hold(self, freezer_id: str) -> ContainmentHold | None:
        return self._get("holds", freezer_id, ContainmentHold)

    def get_impact(self, incident_id: str) -> ImpactSnapshot | None:
        rows = self.store.query("impactSnapshots", incident_id=incident_id)
        return ImpactSnapshot(**rows[0]) if rows else None

    def list_transfers(self, incident_id: str) -> list[Transfer]:
        return [Transfer(**d) for d in self.store.query("transfers", incident_id=incident_id)]

    def list_readings(self, freezer_id: str) -> list[TemperatureReading]:
        rows = self.store.query("readings", freezer_id=freezer_id)
        return sorted((TemperatureReading(**d) for d in rows), key=lambda r: r.recorded_at)

    def list_door_events(self, freezer_id: str) -> list[DoorEvent]:
        rows = self.store.query("doorEvents", freezer_id=freezer_id)
        return sorted((DoorEvent(**d) for d in rows), key=lambda e: e.opened_at)

    def list_responders(self, **filters: Any) -> list[Responder]:
        return [Responder(**d) for d in self.store.query("responders", **filters)]

    def list_events(self, incident_id: str) -> list[IncidentEvent]:
        rows = self.store.query("incidentEvents", incident_id=incident_id)
        return sorted((IncidentEvent(**d) for d in rows), key=lambda e: (e.occurred_at, e.event_id))

    def list_receipts(self, incident_id: str) -> list[ActionReceipt]:
        rows = self.store.query("receipts", incident_id=incident_id)
        return sorted((ActionReceipt(**d) for d in rows), key=lambda r: r.committed_at)

    def list_work_orders(self, incident_id: str) -> list[WorkOrder]:
        return [WorkOrder(**d) for d in self.store.query("workOrders", incident_id=incident_id)]

    def list_dispatches(self, incident_id: str) -> list[Dispatch]:
        return [Dispatch(**d) for d in self.store.query("dispatches", incident_id=incident_id)]

    def list_reservations(self, **filters: Any) -> list[Reservation]:
        return [Reservation(**d) for d in self.store.query("reservations", **filters)]

    # -- writes --------------------------------------------------------------------

    def put(self, collection: str, doc_id: str, model: Any) -> None:
        data = model.model_dump(mode="json") if hasattr(model, "model_dump") else dict(model)
        self.store.set(collection, doc_id, data)

    def append_event(self, event: IncidentEvent) -> None:
        self.put("incidentEvents", event.event_id, event)

    def revision_states(self) -> dict[str, str]:
        rows = self.store.query("agentRevisions")
        return {f"{r['agent']}@{r['revision_id']}": r["state"] for r in rows}

    def memory_notes(self, incident_id: str) -> list[dict[str, Any]]:
        return self.store.query("memoryNotes", incident_id=incident_id)

    # -- kernel state --------------------------------------------------------------

    def load_kernel_state(
        self, incident_id: str, *, unavailable: frozenset[str] = frozenset()
    ) -> KernelState:
        """Assemble the snapshot the kernel reasons over.

        Reservations are loaded for *all* incidents, not just this one: capacity
        conservation is a property of the destination freezer, not of one incident,
        which is exactly what makes concurrent-incident contention detectable.
        """
        incident = self.get_incident(incident_id)
        return KernelState(
            incident=incident,
            freezers={f.id: f for f in self.list_freezers()},
            containers={c.id: c for c in self.list_containers()},
            reservations={r.id: r for r in self.list_reservations()},
            work_orders={w.id: w for w in self.list_work_orders(incident_id)},
            dispatches={d.id: d for d in self.list_dispatches(incident_id)},
            transfers={t.transfer_id: t for t in self.list_transfers(incident_id)},
            receipts={r.action_id: r for r in self.list_receipts(incident_id)},
            holds={h["freezer_id"]: ContainmentHold(**h) for h in self.store.query("holds")},
            impact=self.get_impact(incident_id),
            readings={},
            revision_states=self.revision_states(),
            memory_notes=self.memory_notes(incident_id),
            unavailable_sources=unavailable,
        )

    def load_kernel_state_txn(self, ctx: TxnContext, incident_id: str) -> KernelState:
        """Same assembly, but every read is inside the transaction's read set.

        This is what makes the capacity check and the reservation write a single atomic
        unit — the reason two concurrent brokers cannot both see the same free slots.
        """
        incident_doc = ctx.get("incidents", incident_id)
        impacts = ctx.query("impactSnapshots", incident_id=incident_id)
        holds = {h["freezer_id"]: ContainmentHold(**h) for h in ctx.query("holds")}
        return KernelState(
            incident=Incident(**incident_doc) if incident_doc else None,
            freezers={d["id"]: Freezer(**d) for d in ctx.query("freezers")},
            containers={d["id"]: Container(**d) for d in ctx.query("containers")},
            reservations={d["id"]: Reservation(**d) for d in ctx.query("reservations")},
            work_orders={
                d["id"]: WorkOrder(**d) for d in ctx.query("workOrders", incident_id=incident_id)
            },
            dispatches={
                d["id"]: Dispatch(**d) for d in ctx.query("dispatches", incident_id=incident_id)
            },
            transfers={
                d["transfer_id"]: Transfer(**d)
                for d in ctx.query("transfers", incident_id=incident_id)
            },
            receipts={
                d["action_id"]: ActionReceipt(**d)
                for d in ctx.query("receipts", incident_id=incident_id)
            },
            holds=holds,
            impact=ImpactSnapshot(**impacts[0]) if impacts else None,
            revision_states={
                f"{r['agent']}@{r['revision_id']}": r["state"] for r in ctx.query("agentRevisions")
            },
            memory_notes=ctx.query("memoryNotes", incident_id=incident_id),
        )

    # -- internals -----------------------------------------------------------------

    def _get(self, collection: str, doc_id: str, model: Any) -> Any | None:
        doc = self.store.get(collection, doc_id)
        return model(**doc) if doc is not None else None
