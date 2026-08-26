"""Tool broker — the single egress path for all agent-to-tool traffic.

Every agent tool call goes through ``ToolBroker.call``. Nothing else reaches a domain
service on an agent's behalf. That gives one place to apply, in order:

    1. registry check         — unregistered tools are unreachable, full stop
    2. identity authorization — the §11.3 matrix, by agent principal
    3. semantic policy        — probabilistic, advisory, never the only gate
    4. fault injection        — drill-only, keyed on (tool, action_id, call number)
    5. transport              — in-process ASGI locally, authenticated HTTP on Cloud Run
    6. content screening      — Model Armor over untrusted tool output

Steps 1 and 2 are deterministic and are *repeated server-side* by every domain service.
Bypassing the broker therefore buys nothing; it just moves where the refusal happens.
Steps 3 and 6 are additional layers that can be unavailable without weakening the
guarantee (PRD §32.6, §32.7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from nightshift.common import otel
from nightshift.common.clock import now_iso
from nightshift.safety_kernel.authority import TOOL_REGISTRY, authorize_tool
from nightshift.safety_kernel.decision import Decision
from nightshift.schemas.enums import AgentName, DenialReason, FailureClass


class BrokerDeniedError(RuntimeError):
    """The broker refused the call. Carries the kernel decision for the ledger."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class Transport(Protocol):
    """How a tool call actually reaches its service."""

    def invoke(
        self, tool_name: str, principal_token: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


class ContentScreen(Protocol):
    """Model Armor or an equivalent. Returns ``(blocked, findings)``."""

    def screen(self, text: str, direction: str) -> tuple[bool, dict[str, Any]]: ...


class SemanticPolicy(Protocol):
    """Semantic Governance or an equivalent. Advisory only."""

    def evaluate(
        self, agent: AgentName, tool_name: str, payload: dict[str, Any]
    ) -> tuple[str, str]: ...


FaultHook = Callable[[str, str, int], None]
"""``(tool_name, action_id, call_number_within_action) -> None``. Raises to inject."""


@dataclass
class ToolCallRecord:
    tool: str
    agent: str
    at: str
    allowed: bool
    duplicate: bool = False
    denial: dict[str, Any] | None = None
    policy_verdict: str = "NOT_EVALUATED"
    screen_findings: dict[str, Any] = field(default_factory=dict)
    fault_injected: str | None = None
    latency_ms: float = 0.0
    trace_id: str | None = None


@dataclass
class ToolBroker:
    transport: Transport
    principal_token_for: Callable[[AgentName], str]
    content_screen: ContentScreen | None = None
    semantic_policy: SemanticPolicy | None = None
    fault_hook: FaultHook | None = None
    on_record: Callable[[ToolCallRecord], None] | None = None
    max_tool_calls: int = 400

    _call_counts: dict[tuple[str, str], int] = field(default_factory=dict, init=False)
    _total_calls: int = field(default=0, init=False)
    records: list[ToolCallRecord] = field(default_factory=list, init=False)

    # -- the one entry point --------------------------------------------------------

    def call(
        self,
        agent: AgentName,
        tool_name: str,
        payload: dict[str, Any],
        *,
        system: bool = False,
    ) -> dict[str, Any]:
        """Route one tool call through every governance layer.

        ``system=True`` marks orchestrator-driven deterministic progress — requesting
        the transition the evidence already supports, or attempting closure. Those are
        not an agent exploring, so they do not consume the agent loop budget. They still
        pass every authorization and policy layer and are still recorded.
        """
        import time

        started = time.perf_counter()
        record = ToolCallRecord(tool=tool_name, agent=agent.value, at=now_iso(), allowed=False)
        spec = TOOL_REGISTRY.get(tool_name)

        with otel.span(
            f"tool.{tool_name}",
            **{
                otel.ATTR_TOOL: tool_name,
                otel.ATTR_AGENT: agent.value,
                otel.ATTR_SERVICE: spec.service if spec else "unregistered",
                otel.ATTR_INCIDENT: payload.get("incident_id"),
                otel.ATTR_ACTION_ID: payload.get("action_id"),
            },
        ):
            try:
                if not system:
                    self._budget_check(record)
                self._authorize(agent, tool_name, record)
                self._semantic(agent, tool_name, payload, record)
                self._inject_fault(tool_name, payload, record)

                result = self.transport.invoke(tool_name, self.principal_token_for(agent), payload)
                result = self._screen_response(tool_name, result, record)
                record.allowed = True
                record.duplicate = bool(result.get("duplicate_returned"))
                otel.set_attributes(
                    **{
                        otel.ATTR_DUPLICATE: record.duplicate,
                        otel.ATTR_POLICY: record.policy_verdict,
                        otel.ATTR_SCREEN: record.screen_findings.get("match_state"),
                        otel.ATTR_DECISION: "ALLOW",
                    }
                )
                return result
            except BrokerDeniedError as denied:
                otel.set_attributes(
                    **{
                        otel.ATTR_DECISION: "REFUSE",
                        otel.ATTR_INVARIANT: denied.decision.invariant,
                        otel.ATTR_FAILURE_CLASS: denied.decision.failure_class.value,
                    }
                )
                raise
            except Exception as exc:
                otel.record_exception(exc)
                raise
            finally:
                record.latency_ms = round((time.perf_counter() - started) * 1000, 2)
                record.trace_id = otel.current_trace_id()
                self.records.append(record)
                if self.on_record is not None:
                    self.on_record(record)

    # -- layers ---------------------------------------------------------------------

    def _budget_check(self, record: ToolCallRecord) -> None:
        self._total_calls += 1
        if self._total_calls > self.max_tool_calls:
            decision = Decision(
                verdict=__import__(
                    "nightshift.safety_kernel.decision", fromlist=["Verdict"]
                ).Verdict.REFUSE,
                reason=f"tool-call budget of {self.max_tool_calls} exceeded for this incident",
                invariant="LOOP-GUARD",
                denial_reason=DenialReason.BUDGET_EXCEEDED,
                failure_class=FailureClass.POLICY_DENIAL,
            )
            record.denial = decision.as_dict()
            raise BrokerDeniedError(decision)

    def _authorize(self, agent: AgentName, tool_name: str, record: ToolCallRecord) -> None:
        decision = authorize_tool(agent, tool_name)
        if not decision.allowed:
            record.denial = decision.as_dict()
            raise BrokerDeniedError(decision)

    def _semantic(
        self, agent: AgentName, tool_name: str, payload: dict[str, Any], record: ToolCallRecord
    ) -> None:
        if self.semantic_policy is None:
            record.policy_verdict = "UNAVAILABLE"
            return
        verdict, reason = self.semantic_policy.evaluate(agent, tool_name, payload)
        record.policy_verdict = verdict
        if verdict == "DENY":
            decision = Decision(
                verdict=__import__(
                    "nightshift.safety_kernel.decision", fromlist=["Verdict"]
                ).Verdict.REFUSE,
                reason=f"semantic policy denied: {reason}",
                invariant="SG",
                denial_reason=DenialReason.SEMANTIC_POLICY_DENY,
                failure_class=FailureClass.POLICY_DENIAL,
            )
            record.denial = decision.as_dict()
            raise BrokerDeniedError(decision)

    def _inject_fault(
        self, tool_name: str, payload: dict[str, Any], record: ToolCallRecord
    ) -> None:
        if self.fault_hook is None:
            return
        action_id = str(payload.get("action_id") or payload.get("placement_group_id") or "")
        key = (tool_name, action_id)
        self._call_counts[key] = self._call_counts.get(key, 0) + 1
        try:
            self.fault_hook(tool_name, action_id, self._call_counts[key])
        except Exception as exc:
            record.fault_injected = f"{type(exc).__name__}: {exc}"
            raise

    def _screen_response(
        self, tool_name: str, result: dict[str, Any], record: ToolCallRecord
    ) -> dict[str, Any]:
        """Screen untrusted tool output before it can reach the model's context.

        Only responses that can carry externally authored text are screened. Screening
        every numeric telemetry payload would burn budget without reducing risk.
        """
        if self.content_screen is None:
            return result
        untrusted = _untrusted_text(tool_name, result)
        if not untrusted:
            return result
        blocked, findings = self.content_screen.screen(untrusted, "response")
        record.screen_findings = findings
        if blocked:
            return {
                **{k: v for k, v in result.items() if k not in _UNTRUSTED_FIELDS},
                "content_screen": {
                    "blocked": True,
                    "findings": findings,
                    "note": (
                        "External content was withheld by content screening. The "
                        "authoritative fields above are unaffected."
                    ),
                },
            }
        return {**result, "content_screen": {"blocked": False, "findings": findings}}


_UNTRUSTED_FIELDS = {"vendor_response", "repair_note", "external_note", "notes", "document_text"}


def _untrusted_text(tool_name: str, result: dict[str, Any]) -> str:
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return ""
    parts: list[str] = []
    for field_name in _UNTRUSTED_FIELDS:
        value = result.get(field_name)
        if isinstance(value, str):
            parts.append(value)
    for event in result.get("repair_events", []) or []:
        if isinstance(event, dict) and isinstance(event.get("note"), str):
            parts.append(event["note"])
    return "\n".join(p for p in parts if p)
