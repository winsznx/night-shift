"""Publish the six agents to the Google Cloud Agent Registry, as a catalog.

    uv run python infra/deploy/register_agents.py            # dry run
    uv run python infra/deploy/register_agents.py --apply
    uv run python infra/deploy/register_agents.py --snapshot # write what exists to Firestore

The Fortified Enterprise Fleet track asks that agents be cataloged for cross-department
use. A catalog entry is only worth having if it says something true about the agent, so
each one carries the authority the permission matrix actually grants: the service account
the agent calls as, its authority domains, and how many of the registry's tools it may
and may not reach. Those come from ``nightshift.safety_kernel.authority`` rather than
from a hand-maintained list, so an entry cannot drift from what the broker enforces.

Two things about this surface are worth knowing before reading the output.

It is ``v1beta1`` and ``global`` only. The ``v1`` endpoint answers "This API version is
not supported by AgentService", and ``us-central1`` answers "The valid location ID is
`global`", which is the same global-only trap the Gemini endpoint already has.

``base_agent`` is a required immutable field whose only accepted value on this project is
a preview identifier. It does not describe what executes. What executes is the ADK fleet
in ``agents/fleet.py`` against Cloud Run services. The registry entry is a catalog record
and is described that way everywhere it is mentioned.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nightshift.common.config import get_settings
from nightshift.safety_kernel.authority import AGENT_TOOL_DOMAINS, TOOL_REGISTRY, tools_for
from nightshift.schemas.enums import AgentName
from services.gateway.identity_tokens import AGENT_SERVICE_ACCOUNTS

API = "https://aiplatform.googleapis.com/v1beta1"
LOCATION = "global"
BASE_AGENT = "antigravity-preview-05-2026"

REGISTERED = [
    AgentName.COMMANDER,
    AgentName.SIGNAL_INVESTIGATOR,
    AgentName.IMPACT_ANALYST,
    AgentName.CAPACITY_BROKER,
    AgentName.DISPATCH_AGENT,
    AgentName.CUSTODY_AGENT,
]

DESCRIPTIONS: dict[AgentName, str] = {
    AgentName.COMMANDER: (
        "Owns the incident plan and decides which specialist works next. Holds no domain "
        "write authority of its own."
    ),
    AgentName.SIGNAL_INVESTIGATOR: (
        "Read-only telemetry and equipment history. Distinguishes a door excursion from a "
        "transient event from a likely equipment failure."
    ),
    AgentName.IMPACT_ANALYST: (
        "Scoped inventory reads. Identifies affected containers, maps them to study "
        "criticality, and produces an immutable impact snapshot."
    ),
    AgentName.CAPACITY_BROKER: (
        "Inspects verified backup freezer state and reserves placement capacity. Cannot "
        "commit custody."
    ),
    AgentName.DISPATCH_AGENT: (
        "Creates repair work orders and dispatches the on-call responder. Holds no "
        "inventory access at all, which Cloud Run IAM enforces at the edge."
    ),
    AgentName.CUSTODY_AGENT: (
        "Validates source and destination scans and commits container location only when "
        "the evidence is complete and fresh."
    ),
}


def token() -> str:
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def payload_for(agent: AgentName, project: str) -> dict[str, Any]:
    allowed = sorted(tools_for(agent))
    forbidden = sorted(set(TOOL_REGISTRY) - set(allowed))
    account = AGENT_SERVICE_ACCOUNTS[agent]
    return {
        "id": agent.value,
        "base_agent": BASE_AGENT,
        "description": DESCRIPTIONS[agent],
        # metadata is map<string,string>, so lists are joined rather than nested.
        "metadata": {
            "fleet": "night-shift",
            "service_account": f"{account}@{project}.iam.gserviceaccount.com",
            "authority_domains": ",".join(
                sorted(d.value for d in AGENT_TOOL_DOMAINS.get(agent, []))
            ),
            "tools_allowed": ",".join(allowed),
            "tools_allowed_count": str(len(allowed)),
            "tools_forbidden_count": str(len(forbidden)),
            "enforced_by": "night-shift-broker,domain-service,cloud-run-iam",
            "authority_source": "nightshift/safety_kernel/authority.py",
            "executes_as": "google-adk LlmAgent in agents/fleet.py, not this record",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create missing agents")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="write what currently exists into Firestore for /api/fleet to read",
    )
    args = parser.parse_args()

    import httpx

    settings = get_settings()
    project = settings.project_id
    if not project:
        print("no GOOGLE_CLOUD_PROJECT", file=sys.stderr)
        return 1
    parent = f"projects/{project}/locations/{LOCATION}"
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}

    if not args.apply and not args.snapshot:
        print("DRY RUN. Nothing will be written. Re-run with --apply.\n")

    existing: dict[str, dict[str, Any]] = {}
    created = skipped = failed = 0

    with httpx.Client(timeout=60.0, headers=headers) as client:
        for agent in REGISTERED:
            url = f"{API}/{parent}/agents/{agent.value}"
            probe = client.get(url)
            if probe.status_code == 200:
                existing[agent.value] = probe.json()
                print(f"[exists]  {agent.value}")
                skipped += 1
                continue
            if probe.status_code != 404:
                print(f"[warn]    {agent.value}: HTTP {probe.status_code} on lookup, not creating")
                failed += 1
                continue

            body = payload_for(agent, project)
            if not args.apply:
                print(f"[create]  {agent.value}")
                print("          " + json.dumps(body["metadata"], indent=2).replace("\n", "\n          "))
                continue

            response = client.post(f"{API}/{parent}/agents", json=body)
            if response.status_code == 200:
                print(f"[created] {agent.value}")
                created += 1
                settled = client.get(url)
                if settled.status_code == 200:
                    existing[agent.value] = settled.json()
            else:
                print(f"[failed]  {agent.value}: HTTP {response.status_code} {response.text[:300]}")
                failed += 1

    print(f"\ncreated {created}, already present {skipped}, failed {failed}")

    if args.snapshot or args.apply:
        _write_snapshot(existing, project)
    return 0 if failed == 0 else 1


def _write_snapshot(existing: dict[str, dict[str, Any]], project: str) -> None:
    """Record what the registry actually holds, for ``/api/fleet`` to render.

    Written to Firestore rather than to a file in the image, so a registration performed
    after the build becomes visible without another build. Only agents that genuinely
    came back from a GET are written: an entry this snapshot claims and the registry does
    not hold would be exactly the overclaim the fleet page exists to avoid.
    """
    from nightshift.common.clock import now_iso
    from services.common.repository import Repository

    settings = get_settings()
    agents = {
        agent_id: {
            "identity": (body.get("metadata") or {}).get("service_account"),
            "registry_resource": body.get("name"),
            "registered_at": body.get("created"),
        }
        for agent_id, body in existing.items()
    }
    for namespace in {settings.namespace, "demo", "demo2"}:
        repo = Repository.create(
            settings.store_backend,
            project=project,
            database=settings.firestore_database,
            namespace=namespace,
        )
        repo.store.set(
            "registrySnapshot",
            "current",
            {"agents": agents, "recorded_at": now_iso(), "location": LOCATION},
        )
    print(f"snapshot written for {len(agents)} agent(s)")


if __name__ == "__main__":
    raise SystemExit(main())
