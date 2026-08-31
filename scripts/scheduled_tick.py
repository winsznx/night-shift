"""Keep Night Shift running on its own, on a schedule, for the judging window.

Two modes, run as a Cloud Run Job by Cloud Scheduler.

``--mode telemetry`` writes one current reading for every healthy freezer. It calls no
model. Without it the estate's telemetry is written once and then ages, every backup
destination crosses the 900-second N4 freshness window, and the console reads as a dead
system to anyone who opens it more than fifteen minutes after a seed. That is the
kernel behaving correctly against a world that stopped, and the fix is to stop the world
stopping.

``--mode incident`` runs the real agent fleet end to end and publishes a fresh
KMS-signed manifest. This is the part that has to actually be true rather than
asserted: the Fortified Enterprise Fleet track asks for context safely maintained
across weeks of asynchronous operations, and the only honest way to show that is to
still be running in week three.

Both modes are bounded and both refuse to spend past a cap. An unattended agent with a
model budget and no ceiling is how a hackathon project turns into a bill.

    python scripts/scheduled_tick.py --mode telemetry
    python scripts/scheduled_tick.py --mode incident --max-per-day 4
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.runtime import build_runtime

BUDGET_COLLECTION = "scheduledRuns"
"""Where the spend guard keeps its count.

Firestore rather than a process variable, because every scheduled run is a new
container and a counter that resets on start is not a cap.
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", required=True, choices=["telemetry", "incident"])
    p.add_argument("--namespace", default=None)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument(
        "--max-per-day",
        type=int,
        default=4,
        help="hard ceiling on model-driven runs per UTC day; telemetry ticks are exempt",
    )
    p.add_argument(
        "--max-total",
        type=int,
        default=200,
        help="hard ceiling on model-driven runs for the life of the deployment",
    )
    return p.parse_args()


def _budget_key(day: str) -> str:
    return f"incident-{day}"


def _check_and_claim_budget(repo: Any, max_per_day: int, max_total: int) -> tuple[bool, str]:
    """Claim one model-driven run against the daily and lifetime caps.

    Claim-before-run on purpose. A crash after the claim costs one slot, which is the
    right way for this to fail: the alternative loses the count on every crash and turns
    a crash loop into unbounded spend.
    """
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    today = repo.store.get(BUDGET_COLLECTION, _budget_key(day)) or {}
    lifetime = repo.store.get(BUDGET_COLLECTION, "lifetime") or {}

    today_count = int(today.get("count", 0))
    lifetime_count = int(lifetime.get("count", 0))

    if today_count >= max_per_day:
        return False, f"daily cap reached: {today_count}/{max_per_day} runs on {day}"
    if lifetime_count >= max_total:
        return False, f"lifetime cap reached: {lifetime_count}/{max_total} runs"

    repo.store.set(
        BUDGET_COLLECTION,
        _budget_key(day),
        {"day": day, "count": today_count + 1, "updated_at": now_iso()},
    )
    repo.store.set(
        BUDGET_COLLECTION,
        "lifetime",
        {"count": lifetime_count + 1, "updated_at": now_iso()},
    )
    return True, f"claimed run {today_count + 1}/{max_per_day} for {day}"


def run_telemetry_tick(namespace: str | None) -> int:
    """One current reading per healthy freezer. No model, no incident, no writes to custody."""
    from nightshift.incident_runner import _emit_sensor_tick

    runtime = build_runtime(namespace=namespace)
    _emit_sensor_tick(runtime)

    now = now_iso()
    from nightshift.common.clock import age_seconds

    ages = [
        (f.id, round(age_seconds(f.last_reading_at, now), 1)) for f in runtime.repo.list_freezers()
    ]
    stale = [f"{fid} {age}s" for fid, age in ages if age > 900]
    print(f"telemetry tick at {now} across {len(ages)} freezer(s)", flush=True)
    if not ages:
        # An empty estate means the namespace was never seeded. Say so rather than
        # crashing on an empty min(), because this runs unattended and the log line is
        # the only thing anyone will see.
        print("  no freezers in this namespace; nothing to refresh", flush=True)
        return 0
    print(f"  freshest {min(a for _, a in ages)}s, oldest {max(a for _, a in ages)}s", flush=True)
    if stale:
        # The failed unit is driven by its injected profile and is expected here.
        print(f"  still past the 900s window: {', '.join(stale)}", flush=True)
    return 0


async def run_incident_tick(args: argparse.Namespace) -> int:
    """A full agent-fleet rescue, published as signed evidence, under a spend cap."""
    settings = get_settings()
    namespace = args.namespace or settings.namespace
    runtime = build_runtime(namespace=namespace)

    allowed, reason = _check_and_claim_budget(runtime.repo, args.max_per_day, args.max_total)
    print(f"spend guard: {reason}", flush=True)
    if not allowed:
        # Exit 0. A refused run is the guard working, and a non-zero exit would make
        # Cloud Scheduler retry the thing the cap just declined.
        return 0

    # A scheduled run picks its seed from the clock so successive days are different
    # rescues rather than the same one replayed, and so the seed is still reproducible
    # from the manifest's own timestamp.
    seed = int(datetime.now(UTC).strftime("%Y%m%d%H"))

    from scripts.seed_demo import publish_run

    return await publish_run(namespace=namespace, seed=seed, rounds=args.rounds, driver="agent")


def main() -> int:
    args = parse_args()
    if args.mode == "telemetry":
        return run_telemetry_tick(args.namespace)
    return asyncio.run(run_incident_tick(args))


if __name__ == "__main__":
    raise SystemExit(main())
