"""The effect commit sequence (PRD §16).

Every mutating domain service runs exactly these steps, in this order, inside one
transaction:

    1. validate caller authority              (N7, done by the caller's route guard)
    2. validate request schema                (Pydantic, done at the route boundary)
    3. check for an existing receipt by action_id
    4. if already committed, return that receipt verbatim
    5. otherwise evaluate Safety Kernel preconditions
    6. atomically commit the effect + receipt
    7. return the receipt

Step 3-4 is why a resumed workflow, a redelivered Pub/Sub message, and a double-tapped
responder button all converge on one effect. Step 6 being inside the same transaction
as the capacity read is why two concurrent incidents cannot both win the last slot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nightshift.common.clock import now_iso
from nightshift.common.ids import event_id
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, Decision, KernelState, evaluate_action
from nightshift.safety_kernel.decision import Verdict
from nightshift.schemas.core import ActionReceipt, IncidentEvent
from nightshift.schemas.enums import ActionStatus, FailureClass
from services.common.repository import Repository

EffectBuilder = Callable[[TxnContext, KernelState, ActionRequest], "EffectResult"]


@dataclass(frozen=True)
class EffectResult:
    """What the caller's builder produced: where the effect lives and what to show."""

    effect_ref: str
    collection: str
    summary: str
    evidence_sources: list[str]
    detail: dict[str, Any]


@dataclass(frozen=True)
class EffectOutcome:
    receipt: ActionReceipt
    decision: Decision
    duplicate: bool

    @property
    def committed(self) -> bool:
        return self.receipt.status is ActionStatus.COMMITTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt.model_dump(mode="json"),
            "decision": self.decision.as_dict(),
            "duplicate_returned": self.duplicate,
        }


def commit_effect(
    repo: Repository,
    request: ActionRequest,
    builder: EffectBuilder,
    *,
    trace_id: str | None = None,
    record_refusals: bool = True,
) -> EffectOutcome:
    """Run the seven-step sequence for one action request."""

    def txn(ctx: TxnContext) -> EffectOutcome:
        # 3 / 4 — a *committed* receipt short-circuits everything. That is the whole
        # exactly-once guarantee: the effect exists, so return the original receipt.
        #
        # A refusal is deliberately NOT replayed. A refusal is a statement about the
        # world at one moment, and the world legitimately changes — a close refused
        # because material was stranded in the failed freezer must succeed once that
        # material moves. Replaying refusals made a refusal permanent and could wedge an
        # incident that had since become closeable. The refusal is still evidence; it
        # stays on the incident timeline, and the receipt is re-evaluated on retry.
        existing_doc = ctx.get("receipts", request.action_id)
        if existing_doc is not None:
            existing = ActionReceipt(**existing_doc)
            if existing.status is ActionStatus.COMMITTED:
                return EffectOutcome(
                    receipt=existing.model_copy(update={"duplicate_returned": True}),
                    decision=Decision(
                        verdict=Verdict.ALLOW, reason="existing receipt replayed"
                    ),
                    duplicate=True,
                )

        state = repo.load_kernel_state_txn(ctx, request.incident_id)

        # 5 — deterministic preconditions.
        decision = evaluate_action(state, request)
        if not decision.allowed:
            receipt = _receipt(
                request,
                status=(
                    ActionStatus.UNAVAILABLE
                    if decision.verdict is Verdict.UNAVAILABLE
                    else ActionStatus.REFUSED
                ),
                failure_class=decision.failure_class or FailureClass.INVARIANT_REJECTION,
                refusal_reason=decision.reason,
                trace_id=trace_id,
            )
            if record_refusals:
                # A refusal is evidence. It is written under the *action id* so a retry
                # of the same refused intent does not re-run the whole evaluation, and
                # so the incident timeline can show what was refused and why.
                ctx.set("receipts", request.action_id, receipt.model_dump(mode="json"))
                ctx.set(
                    "incidentEvents",
                    (eid := event_id("evt")),
                    _refusal_event(eid, request, decision, trace_id).model_dump(mode="json"),
                )
            return EffectOutcome(receipt=receipt, decision=decision, duplicate=False)

        # 6 — the effect and its receipt land together or not at all.
        result = builder(ctx, state, request)
        receipt = _receipt(
            request,
            status=ActionStatus.COMMITTED,
            failure_class=FailureClass.NONE,
            effect_ref=result.effect_ref,
            evidence_sources=result.evidence_sources,
            trace_id=trace_id,
        )
        ctx.set("receipts", request.action_id, receipt.model_dump(mode="json"))
        ctx.set(
            "incidentEvents",
            (eid := event_id("evt")),
            _receipt_event(eid, request, receipt, result, trace_id).model_dump(mode="json"),
        )
        return EffectOutcome(receipt=receipt, decision=decision, duplicate=False)

    return repo.store.run_transaction(txn)


def _receipt(
    request: ActionRequest,
    *,
    status: ActionStatus,
    failure_class: FailureClass,
    effect_ref: str | None = None,
    refusal_reason: str | None = None,
    evidence_sources: list[str] | None = None,
    trace_id: str | None = None,
) -> ActionReceipt:
    return ActionReceipt(
        receipt_id=f"RCP-{request.action_id[:16]}",
        action_id=request.action_id,
        incident_id=request.incident_id,
        action_type=request.action_type,
        actor_identity=request.actor_identity,
        requested_by_agent=request.requested_by_agent,
        requested_by_agent_revision=request.requested_by_agent_revision,
        request_hash=request.request_hash,
        effect_ref=effect_ref,
        status=status,
        failure_class=failure_class,
        refusal_reason=refusal_reason,
        committed_at=request.now or now_iso(),
        duplicate_returned=False,
        evidence_sources=evidence_sources or [],
        trace_id=trace_id,
    )


def _receipt_event(
    eid: str,
    request: ActionRequest,
    receipt: ActionReceipt,
    result: EffectResult,
    trace_id: str | None,
) -> IncidentEvent:
    return IncidentEvent(
        event_id=eid,
        incident_id=request.incident_id,
        occurred_at=receipt.committed_at,
        source=request.actor_identity,
        kind="receipt",
        correlation_id=request.incident_id,
        summary=result.summary,
        detail={
            "action_type": request.action_type.value,
            "effect_ref": result.effect_ref,
            "collection": result.collection,
            "evidence_sources": result.evidence_sources,
            **result.detail,
        },
        action_id=request.action_id,
        agent=request.requested_by_agent,
        trace_id=trace_id,
    )


def _refusal_event(
    eid: str, request: ActionRequest, decision: Decision, trace_id: str | None
) -> IncidentEvent:
    return IncidentEvent(
        event_id=eid,
        incident_id=request.incident_id,
        occurred_at=request.now or now_iso(),
        source=request.actor_identity,
        kind="refusal",
        correlation_id=request.incident_id,
        summary=f"{request.action_type.value} refused by {decision.invariant}: {decision.reason}",
        detail=decision.as_dict(),
        action_id=request.action_id,
        agent=request.requested_by_agent,
        trace_id=trace_id,
    )


def record_event(
    repo: Repository,
    incident_id: str,
    *,
    kind: str,
    summary: str,
    source: str,
    detail: dict[str, Any] | None = None,
    agent: Any = None,
    action_id: str | None = None,
    trace_id: str | None = None,
    occurred_at: str | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        event_id=event_id("evt"),
        incident_id=incident_id,
        occurred_at=occurred_at or now_iso(),
        source=source,
        kind=kind,  # type: ignore[arg-type]
        correlation_id=incident_id,
        summary=summary,
        detail=detail or {},
        action_id=action_id,
        agent=agent,
        trace_id=trace_id,
    )
    repo.append_event(event)
    return event
