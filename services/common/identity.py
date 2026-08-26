"""Agent principal identity at the service boundary.

Two layers, both real:

* **Transport identity** — on Cloud Run, each service requires a Google-issued OIDC ID
  token and each agent runs under its own service account. That is what actually stops
  an unauthenticated caller.
* **Principal assertion** — the agent's Night Shift identity, carried in a signed
  header and verified here, then checked against the §11.3 matrix.

The second layer exists because the first one alone cannot distinguish two agents that
share a runtime. Both are enforced; neither is decorative. Crucially, the domain
services re-check authority themselves, so an agent that skipped the tool broker
gateway gains nothing — the answer is the same refusal, just later.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from nightshift.common.canonical import canonical_bytes
from nightshift.safety_kernel.authority import authorize_tool
from nightshift.safety_kernel.decision import Decision, refuse
from nightshift.schemas.enums import AgentName, DenialReason, FailureClass

PRINCIPAL_HEADER = "x-nightshift-principal"
TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class AgentPrincipal:
    agent: AgentName
    revision: str
    issued_at: int
    service_account: str | None = None
    """The Google service account the call actually arrived under, when available."""

    @property
    def identity(self) -> str:
        return self.agent.value


class PrincipalError(ValueError):
    """The principal assertion is absent, malformed, expired, or forged."""


def issue_principal_token(agent: AgentName, revision: str, secret: str,
                          issued_at: int | None = None) -> str:
    issued_at = issued_at if issued_at is not None else int(time.time())
    body = f"{agent.value}:{revision}:{issued_at}"
    mac = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}:{mac}"


def verify_principal_token(
    token: str, secret: str, *, now: int | None = None, ttl: int = TOKEN_TTL_SECONDS
) -> AgentPrincipal:
    parts = token.split(":")
    if len(parts) != 4:
        raise PrincipalError("malformed principal token")
    agent_raw, revision, issued_raw, mac = parts

    expected = hmac.new(
        secret.encode("utf-8"), f"{agent_raw}:{revision}:{issued_raw}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, mac):
        raise PrincipalError("principal token signature does not verify")

    try:
        issued_at = int(issued_raw)
    except ValueError:
        raise PrincipalError("principal token timestamp is not an integer") from None

    now = now if now is not None else int(time.time())
    if now - issued_at > ttl:
        raise PrincipalError("principal token has expired")

    try:
        agent = AgentName(agent_raw)
    except ValueError:
        raise PrincipalError(f"unknown agent identity {agent_raw!r}") from None

    return AgentPrincipal(agent=agent, revision=revision, issued_at=issued_at)


def authorize(principal: AgentPrincipal | None, tool_name: str) -> Decision:
    """Server-side authority check. Runs even when the broker already checked."""
    if principal is None:
        return refuse(
            "N7",
            "no verified principal on the request; unauthenticated callers hold no authority",
            denial_reason=DenialReason.IDENTITY_NOT_PERMITTED,
            failure_class=FailureClass.POLICY_DENIAL,
            detail={"tool": tool_name},
        )
    return authorize_tool(principal.agent, tool_name)


# --------------------------------------------------------------------------------------
# Responder task tokens
# --------------------------------------------------------------------------------------


def responder_task_signature(task_token: str, body: dict[str, object]) -> str:
    """HMAC over a responder scan body, keyed by the task token.

    Threat model §31 "forged responder event": the token is unguessable and scoped to
    one dispatch, and the body is bound to it, so a replayed body from a different task
    fails verification rather than silently entering the custody chain.
    """
    return hmac.new(task_token.encode("utf-8"), canonical_bytes(body), hashlib.sha256).hexdigest()


def verify_responder_signature(task_token: str, body: dict[str, object], signature: str) -> bool:
    return hmac.compare_digest(responder_task_signature(task_token, body), signature)
