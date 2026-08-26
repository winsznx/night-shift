"""Per-agent Google identity for outbound service calls.

The §11.3 permission matrix is only *enforced by Google* if the call actually arrives as
the agent's own service account. Using the container's ambient identity for every call —
which is what a plain ``fetch_id_token`` does — means the per-agent ``run.invoker``
grants are never exercised, and the Dispatch Agent's forbidden inventory call is refused
by our code rather than by Cloud Run.

This mints an OIDC ID token *as the agent's service account*, using IAM Credentials
short-lived-token impersonation. The runtime service account needs
``roles/iam.serviceAccountTokenCreator`` on each agent account, which the provisioning
script grants.

Degradation is explicit: if impersonation is unavailable (no metadata server, missing
grant, running locally), ``mint`` returns ``None`` along with the reason, and the caller
records that the platform-level identity layer was not exercised for that call. It never
silently falls back to a stronger ambient identity and lets the claim stand.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from nightshift.schemas.enums import AgentName

log = logging.getLogger(__name__)

AGENT_SERVICE_ACCOUNTS: dict[AgentName, str] = {
    AgentName.COMMANDER: "ns-commander",
    AgentName.SIGNAL_INVESTIGATOR: "ns-signal",
    AgentName.IMPACT_ANALYST: "ns-impact",
    AgentName.CAPACITY_BROKER: "ns-capacity",
    AgentName.DISPATCH_AGENT: "ns-dispatch",
    AgentName.CUSTODY_AGENT: "ns-custody",
    AgentName.INGESTOR: "ns-ingestor",
    AgentName.RESPONDER_APP: "ns-svc-bff",
    AgentName.DRILL_CONTROLLER: "ns-svc-bff",
}
"""Which Google service account each principal calls as.

The responder app and the drill controller are not agents; they run inside the BFF and
call as it.
"""

_TOKEN_TTL_S = 3000  # tokens are minted for an hour; refresh well before that


@dataclass
class _CachedToken:
    token: str
    minted_at: float

    @property
    def fresh(self) -> bool:
        return (time.time() - self.minted_at) < _TOKEN_TTL_S


@dataclass
class AgentTokenMinter:
    """Mints audience-scoped ID tokens as a given agent's service account."""

    project_id: str
    enabled: bool = True
    _cache: dict[tuple[str, str], _CachedToken] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _unavailable_reason: str = field(default="", init=False)

    def service_account(self, agent: AgentName) -> str:
        name = AGENT_SERVICE_ACCOUNTS.get(agent)
        if not (name and self.project_id):
            return ""
        return f"{name}@{self.project_id}.iam.gserviceaccount.com"

    def mint(self, agent: AgentName, audience: str) -> tuple[str | None, str]:
        """Return ``(token, reason)``. ``token`` is None when impersonation is unavailable."""
        if not self.enabled:
            return None, "per-agent impersonation disabled"
        sa = self.service_account(agent)
        if not sa:
            return None, f"no service account mapped for {agent.value}"

        key = (sa, audience)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.fresh:
                return cached.token, ""

        try:
            import google.auth
            import google.auth.transport.requests
            from google.auth import impersonated_credentials

            source, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials = impersonated_credentials.IDTokenCredentials(
                impersonated_credentials.Credentials(
                    source_credentials=source,
                    target_principal=sa,
                    target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    lifetime=3600,
                ),
                target_audience=audience,
                include_email=True,
            )
            credentials.refresh(google.auth.transport.requests.Request())
            token = str(credentials.token)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if reason != self._unavailable_reason:
                self._unavailable_reason = reason
                log.warning(
                    "per-agent impersonation unavailable for %s (%s); the call will not "
                    "exercise Cloud Run IAM and that is recorded, not papered over",
                    agent.value,
                    reason,
                )
            return None, reason

        with self._lock:
            self._cache[key] = _CachedToken(token=token, minted_at=time.time())
        return token, ""
