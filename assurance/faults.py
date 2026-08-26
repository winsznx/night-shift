"""Deterministic fault injection.

Faults are keyed on ``(tool_name, action_id, call_number_within_action)`` rather than on
wall-clock timing (PRD §23.3). That matters: "fail the second call to reserve_capacity
for this placement group" reproduces exactly, whereas "fail 400ms in" reproduces
differently on every machine and every rerun.

The injector sits in the broker's fault hook, which is *after* authorization and
*before* transport — the same place a network partition or a proxy fault would land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.gateway.transport import TransportError


class InjectedCommitLoss(TransportError):
    """The effect committed; the response never came back.

    Subclasses ``TransportError`` on purpose: the agent must experience this exactly as
    it would a real partition, which means it is attributed as infrastructure (N12) and
    not as an agent safety failure.
    """


class InjectedToolFailure(TransportError):
    """The tool never ran. A plain infrastructure error."""


@dataclass
class FaultSpec:
    tool: str
    call_number: int = 1
    """Which call within the (tool, action_id) key to fault. 1-indexed.

    ``0`` means every call, which is how a service that is genuinely down behaves —
    faulting only the first call would let a bare retry succeed and prove nothing.
    """
    action_id_contains: str = ""
    """Optional filter so a fault can target one placement group or container."""
    kind: str = "commit_loss"
    """``commit_loss`` = effect commits, response lost. ``tool_failure`` = never ran."""
    message: str = ""
    max_injections: int = 1

    def matches(self, tool: str, action_id: str, call_number: int) -> bool:
        if tool != self.tool:
            return False
        if self.call_number and call_number != self.call_number:
            return False
        return not self.action_id_contains or self.action_id_contains in action_id


@dataclass
class FaultInjector:
    specs: list[FaultSpec] = field(default_factory=list)
    injected: list[dict[str, Any]] = field(default_factory=list)
    _counts: dict[int, int] = field(default_factory=dict, init=False)

    def __call__(self, tool: str, action_id: str, call_number: int) -> None:
        for index, spec in enumerate(self.specs):
            if self._counts.get(index, 0) >= spec.max_injections:
                continue
            if not spec.matches(tool, action_id, call_number):
                continue
            self._counts[index] = self._counts.get(index, 0) + 1
            record = {
                "tool": tool,
                "action_id": action_id,
                "call_number": call_number,
                "kind": spec.kind,
                "spec_index": index,
            }
            self.injected.append(record)
            message = spec.message or (
                f"injected {spec.kind} on call {call_number} of {tool}"
            )
            if spec.kind == "commit_loss":
                # The distinguishing detail: the tool is allowed to run first, and only
                # its *response* is lost. That is what makes the retry meet an existing
                # receipt rather than an empty store.
                raise InjectedCommitLoss(message)
            raise InjectedToolFailure(message)

    @property
    def fault_log(self) -> list[dict[str, Any]]:
        return list(self.injected)

    def fired(self) -> bool:
        return bool(self.injected)


class CommitThenLoseTransport:
    """Wraps a transport so a faulted call still commits before the response is lost.

    A fault hook that raises *before* transport would simulate "the call never
    happened", which is the easy case. The interesting case — and the one PRD §22 asks
    about — is "the effect exists but nobody knows". This wrapper produces that by
    invoking the real transport and then discarding its result.
    """

    def __init__(self, inner: Any, injector: FaultInjector) -> None:
        self._inner = inner
        self._injector = injector
        self._counts: dict[tuple[str, str], int] = {}

    def invoke(self, tool_name: str, principal_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        action_key = str(
            payload.get("action_id") or payload.get("placement_group_id")
            or payload.get("container_id") or ""
        )
        key = (tool_name, action_key)
        self._counts[key] = self._counts.get(key, 0) + 1
        call_number = self._counts[key]

        spec = self._matching_spec(tool_name, action_key, call_number)
        if spec is None:
            return self._inner.invoke(tool_name, principal_token, payload)

        if spec.kind == "tool_failure":
            self._record(spec, tool_name, action_key, call_number)
            raise InjectedToolFailure(
                spec.message or f"injected tool failure on {tool_name}"
            )

        # commit_loss: let the effect land, then lose the response.
        self._inner.invoke(tool_name, principal_token, payload)
        self._record(spec, tool_name, action_key, call_number)
        raise InjectedCommitLoss(
            spec.message
            or f"{tool_name} committed but the response was lost (call {call_number})"
        )

    def _matching_spec(self, tool: str, action_id: str, call_number: int) -> FaultSpec | None:
        for index, spec in enumerate(self._injector.specs):
            if self._injector._counts.get(index, 0) >= spec.max_injections:
                continue
            if spec.matches(tool, action_id, call_number):
                return spec
        return None

    def _record(self, spec: FaultSpec, tool: str, action_id: str, call_number: int) -> None:
        index = self._injector.specs.index(spec)
        self._injector._counts[index] = self._injector._counts.get(index, 0) + 1
        self._injector.injected.append(
            {
                "tool": tool,
                "action_id": action_id,
                "call_number": call_number,
                "kind": spec.kind,
                "spec_index": index,
            }
        )
