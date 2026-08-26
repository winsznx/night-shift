"""The kernel's answer type.

There are exactly three outcomes and none of them is "probably fine". A refusal always
names the invariant that produced it so the UI, the ledger, and the verifier all quote
the same reason string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nightshift.schemas.enums import DenialReason, FailureClass


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"
    UNAVAILABLE = "UNAVAILABLE"
    """Safety-critical evidence could not be read. Fails closed under N11."""


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    invariant: str | None = None
    denial_reason: DenialReason | None = None
    failure_class: FailureClass = FailureClass.NONE
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "invariant": self.invariant,
            "denial_reason": self.denial_reason.value if self.denial_reason else None,
            "failure_class": self.failure_class.value,
            "detail": self.detail,
        }


def allow(detail: dict[str, Any] | None = None) -> Decision:
    return Decision(verdict=Verdict.ALLOW, detail=detail or {})


def refuse(
    invariant: str,
    reason: str,
    *,
    denial_reason: DenialReason = DenialReason.INVARIANT_VIOLATION,
    failure_class: FailureClass = FailureClass.INVARIANT_REJECTION,
    detail: dict[str, Any] | None = None,
) -> Decision:
    return Decision(
        verdict=Verdict.REFUSE,
        reason=reason,
        invariant=invariant,
        denial_reason=denial_reason,
        failure_class=failure_class,
        detail=detail or {},
    )


def unavailable(
    invariant: str, reason: str, detail: dict[str, Any] | None = None
) -> Decision:
    return Decision(
        verdict=Verdict.UNAVAILABLE,
        reason=reason,
        invariant=invariant,
        failure_class=FailureClass.INFRASTRUCTURE,
        detail=detail or {},
    )
