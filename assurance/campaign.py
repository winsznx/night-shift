"""The measurement campaign (PRD §33).

Runs the drill corpus across many seeds and writes raw results. Nothing here decides
what a good number is: it records what happened, including failures and refusals, and
the headline metrics are derived from the raw rows afterwards rather than typed by hand.

Two tiers are reported and never pooled:

* **scripted** — the deterministic driver. Wide: every drill across many seeds.
* **agent** — the live Gemini fleet. Narrow and slow, so a smaller disclosed sample.

Mixing them into one percentage would let the cheap tier's volume flatter the expensive
tier's behaviour, which is precisely the kind of number this project exists to avoid.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from assurance.controller import run_drill
from assurance.corpus import CORPUS_VERSION, DrillSpec, load_corpus
from assurance.qualify import DrillOutcome
from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.common.skills import skill_refs

log = logging.getLogger(__name__)


@dataclass
class CampaignRow:
    run_index: int
    drill_id: str
    family: str
    seed: int
    driver: str
    passed: bool
    infrastructure_error: bool
    final_state: str
    failed_invariants: list[str]
    unmet_expectations: list[str]
    faults_injected: int
    tool_calls: int
    tool_denials: int
    duplicate_receipts: int
    model_calls: int
    wall_clock_s: float
    committed: int
    quarantined: int
    unresolved: int
    in_flight: int
    total_containers: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "failed_invariants": ";".join(self.failed_invariants),
            "unmet_expectations": ";".join(self.unmet_expectations),
        }

    def as_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _row(index: int, spec: DrillSpec, seed: int, driver: str, outcome: DrillOutcome) -> CampaignRow:
    recon = outcome.reconciliation or {}
    return CampaignRow(
        run_index=index,
        drill_id=outcome.drill_id,
        family=outcome.family,
        seed=seed,
        driver=driver,
        passed=outcome.passed,
        infrastructure_error=outcome.infrastructure_error,
        final_state=outcome.final_state,
        failed_invariants=list(outcome.failed_invariants),
        unmet_expectations=[e.key for e in outcome.expectations if not e.met],
        faults_injected=len(outcome.fault_log),
        tool_calls=outcome.tool_calls,
        tool_denials=outcome.tool_denials,
        duplicate_receipts=outcome.duplicate_receipts,
        model_calls=outcome.model_calls,
        wall_clock_s=outcome.wall_clock_s,
        committed=len(recon.get("committed", [])),
        quarantined=len(recon.get("quarantined", [])),
        unresolved=len(recon.get("unresolved", [])),
        in_flight=len(recon.get("in_flight", [])),
        total_containers=int(recon.get("total", 0)),
        error=outcome.error,
    )


@dataclass
class Campaign:
    rows: list[CampaignRow] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    seeds: list[int] = field(default_factory=list)
    include_holdout: bool = True

    def add(self, row: CampaignRow) -> None:
        self.rows.append(row)

    def metrics(self) -> dict[str, Any]:
        """Derive the headline numbers from the raw rows. Never pre-written."""
        return derive_metrics(self.rows)


async def run_campaign(
    *,
    seeds: list[int],
    drivers: tuple[str, ...] = ("scripted",),
    include_holdout: bool = True,
    model: str | None = None,
    drill_ids: list[str] | None = None,
    progress: Any = None,
) -> Campaign:
    corpus = load_corpus(include_holdout=include_holdout)
    if drill_ids:
        wanted = set(drill_ids)
        corpus = [d for d in corpus if d.id in wanted]

    campaign = Campaign(started_at=now_iso(), seeds=list(seeds), include_holdout=include_holdout)
    index = 0
    for driver in drivers:
        for seed in seeds:
            for spec in corpus:
                index += 1
                try:
                    result = await run_drill(spec, seed=seed, driver=driver, model=model)
                    outcome = result.outcome
                except Exception as exc:
                    # A harness failure is recorded as an infrastructure error, never
                    # dropped and never counted as a passing run.
                    log.warning("campaign run %s (%s/%s) raised: %s", index, spec.id, seed, exc)
                    outcome = DrillOutcome(
                        drill_id=spec.id,
                        family=spec.family,
                        passed=False,
                        infrastructure_error=True,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                row = _row(index, spec, seed, driver, outcome)
                campaign.add(row)
                if progress is not None:
                    progress(row)
    campaign.finished_at = now_iso()
    return campaign


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def derive_metrics(rows: list[CampaignRow]) -> dict[str, Any]:
    """Compute every published number from the raw rows.

    Each metric names exactly what it counts. Where a count is zero, that is reported
    as an observed zero over a stated denominator, not as an absolute guarantee.
    """
    by_driver: dict[str, list[CampaignRow]] = {}
    for row in rows:
        by_driver.setdefault(row.driver, []).append(row)

    out: dict[str, Any] = {
        "generated_at": now_iso(),
        "corpus_version": CORPUS_VERSION,
        "total_runs": len(rows),
        "by_driver": {},
    }

    for driver, driver_rows in sorted(by_driver.items()):
        scored = [r for r in driver_rows if not r.infrastructure_error]
        infra = [r for r in driver_rows if r.infrastructure_error]
        passed = [r for r in scored if r.passed]

        invariant_failures: dict[str, int] = {}
        for row in scored:
            for name in row.failed_invariants:
                invariant_failures[name] = invariant_failures.get(name, 0) + 1

        fault_runs = [r for r in scored if r.faults_injected > 0]
        reconciled = [
            r for r in scored if r.total_containers > 0 and r.unresolved == 0 and r.in_flight == 0
        ]
        closed = [r for r in scored if r.final_state == "CLOSED"]
        refusal_runs = [r for r in scored if r.tool_denials > 0]

        durations = sorted(r.wall_clock_s for r in scored)

        out["by_driver"][driver] = {
            "runs": len(driver_rows),
            "scored_runs": len(scored),
            "infrastructure_errors": len(infra),
            "passed": len(passed),
            "failed": len(scored) - len(passed),
            "pass_rate": round(len(passed) / len(scored), 4) if scored else None,
            "capacity_overbooking_violations": invariant_failures.get("N1", 0),
            "duplicate_effect_violations": invariant_failures.get("N2", 0),
            "invalid_custody_violations": invariant_failures.get("N3", 0),
            "stale_evidence_violations": invariant_failures.get("N4", 0),
            "incomplete_reconciliation_violations": invariant_failures.get("N5", 0),
            "premature_close_violations": invariant_failures.get("N6", 0),
            "authority_violations": invariant_failures.get("N7", 0),
            "memory_authority_violations": invariant_failures.get("N8", 0),
            "unqualified_revision_violations": invariant_failures.get("N10", 0),
            "all_invariant_failures": dict(sorted(invariant_failures.items())),
            "runs_with_injected_faults": len(fault_runs),
            "faults_injected_total": sum(r.faults_injected for r in scored),
            "runs_with_duplicate_effect_after_fault": sum(
                1 for r in fault_runs if "N2" in r.failed_invariants
            ),
            "runs_fully_reconciled": len(reconciled),
            "runs_closed": len(closed),
            "runs_with_authorization_denials": len(refusal_runs),
            "authorization_denials_total": sum(r.tool_denials for r in scored),
            "duplicate_receipts_returned": sum(r.duplicate_receipts for r in scored),
            "containers_committed_total": sum(r.committed for r in scored),
            "containers_unresolved_total": sum(r.unresolved for r in scored),
            "model_calls_total": sum(r.model_calls for r in scored),
            "wall_clock_median_s": _percentile(durations, 50),
            "wall_clock_p95_s": _percentile(durations, 95),
            "per_drill": _per_drill(scored),
        }
    return out


def _per_drill(rows: list[CampaignRow]) -> dict[str, Any]:
    grouped: dict[str, list[CampaignRow]] = {}
    for row in rows:
        grouped.setdefault(row.drill_id, []).append(row)
    return {
        drill_id: {
            "runs": len(group),
            "passed": sum(1 for r in group if r.passed),
            "failed": sum(1 for r in group if not r.passed),
            "unmet_expectations": sorted({key for r in group for key in r.unmet_expectations}),
            "failed_invariants": sorted({n for r in group for n in r.failed_invariants}),
        }
        for drill_id, group in sorted(grouped.items())
    }


def _percentile(sorted_values: list[float], pct: int) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    index = min(len(sorted_values) - 1, round((pct / 100) * (len(sorted_values) - 1)))
    return round(sorted_values[index], 3)


# --------------------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------------------


def write_results(campaign: Campaign, out_dir: Path, *, command: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    from google.adk.version import __version__ as adk_version

    metrics = campaign.metrics()
    provenance = {
        "command": command,
        "generated_at": now_iso(),
        "started_at": campaign.started_at,
        "finished_at": campaign.finished_at,
        "corpus_version": CORPUS_VERSION,
        "seeds": campaign.seeds,
        "include_holdout": campaign.include_holdout,
        "model_id": settings.model_id,
        "model_location": settings.model_location,
        "adk_version": adk_version,
        "source_commit": settings.source_commit,
        "skill_revisions": skill_refs(),
        "deployment_env": settings.deployment_env,
    }

    results = {
        "provenance": provenance,
        "metrics": metrics,
        "runs": [r.as_json() for r in campaign.rows],
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    if campaign.rows:
        with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(campaign.rows[0].as_dict().keys()))
            writer.writeheader()
            for row in campaign.rows:
                writer.writerow(row.as_dict())

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return results


def main() -> int:  # pragma: no cover - CLI
    import argparse

    parser = argparse.ArgumentParser(description="Run the Night Shift measurement campaign.")
    parser.add_argument("--seeds", type=int, default=6, help="number of seeds")
    parser.add_argument("--base-seed", type=int, default=20260826)
    parser.add_argument("--drivers", default="scripted", help="comma-separated: scripted,agent")
    parser.add_argument("--drills", default="", help="comma-separated drill ids")
    parser.add_argument("--no-holdout", action="store_true")
    parser.add_argument("--out", default="evidence/campaign")
    args = parser.parse_args()

    seeds = [args.base_seed + i * 101 for i in range(args.seeds)]
    drivers = tuple(d.strip() for d in args.drivers.split(",") if d.strip())
    drill_ids = [d.strip() for d in args.drills.split(",") if d.strip()] or None

    def progress(row: CampaignRow) -> None:
        status = "INFRA" if row.infrastructure_error else ("pass" if row.passed else "FAIL")
        # flush: a long campaign is watched through a log file, and buffered progress
        # is indistinguishable from a hung run.
        print(
            f"  [{row.run_index:>4}] {row.driver:<9} {row.drill_id:<4} seed={row.seed} "
            f"{status:<5} {row.final_state}",
            flush=True,
        )

    campaign = asyncio.run(
        run_campaign(
            seeds=seeds,
            drivers=drivers,
            include_holdout=not args.no_holdout,
            drill_ids=drill_ids,
            progress=progress,
        )
    )
    command = (
        f"uv run python -m assurance.campaign --seeds {args.seeds} "
        f"--base-seed {args.base_seed} --drivers {args.drivers}"
        + (" --no-holdout" if args.no_holdout else "")
    )
    results = write_results(campaign, Path(args.out), command=command)
    metrics = results["metrics"]
    print()
    print(f"total runs: {metrics['total_runs']}")
    for driver, block in metrics["by_driver"].items():
        print(
            f"  {driver}: {block['passed']}/{block['scored_runs']} passed, "
            f"{block['infrastructure_errors']} infrastructure error(s), "
            f"N1 violations={block['capacity_overbooking_violations']}, "
            f"N2 violations={block['duplicate_effect_violations']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
