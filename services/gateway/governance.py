"""Model Armor and Semantic Governance adapters.

Both layers are probabilistic. Neither is allowed to be the only reason an unsafe thing
did not happen, and both are allowed to be unavailable — Night Shift records the
degradation and keeps running on the deterministic layers (PRD §32.6, §32.7).

``ModelArmorScreen`` calls the live Model Armor API when a template is configured.
``HeuristicScreen`` is the offline stand-in used by the deterministic drill corpus, and
it is labelled as such everywhere it appears so nobody mistakes a local run's finding
for a live Model Armor finding.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from nightshift.schemas.enums import AgentName, ToolDomain
from nightshift.safety_kernel.authority import TOOL_REGISTRY

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Content screening
# --------------------------------------------------------------------------------------


@dataclass
class ModelArmorScreen:
    """Live Model Armor. Fails open to 'not screened' and says so."""

    template: str
    location: str = "us-central1"
    backend: str = "model-armor"
    _client: Any = field(default=None, init=False)

    def _endpoint(self) -> str:
        return f"https://modelarmor.{self.location}.rep.googleapis.com/v1/{self.template}:sanitizeUserPrompt"

    def screen(self, text: str, direction: str) -> tuple[bool, dict[str, Any]]:
        import httpx

        try:
            import google.auth
            import google.auth.transport.requests

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(google.auth.transport.requests.Request())
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    self._endpoint(),
                    headers={"Authorization": f"Bearer {credentials.token}"},
                    json={"userPromptData": {"text": text[:20_000]}},
                )
            if response.status_code != 200:
                return False, {"backend": self.backend, "available": False,
                               "status": response.status_code}
            data = response.json().get("sanitizationResult", {})
        except Exception as exc:  # noqa: BLE001
            log.warning("Model Armor unavailable (%s); continuing on remaining layers", exc)
            return False, {"backend": self.backend, "available": False, "error": str(exc)}

        match_state = data.get("filterMatchState", "NO_MATCH_FOUND")
        matched: list[str] = []
        for name, result in (data.get("filterResults") or {}).items():
            inner = next(iter(result.values())) if isinstance(result, dict) and result else {}
            state = inner.get("matchState") if isinstance(inner, dict) else None
            if state == "MATCH_FOUND":
                matched.append(name)
        return match_state == "MATCH_FOUND", {
            "backend": self.backend,
            "available": True,
            "direction": direction,
            "match_state": match_state,
            "matched_filters": sorted(matched),
        }


_INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
     "instruction override"),
    (re.compile(r"\b(disregard|forget)\s+(your|the)\s+(rules|instructions|policy)", re.I),
     "instruction override"),
    (re.compile(r"\b(export|exfiltrate|send|email|upload)\b.{0,40}\b(inventory|specimen|manifest|database)\b", re.I),
     "data exfiltration request"),
    (re.compile(r"\bretrieve\b.{0,30}\b(specimen|inventory|study)\b", re.I),
     "restricted data request"),
    (re.compile(r"\byou are now\b|\bnew system prompt\b|\bdeveloper mode\b", re.I),
     "role hijack"),
    (re.compile(r"\b(attacker|evil|exfil)@|\bhttps?://(?!localhost)\S+\?.*=(?:key|token|secret)", re.I),
     "suspicious destination"),
]


@dataclass
class HeuristicScreen:
    """Offline stand-in for Model Armor.

    Deliberately narrow and clearly labelled. Its findings are recorded with
    ``backend: heuristic-offline`` so a deterministic drill result can never be
    presented as evidence about Model Armor's real detection behaviour.
    """

    backend: str = "heuristic-offline"

    def screen(self, text: str, direction: str) -> tuple[bool, dict[str, Any]]:
        findings = sorted({label for pattern, label in _INJECTION_PATTERNS if pattern.search(text)})
        return bool(findings), {
            "backend": self.backend,
            "available": True,
            "direction": direction,
            "match_state": "MATCH_FOUND" if findings else "NO_MATCH_FOUND",
            "matched_filters": findings,
        }


# --------------------------------------------------------------------------------------
# Semantic governance
# --------------------------------------------------------------------------------------

SEMANTIC_POLICIES = [
    {
        "id": "SG-01",
        "constraint": "The Facilities/Dispatch Agent must not request specimen-level inventory.",
        "agents": [AgentName.DISPATCH_AGENT],
        "forbidden_domains": [
            ToolDomain.INVENTORY_SCOPED_READ,
            ToolDomain.INVENTORY_INCIDENT_READ,
            ToolDomain.INVENTORY_PLACEMENT_VIEW,
            ToolDomain.INVENTORY_WRITE,
        ],
    },
    {
        "id": "SG-02",
        "constraint": "The Capacity Broker must not call custody mutation tools.",
        "agents": [AgentName.CAPACITY_BROKER],
        "forbidden_domains": [ToolDomain.CUSTODY_WRITE],
    },
    {
        "id": "SG-03",
        "constraint": "The Custody Agent must not create or alter maintenance work orders.",
        "agents": [AgentName.CUSTODY_AGENT],
        "forbidden_domains": [ToolDomain.FACILITIES_WRITE],
    },
    {
        "id": "SG-04",
        "constraint": (
            "Any agent requesting incident closeout while unresolved containers remain "
            "should be denied or escalated."
        ),
        "agents": [AgentName.COMMANDER],
        "forbidden_domains": [],
        "special": "closeout_guard",
    },
    {
        "id": "SG-05",
        "constraint": (
            "External communication must not include synthetic study metadata beyond the "
            "minimum equipment context."
        ),
        "agents": [AgentName.DISPATCH_AGENT],
        "forbidden_domains": [],
        "special": "vendor_egress",
    },
]
"""The §12 constraint set.

Each one is *also* enforced deterministically somewhere: SG-01/02/03 by the §11.3
matrix, SG-04 by N6, SG-05 by the Facilities egress filter. That redundancy is the
point — the semantic layer can be wrong in either direction without changing what is
actually possible.
"""


@dataclass
class LocalSemanticPolicy:
    """Deterministic evaluation of the semantic constraint set.

    Mode ``dry_run`` observes and reports without denying (PRD §12: deploy dry-run
    first, validate logs, then enforce). Mode ``enforce`` denies.
    """

    mode: str = "dry_run"
    observations: list[dict[str, Any]] = field(default_factory=list)

    def evaluate(
        self, agent: AgentName, tool_name: str, payload: dict[str, Any]
    ) -> tuple[str, str]:
        spec = TOOL_REGISTRY.get(tool_name)
        if spec is None:
            return "ALLOW", ""

        for policy in SEMANTIC_POLICIES:
            if agent not in policy["agents"]:
                continue
            hit = spec.domain in policy["forbidden_domains"]
            if policy.get("special") == "closeout_guard" and tool_name == "request_incident_close":
                hit = False  # N6 owns this; the semantic layer only observes it.
            if not hit:
                continue
            reason = f"{policy['id']}: {policy['constraint']}"
            self.observations.append(
                {"policy": policy["id"], "agent": agent.value, "tool": tool_name,
                 "mode": self.mode, "would_deny": True}
            )
            return ("DENY" if self.mode == "enforce" else "OBSERVE_WOULD_DENY"), reason
        return "ALLOW", ""


def build_content_screen(template: str, location: str = "us-central1") -> Any:
    """Live Model Armor when a template is configured, heuristic stand-in otherwise."""
    return ModelArmorScreen(template=template, location=location) if template else HeuristicScreen()
