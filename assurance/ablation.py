"""Run the drill corpus with the Safety Kernel removed, and compare.

Every published run so far has the kernel in the loop, so the counts show that
violations did not occur. They do not show that the kernel is what prevented them. That
is the difference between proving a system correct and proving a mechanism responsible,
and only the second one answers "why is this architecture better than the obvious one".

Two arms, same corpus, same seeds, same everything else:

``control``
    unmodified.

``kernel``
    ``services.common.effects.evaluate_action`` is rebound to a function that allows
    every action. ``effects.py`` imports the symbol at module scope, so this removes
    exactly step 5 of the seven-step commit sequence and duplicates no logic. The
    transaction, the receipt lookup, the authorization check and the write all still
    happen, which is the point: what is measured is the kernel's contribution, not the
    contribution of everything at once.

The honest reading is in ``evidence/methodology.md``. N1, N2 and N3 hold in both arms,
because authorization and the transactional commit are separate mechanisms from the
preconditions. That is what defence in depth means, and it is reported as a null rather
than dressed up.

Guarded to the in-memory store. This must never run against Firestore or a deployment.

    uv run python -m assurance.ablation --seeds 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.safety_kernel import ActionRequest, Decision, KernelState
from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.decision import Verdict

CORPUS_VERSION = "1.0.0"
BASE_SEED = 20260826
ARMS = ("control", "kernel")


def _allow_everything(
    state: KernelState,
    request: ActionRequest,
    *,
    config: KernelConfig = DEFAULT_CONFIG,
) -> Decision:
    """The ablated kernel. Signature matches evaluate_action; every precondition passes."""
    return Decision(
        verdict=Verdict.ALLOW,
        reason="ABLATED: kernel preconditions bypassed",
    )


def _guard() -> None:
    settings = get_settings()
    backend = getattr(settings, "store_backend", None) or getattr(settings, "store", "")
    env = getattr(settings, "deployment_env", "")
    if str(backend) != "memory" or env == "cloud-run":
        raise SystemExit(
            f"refusing to run an ablation against store={backend!r} env={env!r}. "
            "This disables the safety kernel and must only touch the in-memory store."
        )


async def _run_arm(arm: str, seeds: list[int]) -> Any:
    import services.common.effects as effects
    from assurance import campaign as campaign_mod

    original = effects.evaluate_action
    if arm == "kernel":
        effects.evaluate_action = _allow_everything
    try:
        return await campaign_mod.run_campaign(seeds=seeds, drivers=("scripted",))
    finally:
        effects.evaluate_action = original


def _summarise(campaign: Any) -> dict[str, Any]:
    rows = campaign.rows
    failed_invariants: dict[str, int] = {}
    for row in rows:
        for name in row.failed_invariants:
            failed_invariants[name] = failed_invariants.get(name, 0) + 1
    return {
        "total_runs": len(rows),
        "passed": sum(1 for r in rows if r.passed),
        "failed": sum(1 for r in rows if not r.passed),
        "failed_invariants": dict(sorted(failed_invariants.items())),
        "failing_drills": sorted({r.drill_id for r in rows if not r.passed}),
        # Every run, not just the summary. A comparison whose rows cannot be inspected is
        # a claim rather than a measurement.
        "runs": [
            {
                "drill_id": r.drill_id,
                "family": r.family,
                "seed": r.seed,
                "driver": r.driver,
                "passed": r.passed,
                "final_state": r.final_state,
                "failed_invariants": list(r.failed_invariants),
                "unmet_expectations": list(r.unmet_expectations),
            }
            for r in rows
        ],
    }


async def main_async(seed_count: int) -> dict[str, Any]:
    _guard()
    seeds = [BASE_SEED + i * 101 for i in range(seed_count)]
    settings = get_settings()
    results: dict[str, Any] = {
        "provenance": {
            "command": f"uv run python -m assurance.ablation --seeds {seed_count}",
            "generated_at": now_iso(),
            "source_commit": settings.source_commit,
            "corpus_version": CORPUS_VERSION,
            "seeds": seeds,
            "base_seed": BASE_SEED,
            "drivers": ["scripted"],
            "store_backend": settings.store_backend,
            "model_calls": 0,
            "ablation_target": "services.common.effects.evaluate_action",
            "note": (
                "The kernel arm rebinds one imported symbol and duplicates no logic. "
                "The transaction, receipt lookup, authorization check and write all "
                "still run, so what is measured is the kernel's contribution alone."
            ),
        },
        "seeds": seeds,
        "arms": {},
    }

    for arm in ARMS:
        print(f"\n=== arm: {arm} ===", flush=True)
        campaign = await _run_arm(arm, seeds)
        summary = _summarise(campaign)
        results["arms"][arm] = summary
        print(
            f"  {summary['passed']}/{summary['total_runs']} passed"
            f"  failed_invariants={summary['failed_invariants']}",
            flush=True,
        )

    c, k = results["arms"]["control"], results["arms"]["kernel"]
    print("\n--- comparison -------------------------------------------------")
    print(f"  with the kernel     {c['passed']}/{c['total_runs']} passed")
    print(f"  kernel removed      {k['passed']}/{k['total_runs']} passed")
    print(f"  violations unmasked {k['failed_invariants']}")
    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seeds", type=int, default=6)
    p.add_argument("--out", type=Path, default=Path("evidence/ablation"))
    args = p.parse_args()
    results = asyncio.run(main_async(args.seeds))
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "ablation.json"
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
