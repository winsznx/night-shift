"""Run one Night Shift incident end to end and print what happened.

    uv run python scripts/run_incident.py                # local store, live Gemini
    uv run python scripts/run_incident.py --store firestore --namespace demo

This is the headline path: inject a freezer failure, let the fleet run, let the field
simulator produce responder scans, and report the deterministic outcome.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.config import get_settings  # noqa: E402
from nightshift.incident_runner import ScenarioConfig, run_incident  # noqa: E402
from nightshift.runtime import build_runtime  # noqa: E402
from nightshift.safety_kernel.invariants import check_all_invariants  # noqa: E402
from nightshift.common.clock import now_iso  # noqa: E402
from nightshift.safety_kernel.world import reconciliation_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one Night Shift incident.")
    p.add_argument("--store", default=None, choices=["memory", "firestore"])
    p.add_argument("--namespace", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--seed", type=int, default=20260826)
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--transfers", type=int, default=50)
    p.add_argument("--duplicate-delivery", action="store_true")
    p.add_argument("--json", action="store_true", help="emit machine-readable output only")
    return p.parse_args()


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    namespace = args.namespace or settings.namespace

    runtime = build_runtime(namespace=namespace, store_backend=args.store)
    scenario = ScenarioConfig(
        seed=args.seed,
        max_rounds=args.rounds,
        max_transfers=args.transfers,
        duplicate_delivery=args.duplicate_delivery,
    )

    if not args.json:
        print(f"store={runtime.repo.store.backend} namespace={namespace} "
              f"model={args.model or settings.model_id}")
        print("Injecting freezer failure and opening the incident…\n")

    runtime, run = await run_incident(
        runtime=runtime, scenario=scenario, namespace=namespace, model=args.model
    )

    state = runtime.repo.load_kernel_state(run.incident_id)
    now = now_iso()
    recon = reconciliation_snapshot(state)
    invariants = check_all_invariants(state, now, delivered_event_ids=run.delivered_event_ids)

    summary = {
        **run.as_dict(),
        "reconciliation": recon.as_dict(),
        "invariants": {r.invariant: r.holds for r in invariants},
        "failed_invariants": [r.invariant for r in invariants if not r.holds],
        "tool_calls": len(runtime.broker.records),
        "tool_denials": sum(1 for r in runtime.broker.records if r.denial),
        "duplicate_receipts": sum(1 for r in runtime.broker.records if r.duplicate),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0 if not summary["failed_invariants"] else 1

    o = run.outcome
    print(f"Incident      {run.incident_id}")
    print(f"Final state   {o.final_state if o else 'UNKNOWN'}")
    print(f"Rounds        {o.rounds if o else 0}   stopped: {o.stopped_because if o else ''}")
    print(f"Specialists   {', '.join(r.agent.value for r in o.specialist_results) if o else ''}")
    print()
    print(f"Impacted      {recon.total} container(s)")
    print(f"  committed   {len(recon.committed)}")
    print(f"  quarantined {len(recon.quarantined)}")
    print(f"  in flight   {len(recon.in_flight)}")
    print(f"  unresolved  {len(recon.unresolved)}")
    print(f"  complete    {recon.complete}")
    print()
    print(f"Tool calls    {summary['tool_calls']}  "
          f"(denied {summary['tool_denials']}, duplicate receipts {summary['duplicate_receipts']})")
    print()
    print("Invariants:")
    for r in invariants:
        print(f"  {'PASS' if r.holds else 'FAIL'}  {r.invariant:<4} {r.title:<34} {r.detail[:70]}")
    if run.notes:
        print()
        print("Notes:")
        for n in run.notes:
            print(f"  - {n}")

    failed = [r for r in invariants if not r.holds]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
