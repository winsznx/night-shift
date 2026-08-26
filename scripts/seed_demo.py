"""Seed the live demo: run a real incident and publish its signed evidence.

    uv run python scripts/seed_demo.py --store firestore --namespace demo

Runs the full agent fleet against the configured store, then compiles, signs, and
publishes the evidence bundle. This is what populates the public judge path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.common.skills import load_skills
from nightshift.evidence.store import record_manifest_in_store, write_evidence
from nightshift.incident_runner import ScenarioConfig, run_incident
from nightshift.runtime import build_runtime
from nightshift.safety_kernel.authority import AGENT_TOOL_DOMAINS
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import AgentName


def source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return get_settings().source_commit


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed the live Night Shift demo.")
    p.add_argument("--store", default=None, choices=["memory", "firestore"])
    p.add_argument("--namespace", default=None)
    p.add_argument("--seed", type=int, default=20260826)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--driver", default="agent", choices=["agent", "scripted"])
    p.add_argument("--no-upload", action="store_true", help="skip Cloud Storage upload")
    p.add_argument(
        "--publish-only",
        default=None,
        metavar="INCIDENT_ID",
        help=(
            "Publish evidence for an incident that already ran, instead of running a new "
            "one. Re-running a completed rescue to obtain its manifest would either "
            "duplicate effects or open a second incident for the same real-world "
            "condition, so the publish step has to be reachable on its own."
        ),
    )
    return p.parse_args()


@dataclass
class _AlreadyRan:
    """Stands in for a run result when the incident already completed.

    Carries only what the evidence bundle needs. The opening event ids and estate hash
    are recovered from the stored incident rather than invented, so a published manifest
    never claims provenance the run did not actually have.
    """

    incident_id: str
    repo: Any

    @property
    def delivered_event_ids(self) -> list[str]:
        incident = self.repo.get_incident(self.incident_id)
        return list(getattr(incident, "source_event_ids", None) or [])

    @property
    def estate_hash(self) -> str:
        from fixtures.estate import build_estate, estate_hash

        return estate_hash(build_estate())


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    namespace = args.namespace or settings.namespace

    runtime = build_runtime(namespace=namespace, store_backend=args.store)
    print(
        f"store={runtime.repo.store.backend} namespace={namespace} "
        f"driver={args.driver} model={settings.model_id}",
        flush=True,
    )

    if args.publish_only:
        run = _AlreadyRan(incident_id=args.publish_only, repo=runtime.repo)
    else:
        runtime, run = await run_incident(
            runtime=runtime,
            scenario=ScenarioConfig(seed=args.seed, max_rounds=args.rounds, max_transfers=50),
            namespace=namespace,
            driver=args.driver,
        )

    state = runtime.repo.load_kernel_state(run.incident_id)
    recon = reconciliation_snapshot(state)
    print(
        f"\nincident {run.incident_id}: {state.incident.state.value if state.incident else '?'} "
        f"({len(recon.committed)}/{recon.total} committed, "
        f"{len(recon.unresolved)} unresolved)",
        flush=True,
    )

    from google.adk.version import __version__ as adk_version

    bundle = write_evidence(
        state,
        settings=settings,
        upload=not args.no_upload,
        evaluated_at=now_iso(),
        estate_fixture_hash=run.estate_hash,
        opening_evidence=[{"event_id": eid, "kind": "sensor"} for eid in run.delivered_event_ids],
        agents=[
            {
                "agent": a.value,
                "revision": "rev-1",
                "authority_domains": sorted(d.value for d in AGENT_TOOL_DOMAINS[a]),
            }
            for a in [
                AgentName.COMMANDER,
                AgentName.SIGNAL_INVESTIGATOR,
                AgentName.IMPACT_ANALYST,
                AgentName.CAPACITY_BROKER,
                AgentName.DISPATCH_AGENT,
                AgentName.CUSTODY_AGENT,
            ]
        ],
        skill_revisions={n: s.revision for n, s in load_skills().items()},
        policy_refs={
            "semantic_governance_mode": runtime.semantic_policy.mode,
            "observations": len(runtime.semantic_policy.observations),
        },
        trace_ids=sorted(
            {rc.trace_id for rc in state.receipts.values() if rc.trace_id}
            | (
                {state.incident.trace_root_id}
                if state.incident and state.incident.trace_root_id
                else set()
            )
        ),
        delivered_event_ids=run.delivered_event_ids,
        source_commit=source_commit(),
        deployment_env=settings.deployment_env,
        model_id=settings.model_id,
        adk_version=adk_version,
        corpus_version="1.0.0",
        limitations=[
            "The research estate, specimen records, and responder roster are synthetic.",
            "Responder scans in this run were produced by the bounded field simulator; "
            "no physical movement occurred.",
            f"Content screening used the {getattr(runtime.content_screen, 'backend', 'unknown')} "
            "backend.",
        ],
    )
    record_manifest_in_store(runtime.repo, bundle)

    print(json.dumps(bundle.as_dict(), indent=2), flush=True)

    from nightshift.verify.verifier import verify_manifest_file

    result = verify_manifest_file(bundle.manifest_path)
    print()
    print(result.render(), flush=True)
    return 0 if result.status.value in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
