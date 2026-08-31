"""Incident orchestration.

The Commander decides *which specialist works next*. This module executes that decision,
enforces budgets, drives deterministic state transitions when the evidence supports
them, and records everything on the incident timeline.

Why the loop is here and not inside an ADK agent-transfer graph: specialist ordering,
tool-call budgets, and resume points need to be observable state that a drill can
interrupt and a manifest can replay. An emergent conversation is a poor place to keep
something a verifier has to reproduce.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from agents.fleet import OUTPUT_SCHEMAS, AgentBuild, build_fleet
from nightshift.common import otel
from nightshift.common.ids import correlation_id
from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.invariants import n6_would_hold
from nightshift.safety_kernel.transitions import can_transition_incident, next_natural_state
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.agent_io import CommanderPlan
from nightshift.schemas.enums import TERMINAL_INCIDENT_STATES, AgentName, IncidentState
from services.common.effects import record_event
from services.common.repository import Repository
from services.gateway.broker import BrokerDeniedError, ToolBroker

log = logging.getLogger(__name__)


_QUOTA_MARKERS = ("resource_exhausted", "resourceexhausted", "429", "rate limit", "quota")

_TRANSPORT_MARKERS = (
    "503",
    "unavailable",
    "500",
    "internal server error",
    "internal error",
    "504",
    "deadline exceeded",
    "deadlineexceeded",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection error",
    "remote end closed",
    "broken pipe",
    "server disconnected",
)


def _transient_class(exc: BaseException) -> str | None:
    """Name the infrastructure failure class, or ``None`` if this is not one.

    The distinction that matters is between the model *deciding* something and the model
    being *unreachable*. A refusal, a bad plan, or a schema violation is an agent
    outcome and belongs on the timeline as one. A 503 from Vertex is someone else's
    capacity problem, and abandoning a freezer rescue over it would leave 42 specimen
    containers half-moved because a data centre was busy.

    This used to match quota errors only, so a routine 503 ended the run on the first
    attempt: the Commander returned no plan, and ``_run_inner`` breaks out of the whole
    loop when that happens. Every non-quota transport failure was therefore a full
    rescue abort.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _QUOTA_MARKERS):
        return "quota"
    if any(marker in text for marker in _TRANSPORT_MARKERS):
        return "transport"
    return None


_REPAIRABLE_ERRORS = ("no JSON object found", "schema validation failed")


def _repair_prompt(original: str, result: SpecialistResult) -> str | None:
    """A second, corrective ask, or ``None`` when the failure is not the agent's to fix.

    Only two failures are worth re-asking: the agent wrote prose where a JSON object was
    required, or it wrote an object the output schema rejected. Both are the shape a
    hallucination takes here, and both are recoverable by showing the agent the parser's
    own complaint.

    A broker denial is not repairable and must not be re-asked: the agent reached for a
    tool it does not hold, the answer is no, and asking again is asking the authority
    layer to change its mind. A transport failure is not repairable either, because
    ``_invoke_once`` has already exhausted its backoff by the time this is reached.
    """
    if result.ok or not result.error:
        return None
    if not any(marker in result.error for marker in _REPAIRABLE_ERRORS):
        return None
    return (
        f"{original}\n\n"
        "Your previous reply could not be used. The parser reported: "
        f"{result.error}. Reply with a single JSON object matching your output schema, "
        "and nothing else. No prose before it and no code fence around it."
    )


@dataclass
class SpecialistResult:
    agent: AgentName
    ok: bool
    output: dict[str, Any] | None
    raw_text: str
    error: str | None = None
    tool_calls: int = 0
    duration_s: float = 0.0


@dataclass
class RunOutcome:
    incident_id: str
    final_state: str
    rounds: int
    specialist_results: list[SpecialistResult] = field(default_factory=list)
    commander_plans: list[dict[str, Any]] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    stopped_because: str = ""
    model_calls: int = 0
    wall_clock_s: float = 0.0
    trace_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "trace_id": self.trace_id,
            "final_state": self.final_state,
            "rounds": self.rounds,
            "specialists_run": [r.agent.value for r in self.specialist_results],
            "specialist_failures": [
                {"agent": r.agent.value, "error": r.error}
                for r in self.specialist_results
                if not r.ok
            ],
            "escalations": self.escalations,
            "stopped_because": self.stopped_because,
            "model_calls": self.model_calls,
            "wall_clock_s": round(self.wall_clock_s, 2),
        }


class IncidentOrchestrator:
    def __init__(
        self,
        repo: Repository,
        broker: ToolBroker,
        incident_id: str,
        *,
        model: str,
        revisions: dict[AgentName, str] | None = None,
        skill_refs: dict[str, str] | None = None,
        memory_context: list[str] | None = None,
        config: KernelConfig = DEFAULT_CONFIG,
        max_rounds: int = 6,
        field_hook: Any = None,
    ) -> None:
        self.repo = repo
        self.broker = broker
        self.incident_id = incident_id
        self.model = model
        self.config = config
        self.max_rounds = max_rounds
        self.field_hook = field_hook
        """Called as ``field_hook(round_index)`` after each round.

        This is where physical-world events enter: a responder scanning a box. Claude
        cannot move a freezer box, so in demo and drill namespaces the field simulator
        emits the same events the responder web interface emits. In a real deployment
        this hook is simply absent and the events arrive over Pub/Sub.
        """
        self.correlation = correlation_id("inc")
        self.fleet: dict[AgentName, AgentBuild] = build_fleet(
            broker,
            incident_id,
            model=model,
            revisions=revisions,
            skill_refs=skill_refs,
            memory_context=memory_context,
        )
        self._session_service = InMemorySessionService()
        self._runners: dict[AgentName, Runner] = {}
        self._model_calls = 0

    # -- public ---------------------------------------------------------------------

    async def run(self) -> RunOutcome:
        with otel.span(
            "incident.run",
            **{otel.ATTR_INCIDENT: self.incident_id, "nightshift.model": self.model},
        ):
            outcome = await self._run_inner()
            outcome.trace_id = otel.current_trace_id()
            if outcome.trace_id:
                self._record_trace_root(outcome.trace_id)
            return outcome

    def _record_trace_root(self, trace_id: str) -> None:
        """Pin the incident's root trace so the proof surfaces can link to it."""
        incident = self.repo.get_incident(self.incident_id)
        if incident is None or incident.trace_root_id == trace_id:
            return
        self.repo.put(
            "incidents", incident.id, incident.model_copy(update={"trace_root_id": trace_id})
        )

    async def _run_inner(self) -> RunOutcome:
        started = time.perf_counter()
        outcome = RunOutcome(incident_id=self.incident_id, final_state="", rounds=0)

        for round_index in range(self.max_rounds):
            outcome.rounds = round_index + 1

            elapsed = time.perf_counter() - started
            if elapsed > self.config.max_wall_clock_seconds:
                outcome.stopped_because = "wall-clock budget exceeded"
                break

            plan = await self._commander_step(round_index)
            if plan is None:
                outcome.stopped_because = "commander produced no usable plan"
                break
            outcome.commander_plans.append(plan.model_dump(mode="json"))

            if plan.escalate:
                outcome.escalations.append(plan.escalation_reason or "commander escalated")
                self._request_transition(
                    IncidentState.ESCALATED, plan.escalation_reason or "commander escalated"
                )

            for step in plan.next_steps:
                if step.specialist not in self.fleet:
                    continue
                # Let the world advance before each specialist, not only between rounds.
                # A round against real Firestore takes minutes, and telemetry that was
                # fresh when the round started can age past the N4 freshness window
                # before the custody agent reaches it.
                self._tick_world(round_index)
                with otel.span(
                    f"specialist.{step.specialist.value}",
                    **{
                        otel.ATTR_INCIDENT: self.incident_id,
                        otel.ATTR_AGENT: step.specialist.value,
                        otel.ATTR_AGENT_REVISION: self.fleet[step.specialist].revision,
                        "nightshift.objective": step.objective[:200],
                    },
                ):
                    result = await self._run_specialist(step.specialist, step.objective)
                outcome.specialist_results.append(result)
                if result.output and result.output.get("escalate"):
                    outcome.escalations.append(
                        f"{step.specialist.value}: {result.output.get('rationale', 'escalated')}"
                    )
                self._advance_deterministically()

            self._tick_world(round_index)

            self._advance_deterministically()

            if plan.request_closure:
                closed = self._attempt_closure()
                if closed:
                    outcome.stopped_because = "incident closed"
                    break

            incident = self.repo.get_incident(self.incident_id)
            if incident and incident.state in {IncidentState.CLOSED, IncidentState.ABORTED_SAFE}:
                outcome.stopped_because = f"incident reached {incident.state.value}"
                break
        else:
            outcome.stopped_because = "round budget exhausted"

        # Final sweep. If the incident is deterministically closeable — every container
        # in a terminal state, no uncertain effects, containment released against
        # validated recovery, and nothing left in the failed freezer — close it.
        #
        # This is not the Commander's judgement being overridden. It is the same
        # evidence-driven progress every other transition makes, applied once more at
        # the end so a finished rescue does not sit open because a conversation ran out
        # of turns. A live run reached RECONCILING with 42/42 committed and
        # n6_would_hold() true, and stayed there.
        if self._close_if_evidence_supports_it():
            outcome.stopped_because = "incident closed on final evidence sweep"

        incident = self.repo.get_incident(self.incident_id)
        outcome.final_state = incident.state.value if incident else "UNKNOWN"
        outcome.model_calls = self._model_calls
        outcome.wall_clock_s = time.perf_counter() - started
        return outcome

    # -- steps ----------------------------------------------------------------------

    async def _commander_step(self, round_index: int) -> CommanderPlan | None:
        state = self.repo.load_kernel_state(self.incident_id)
        recon = reconciliation_snapshot(state)
        incident = state.incident

        live_reservations = len(
            [r for r in state.reservations.values() if r.incident_id == self.incident_id]
        )
        briefing = (
            f"Round {round_index + 1}. Incident {self.incident_id} is currently "
            f"{incident.state.value if incident else 'UNKNOWN'}.\n"
            f"Reconciliation: {recon.total} impacted container(s), "
            f"{len(recon.committed)} committed, {len(recon.quarantined)} quarantined, "
            f"{len(recon.in_flight)} in flight, {len(recon.unresolved)} unresolved.\n"
            f"Impact snapshot recorded: {state.impact is not None}. "
            f"Active reservations: {live_reservations}. "
            f"Work orders: {len(state.work_orders)}. Dispatches: {len(state.dispatches)}.\n\n"
            f"{self._blockers_text()}\n\n"
            "Read the incident with your tools before deciding. Choose the specialists "
            "that address what is actually blocking progress, in the order that makes "
            "sense. Return your CommanderPlan."
        )
        result = await self._invoke(AgentName.COMMANDER, briefing)
        if not result.ok or result.output is None:
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_decision",
                source=AgentName.COMMANDER.value,
                summary="Commander produced no usable plan",
                detail={"error": result.error, "raw": result.raw_text[:500]},
                agent=AgentName.COMMANDER,
            )
            return None
        try:
            plan = CommanderPlan(**result.output)
        except ValidationError as exc:
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_decision",
                source=AgentName.COMMANDER.value,
                summary="Commander output failed schema validation",
                detail={"error": str(exc)[:800]},
                agent=AgentName.COMMANDER,
            )
            return None

        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.COMMANDER.value,
            summary=plan.assessment[:300],
            detail={
                "next_steps": [
                    {"specialist": s.specialist.value, "objective": s.objective}
                    for s in plan.next_steps
                ],
                "request_closure": plan.request_closure,
                "escalate": plan.escalate,
            },
            agent=AgentName.COMMANDER,
        )
        for step in plan.next_steps:
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_delegation",
                source=AgentName.COMMANDER.value,
                summary=f"Commander delegated to {step.specialist.value}: {step.objective[:160]}",
                detail={"specialist": step.specialist.value, "objective": step.objective},
                agent=AgentName.COMMANDER,
            )
        return plan

    async def _run_specialist(self, name: AgentName, objective: str) -> SpecialistResult:
        before = len(self.broker.records)
        started = time.perf_counter()
        result = await self._invoke(
            name,
            f"Incident {self.incident_id}. Your objective this round: {objective}\n\n"
            "Use your tools to establish current authoritative state, then return your "
            "structured output.",
        )
        result.tool_calls = len(self.broker.records) - before
        result.duration_s = time.perf_counter() - started

        if result.ok and result.output is not None:
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_decision",
                source=name.value,
                summary=_summarize(name, result.output),
                detail=result.output,
                agent=name,
            )
            self._apply_consequences(name, result.output)
        else:
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_decision",
                source=name.value,
                summary=f"{name.value} did not return a usable decision",
                detail={"error": result.error, "raw": result.raw_text[:500]},
                agent=name,
            )
        return result

    _QUOTA_BACKOFF_S = (15, 45, 90)
    """Backoff for model quota exhaustion.

    A 429 from Vertex is infrastructure, not an agent decision (N12). Quota refills on a
    wall-clock window, so the wait has to be long enough to actually clear one.
    """

    _TRANSPORT_BACKOFF_S = (2, 6, 15)
    """Backoff for a model endpoint that is reachable but unwell.

    A 503 or a reset connection usually clears on the next attempt, and waiting 15
    seconds for one burns the incident's wall-clock budget for no reason.
    """

    _MAX_REPAIR_ATTEMPTS = 1
    """How many times a malformed agent response is re-asked before it counts as failed.

    Bounded at one on purpose. A model that produced unparseable output once will often
    produce valid output when handed the parser's own complaint, and a model that fails
    twice is not going to converge by being asked a third time. An unbounded repair loop
    is the failure mode this budget exists to prevent.
    """

    async def _invoke(self, name: AgentName, message: str) -> SpecialistResult:
        """Call an agent, recovering from the two failures that are not decisions.

        Transport failures are retried inside ``_invoke_once``. Malformed output is
        retried here, once, by handing the agent the exact validation error and asking
        again. Both recoveries are recorded on the incident timeline as
        ``agent_recovery`` so the reader can see that the fleet degraded and came back
        rather than silently producing a shorter rescue.
        """
        result = await self._invoke_once(name, message)
        repair = _repair_prompt(message, result)
        if result.ok or repair is None:
            return result

        for attempt in range(self._MAX_REPAIR_ATTEMPTS):
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_recovery",
                source=name.value,
                summary=(
                    f"{name.value} returned output the schema rejected; re-asking once "
                    "with the validation error attached"
                ),
                detail={"error": result.error, "attempt": attempt + 1, "recovery": "reprompt"},
                agent=name,
            )
            retried = await self._invoke_once(name, repair)
            if retried.ok:
                record_event(
                    self.repo,
                    self.incident_id,
                    kind="agent_recovery",
                    source=name.value,
                    summary=f"{name.value} returned valid output on the repair attempt",
                    detail={"attempt": attempt + 1, "recovery": "reprompt", "outcome": "recovered"},
                    agent=name,
                )
                return retried
            result = retried

        return result

    async def _invoke_once(self, name: AgentName, message: str) -> SpecialistResult:
        runner = self._runner_for(name)
        session_id = f"{self.incident_id}-{name.value}"
        await self._ensure_session(name, session_id)

        chunks: list[str] = []
        error: str | None = None

        for attempt in range(len(self._QUOTA_BACKOFF_S) + 1):
            chunks = []
            error = None
            self._model_calls += 1
            try:
                async for event in runner.run_async(
                    user_id="nightshift",
                    session_id=session_id,
                    new_message=types.Content(role="user", parts=[types.Part(text=message)]),
                ):
                    content = getattr(event, "content", None)
                    if content and getattr(content, "parts", None):
                        for part in content.parts:
                            if getattr(part, "text", None):
                                chunks.append(part.text)
                break
            except BrokerDeniedError as denied:
                error = f"tool authorization denied: {denied.decision.reason}"
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                failure_class = _transient_class(exc)
                backoff = (
                    self._QUOTA_BACKOFF_S if failure_class == "quota" else self._TRANSPORT_BACKOFF_S
                )
                if failure_class is None or attempt >= len(backoff):
                    break
                delay = backoff[attempt]
                log.warning(
                    "%s hit a %s failure from the model API; retrying in %ss (attempt %s)",
                    name.value,
                    failure_class,
                    delay,
                    attempt + 1,
                )
                record_event(
                    self.repo,
                    self.incident_id,
                    kind="agent_recovery",
                    source=name.value,
                    summary=(
                        f"Model API {failure_class} failure; waiting {delay}s before "
                        "retrying. This is an infrastructure delay, not an agent decision."
                    ),
                    detail={
                        "attempt": attempt + 1,
                        "backoff_s": delay,
                        "failure_class": failure_class,
                        "recovery": "backoff-retry",
                        "error": error[:300],
                    },
                    agent=name,
                )
                await asyncio.sleep(delay)

        raw = "\n".join(chunks).strip()
        if error is not None:
            return SpecialistResult(agent=name, ok=False, output=None, raw_text=raw, error=error)

        parsed = _extract_json(raw)
        if parsed is None:
            return SpecialistResult(
                agent=name,
                ok=False,
                output=None,
                raw_text=raw,
                error="no JSON object found in the final message",
            )
        schema = OUTPUT_SCHEMAS[name]
        try:
            validated = schema(**parsed).model_dump(mode="json")
        except ValidationError as exc:
            return SpecialistResult(
                agent=name,
                ok=False,
                output=parsed,
                raw_text=raw,
                error=f"schema validation failed: {exc.error_count()} error(s)",
            )
        return SpecialistResult(agent=name, ok=True, output=validated, raw_text=raw)

    def _runner_for(self, name: AgentName) -> Runner:
        if name not in self._runners:
            build = self.fleet[name]
            app = App(
                name=f"nightshift_{build.agent.name}",
                root_agent=build.agent,
                resumability_config=ResumabilityConfig(is_resumable=True),
            )
            self._runners[name] = Runner(
                app=app, session_service=self._session_service, auto_create_session=True
            )
        return self._runners[name]

    async def _ensure_session(self, name: AgentName, session_id: str) -> None:
        app_name = f"nightshift_{self.fleet[name].agent.name}"
        existing = await self._session_service.get_session(
            app_name=app_name, user_id="nightshift", session_id=session_id
        )
        if existing is None:
            await self._session_service.create_session(
                app_name=app_name, user_id="nightshift", session_id=session_id
            )

    def _tick_world(self, round_index: int) -> None:
        """Advance the simulated physical world one step.

        In a real deployment this hook is absent and these events arrive over Pub/Sub
        from sensor integrations and responder devices.
        """
        if self.field_hook is None:
            return
        try:
            self.field_hook(round_index)
        except Exception as exc:
            log.warning("field hook failed on round %s: %s", round_index, exc)

    # -- what is actually blocking progress -------------------------------------------

    _PRIMARY_PATH: list[IncidentState] = [
        IncidentState.CONFIRMED,
        IncidentState.CONTAINED,
        IncidentState.RESCUE_PLANNING,
        IncidentState.CAPACITY_RESERVED,
        IncidentState.DISPATCHED,
        IncidentState.TRANSFER_IN_PROGRESS,
        IncidentState.RECONCILING,
        IncidentState.CLOSED,
    ]

    def _pipeline_need(self) -> tuple[AgentName | None, str]:
        """The single next thing the incident deterministically needs, and why.

        Computed from authoritative state, not from a fixed running order. This exists
        because early live runs had the Commander pick specialists in an order the
        pipeline could not use — custody before any capacity was reserved, impact
        assessment twice, and never a signal verdict at all, which left containment
        (a reflex to a *confirmed* equipment failure) permanently unplaced.

        It reports a fact about the pipeline, the way an operations console would. The
        Commander still chooses; it just is not guessing any more.
        """
        state = self.repo.load_kernel_state(self.incident_id)
        if state.incident is None:
            return None, ""
        incident = state.incident
        freezer_id = incident.failed_freezer_id

        if not self._signal_verdict_recorded():
            return AgentName.SIGNAL_INVESTIGATOR, (
                "No signal verdict has been recorded. Containment is a reflex to a "
                "confirmed equipment failure, and nothing downstream can proceed until "
                "the telemetry is classified."
            )
        if state.holds.get(freezer_id) is None:
            return AgentName.SIGNAL_INVESTIGATOR, (
                f"No containment hold exists on {freezer_id}. The signal verdict did not "
                "classify this as an equipment failure; re-examine the telemetry."
            )
        if state.impact is None:
            return AgentName.IMPACT_ANALYST, (
                "No authoritative impact snapshot exists. Capacity cannot be planned "
                "against an unknown impact set."
            )

        unplaced = self._unplaced_groups(state)
        if unplaced:
            return AgentName.CAPACITY_BROKER, (
                f"{len(unplaced)} placement group(s) have no active reservation: "
                f"{', '.join(unplaced[:4])}. Material cannot move without a reserved "
                "destination."
            )
        if not state.dispatches:
            return AgentName.DISPATCH_AGENT, (
                "Capacity is reserved but no responder has been dispatched and no work "
                "order exists. Nothing physical can happen yet."
            )

        awaiting = [t for t in state.transfers.values() if t.state.value == "RECEIVED"]
        if awaiting:
            return AgentName.CUSTODY_AGENT, (
                f"{len(awaiting)} container(s) are scanned in at their destination and "
                "awaiting a custody commit. Only the custody-agent can commit them."
            )

        recon = reconciliation_snapshot(state)
        if recon.unresolved:
            return AgentName.CUSTODY_AGENT, (
                f"{len(recon.unresolved)} container(s) are unresolved and need an "
                "explicit disposition before this incident can close."
            )
        if recon.in_flight:
            return None, (
                f"{len(recon.in_flight)} container(s) are picked up but not yet scanned "
                "in at their destination. Waiting on the responder."
            )
        if recon.complete:
            hold = state.holds.get(freezer_id)
            if hold is not None and hold.active:
                return None, (
                    "Every container is reconciled but the containment hold is still "
                    "active, because post-repair telemetry has not yet demonstrated a "
                    "validated recovery window. The hold will release on its own once it "
                    "has. Nothing for a specialist to do."
                )
            return None, (
                "READY TO CLOSE. Every impacted container is in a terminal custody state "
                "and containment has been released with validated recovery evidence. "
                "Nothing further is needed from any specialist. You must set "
                "request_closure to true in this plan — the incident will not close "
                "otherwise, and leaving a finished incident open is itself a failure."
            )
        return None, ""

    def _signal_verdict_recorded(self) -> bool:
        return any(
            e.kind == "agent_decision"
            and e.agent is AgentName.SIGNAL_INVESTIGATOR
            and "classification" in (e.detail or {})
            for e in self.repo.list_events(self.incident_id)
        )

    @staticmethod
    def _unplaced_groups(state: Any) -> list[str]:
        if state.impact is None:
            return []
        covered = {
            r.placement_group_id
            for r in state.reservations.values()
            if state.incident is not None
            and r.incident_id == state.incident.id
            and r.state.value in {"ACTIVE", "CONSUMED"}
        }
        return sorted(g.id for g in state.impact.placement_groups if g.id not in covered)

    def _blockers_text(self) -> str:
        state = self.repo.load_kernel_state(self.incident_id)
        if state.incident is None:
            return ""
        current = state.incident.state

        lines = ["Deterministic pipeline status:"]
        try:
            start = self._PRIMARY_PATH.index(current) + 1
        except ValueError:
            start = 0
        for target in self._PRIMARY_PATH[start:]:
            decision = can_transition_incident(state, target)
            if decision.allowed:
                lines.append(f"  next state {target.value}: ready, will advance automatically")
            else:
                lines.append(f"  next state {target.value}: BLOCKED — {decision.reason}")
            break

        need, reason = self._pipeline_need()
        if need is not None:
            lines.append(f"  what is needed next: {need.value}")
            lines.append(f"  why: {reason}")
        elif reason:
            lines.append(f"  {reason}")
        return "\n".join(lines)

    # -- deterministic consequences ---------------------------------------------------

    def _apply_consequences(self, name: AgentName, output: dict[str, Any]) -> None:
        """Enact the deterministic follow-through of a specialist's verdict.

        This is where the architecture rule gets its teeth. Containment is a reflex, not
        a decision: the Signal Investigator decides *whether this is an equipment
        failure*, and if it is, containment follows automatically under the ingestor
        principal. Likewise the Impact Analyst decides *which containers and how
        urgently*, and the deterministic service records the authoritative snapshot from
        that validated output.

        No agent holds inventory-write authority, so no agent can do either of these
        itself — which is exactly the point.
        """
        match name:
            case AgentName.SIGNAL_INVESTIGATOR:
                self._consequence_signal(output)
            case AgentName.IMPACT_ANALYST:
                self._consequence_impact(output)
            case _:
                pass

    def _consequence_signal(self, output: dict[str, Any]) -> None:
        if output.get("classification") != "EQUIPMENT_FAILURE":
            return
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return
        self._advance_deterministically()
        self._ingestor_call(
            "apply_containment_hold",
            {
                "incident_id": self.incident_id,
                "freezer_id": incident.failed_freezer_id,
                "reason": (
                    f"equipment failure confirmed by signal-investigator "
                    f"({output.get('suspected_fault_class', 'UNKNOWN')})"
                ),
            },
        )

    def _consequence_impact(self, output: dict[str, Any]) -> None:
        container_ids = [str(c) for c in output.get("container_ids", [])]
        if not container_ids:
            return
        self._ingestor_call(
            "record_impact_snapshot",
            {
                "incident_id": self.incident_id,
                "container_ids": container_ids,
                "inventory_complete": bool(output.get("inventory_complete", False)),
            },
        )

    def _ingestor_call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a deterministic consequence under the ingestor principal.

        Deliberately not routed through the agent broker: this is not an agent acting.
        It is the system reacting to a validated agent verdict, and the ledger records
        ``incident-ingestor`` as the actor so authority stays legible.
        """
        from fastapi.testclient import TestClient

        from services.common.identity import PRINCIPAL_HEADER, issue_principal_token
        from services.inventory.app import app as inventory_app

        inventory_app.state.repository = self.repo
        client = TestClient(inventory_app, raise_server_exceptions=False)
        token = issue_principal_token(
            AgentName.INGESTOR, "rev-1", self.repo_settings.agent_shared_secret
        )
        route = {
            "apply_containment_hold": "/v1/holds",
            "record_impact_snapshot": "/v1/impact",
            "release_containment_hold": f"/v1/holds/{payload.get('freezer_id')}/release",
        }[operation]
        response = client.post(route, json=payload, headers={PRINCIPAL_HEADER: token})
        try:
            return dict(response.json())
        except ValueError:
            return {"error": f"non-JSON response {response.status_code}"}

    @property
    def repo_settings(self) -> Any:
        from nightshift.common.config import get_settings

        return get_settings()

    # -- deterministic progress ------------------------------------------------------

    def _advance_deterministically(self) -> None:
        """Walk the incident forward as far as the evidence actually supports.

        Containment release is part of this. A hold releases because post-repair
        telemetry demonstrates a validated recovery, not because anyone decided the
        incident is over — so it belongs with the other evidence-driven transitions
        rather than behind a closure request.

        The Commander does not get to skip states, and it does not have to name every
        intermediate one either. This asks the kernel what the evidence already
        justifies and requests exactly that.
        """
        self._release_containment_if_recovered()
        for _ in range(len(IncidentState)):
            state = self.repo.load_kernel_state(self.incident_id)
            target = next_natural_state(state)
            if target is None or target is IncidentState.CLOSED:
                return
            if not self._request_transition(target, "evidence supports this transition"):
                return

    def _request_transition(self, to_state: IncidentState, reason: str) -> bool:
        try:
            result = self.broker.call(
                AgentName.COMMANDER,
                "request_incident_transition",
                {"incident_id": self.incident_id, "to_state": to_state.value, "reason": reason},
                system=True,
            )
        except BrokerDeniedError:
            return False
        except Exception as exc:
            log.warning("transition to %s failed: %s", to_state.value, exc)
            return False
        return bool(result.get("receipt", {}).get("status") == "COMMITTED")

    def _release_containment_if_recovered(self) -> bool:
        """Offer the hold's release rule the post-repair readings and let it decide.

        The readings are passed in raw. If the freezer has not held setpoint for the
        full validation window, or any reading in it is too warm, the release is refused
        and the incident stays open — which is the D18 behaviour.
        """
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return False
        freezer_id = incident.failed_freezer_id
        hold = self.repo.get_hold(freezer_id)
        if hold is None or not hold.active:
            return False

        readings = self.repo.list_readings(freezer_id)
        window = [
            {"recorded_at": r.recorded_at, "celsius": r.celsius}
            for r in readings
            if r.id.startswith(f"R-{freezer_id}-RECOVERY")
        ]
        if not window:
            record_event(
                self.repo,
                self.incident_id,
                kind="refusal",
                source="incident-ingestor",
                summary=(
                    f"Containment hold on {freezer_id} not released: no post-repair "
                    "validation readings exist yet"
                ),
                detail={"freezer_id": freezer_id},
            )
            return False

        result = self._ingestor_call(
            "release_containment_hold",
            {
                "incident_id": self.incident_id,
                "freezer_id": freezer_id,
                "validation_readings": window,
            },
        )
        return bool(result.get("receipt", {}).get("status") == "COMMITTED")

    def _close_if_evidence_supports_it(self) -> bool:
        """Close only when the deterministic preconditions already hold.

        Asks the kernel first and does nothing unless the answer is an unqualified yes,
        so this can never turn a partial rescue into a closed one — N6 is the same guard
        the Incident Control Service will apply to the request anyway.
        """
        incident = self.repo.get_incident(self.incident_id)
        if incident is None or incident.state in TERMINAL_INCIDENT_STATES:
            return False

        self._advance_deterministically()
        state = self.repo.load_kernel_state(self.incident_id)
        ok, reason = n6_would_hold(state)
        if not ok:
            record_event(
                self.repo,
                self.incident_id,
                kind="note",
                source="incident-orchestrator",
                summary=f"Incident left open at end of run: {reason}",
                detail={"final_state": state.incident.state.value if state.incident else None},
            )
            return False

        record_event(
            self.repo,
            self.incident_id,
            kind="note",
            source="incident-orchestrator",
            summary=(
                "Every closure precondition is satisfied; closing on the final evidence "
                "sweep rather than leaving a finished rescue open."
            ),
            detail=reconciliation_snapshot(state).as_dict(),
        )
        return self._attempt_closure()

    def _attempt_closure(self) -> bool:
        state = self.repo.load_kernel_state(self.incident_id)
        recon = reconciliation_snapshot(state)
        if not recon.complete:
            record_event(
                self.repo,
                self.incident_id,
                kind="refusal",
                source=AgentName.COMMANDER.value,
                summary=(
                    f"Closure not requested: {len(recon.unresolved)} unresolved and "
                    f"{len(recon.in_flight)} in-flight container(s) remain"
                ),
                detail=recon.as_dict(),
                agent=AgentName.COMMANDER,
            )
            return False

        self._advance_deterministically()
        if self.repo.get_incident(self.incident_id).state is not IncidentState.RECONCILING:  # type: ignore[union-attr]
            self._request_transition(IncidentState.RECONCILING, "all containers accounted for")

        try:
            result = self.broker.call(
                AgentName.COMMANDER,
                "request_incident_close",
                {"incident_id": self.incident_id, "reason": "all impacted containers reconciled"},
                system=True,
            )
        except Exception as exc:
            log.warning("close request failed: %s", exc)
            return False
        return bool(result.get("receipt", {}).get("status") == "COMMITTED")


# --------------------------------------------------------------------------------------


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the structured object out of a final message.

    Models occasionally wrap it in a fence despite instructions, so both shapes are
    accepted. Anything else is a parse failure, not something to repair by guessing.
    """
    if not text:
        return None
    fenced = _JSON_BLOCK.search(text)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _summarize(name: AgentName, output: dict[str, Any]) -> str:
    match name:
        case AgentName.SIGNAL_INVESTIGATOR:
            return (
                f"{output.get('classification')} at "
                f"{output.get('recommended_severity')} "
                f"(confidence {output.get('confidence')}): {output.get('rationale', '')[:180]}"
            )
        case AgentName.IMPACT_ANALYST:
            n = len(output.get("container_ids", []))
            complete = output.get("inventory_complete")
            return f"Impact: {n} container(s), enumeration complete={complete}"
        case AgentName.CAPACITY_BROKER:
            choices = output.get("choices", [])
            placed = output.get("all_groups_placed")
            return f"Capacity plan: {len(choices)} placement(s), all groups placed={placed}"
        case AgentName.DISPATCH_AGENT:
            return (
                f"Dispatch: {output.get('responder_role')} for "
                f"{output.get('response_phase')}, fault {output.get('fault_class')}"
            )
        case AgentName.CUSTODY_AGENT:
            return (
                f"Custody {output.get('action')} for {output.get('container_id')}: "
                f"{output.get('reason', '')[:160]}"
            )
        case _:
            return json.dumps(output)[:240]
