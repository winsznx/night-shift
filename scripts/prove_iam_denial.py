"""Prove the platform layer of the §11.3 matrix, live, against deployed Cloud Run.

PRD §11.4 asks for at least one real call where an agent identity attempts a forbidden
service and the platform denies it. Everything in the drill corpus runs through
``InProcessTransport``, where there is no network hop and therefore no Cloud Run edge —
our own broker refuses those calls. That is a real denial, but it is *our* denial, and
claiming Google enforced it would be an overclaim.

This makes the call for real:

* mint an OIDC ID token **as the Dispatch Agent's own service account**
* call the Inventory service, which the Dispatch Agent holds no authority on
* record what Cloud Run answers, before any Night Shift code runs

Then it does the same as an identity that *is* permitted, because a denial nobody can
contrast with an allow proves only that the endpoint is unreachable.

    uv run python scripts/prove_iam_denial.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.schemas.enums import AgentName
from services.common.identity import PRINCIPAL_HEADER, issue_principal_token
from services.gateway.identity_tokens import AgentTokenMinter

ROOT = Path(__file__).resolve().parents[1]

# (agent, service, url setting, probe path, what the §11.3 matrix says)
PROBES: list[tuple[AgentName, str, str, str, str]] = [
    (
        AgentName.DISPATCH_AGENT,
        "inventory",
        "inventory_url",
        "/v1/freezers/F-17/impacted",
        "forbidden",
    ),
    (
        AgentName.IMPACT_ANALYST,
        "inventory",
        "inventory_url",
        "/v1/freezers/F-17/impacted",
        "permitted",
    ),
    (
        AgentName.DISPATCH_AGENT,
        "facilities",
        "facilities_url",
        "/v1/responders",
        "permitted",
    ),
]


def main() -> int:
    settings = get_settings()
    minter = AgentTokenMinter(project_id=settings.project_id)

    rows: list[dict[str, Any]] = []
    for agent, service, url_attr, path, expectation in PROBES:
        base = getattr(settings, url_attr, "")
        if not base:
            print(f"skip {agent.value} -> {service}: no URL configured")
            continue

        token, reason = minter.mint(agent, base)
        row: dict[str, Any] = {
            "agent": agent.value,
            "service": service,
            "principal": minter.service_account(agent),
            "audience": base,
            "path": path,
            "matrix_expectation": expectation,
            "impersonated": token is not None,
            "impersonation_error": reason,
        }
        if token is None:
            row["result"] = "NOT_EXERCISED"
            rows.append(row)
            print(f"  {agent.value:<18} -> {service:<11} impersonation unavailable: {reason}")
            continue

        # A real call carries both credentials: the Google ID token that Cloud Run checks
        # at its edge, and the Night Shift principal assertion the service checks itself.
        # Sending only the first would make every permitted call fail at the app layer and
        # make the platform denial look indistinguishable from an ordinary rejection.
        headers = {
            "Authorization": f"Bearer {token}",
            PRINCIPAL_HEADER: issue_principal_token(agent, "rev-1", settings.agent_shared_secret),
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{base}{path}", headers=headers)

        row["status"] = response.status_code
        row["denied_by_platform"] = response.status_code in (401, 403)
        # Cloud Run's edge answers in HTML. A Night Shift refusal is JSON with an
        # invariant. Which one replied is the whole point, so record the shape.
        body = response.text[:300].replace("\n", " ")
        row["responder"] = (
            "cloud-run-edge"
            if response.status_code in (401, 403) and "<html" in body.lower()
            else "nightshift-service"
        )
        row["body_snippet"] = body
        row["result"] = "DENIED" if row["denied_by_platform"] else "ALLOWED"
        rows.append(row)

        print(
            f"  {agent.value:<18} -> {service:<11} {expectation:<10} "
            f"HTTP {response.status_code}  {row['result']} by {row['responder']}"
        )

    forbidden = [r for r in rows if r["matrix_expectation"] == "forbidden"]
    permitted = [r for r in rows if r["matrix_expectation"] == "permitted"]
    proven = bool(forbidden) and all(
        r.get("denied_by_platform") and r.get("responder") == "cloud-run-edge" for r in forbidden
    )
    contrasted = bool(permitted) and all(r.get("result") == "ALLOWED" for r in permitted)

    document = {
        "generated_at": now_iso(),
        "project": settings.project_id,
        "region": settings.region,
        "source_commit": settings.source_commit,
        "claim": (
            "An agent identity calling a service it holds no authority on is refused by "
            "Cloud Run IAM before the request reaches Night Shift code."
        ),
        "platform_denial_proven": proven,
        "contrasted_with_permitted_call": contrasted,
        "note": (
            "A denial alone would not distinguish enforcement from an unreachable "
            "endpoint, so a permitted identity calls the same route and is allowed."
        ),
        "probes": rows,
    }
    out = ROOT / "evidence" / "iam-denial.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"\nplatform denial proven      : {proven}")
    print(f"contrasted with allowed call: {contrasted}")
    print(f"written to {out.relative_to(ROOT)}")
    return 0 if proven and contrasted else 1


if __name__ == "__main__":
    raise SystemExit(main())
