"""Refuse to deploy an unqualified revision (PRD §23.5 traffic gate).

Managed Agent Runtime revision traffic splitting is not delivered on this project, so
the PRD's documented fallback applies: qualification state is authoritative, and
**deployment code must refuse unqualified revisions**. This is that refusal.

It runs the drill corpus against the working tree, scores it with the deterministic
qualification engine, and exits non-zero unless every scored drill passes. The deploy
script calls it before it builds anything, so an unqualified revision never reaches
Cloud Run at all.

    uv run python scripts/check_qualification.py [--fast] [--record]

``--fast`` runs one seed instead of three. ``--record`` writes the qualification to
Firestore so the running system's N10 check sees the same verdict the gate did.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assurance.controller import run_drill
from assurance.corpus import CORPUS_VERSION, load_corpus
from assurance.qualify import QualificationRun, qualify_revision
from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.common.skills import skill_refs
from nightshift.schemas.enums import AgentName

ROOT = Path(__file__).resolve().parents[1]


def source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualification gate. Exits non-zero if this revision is not qualified."
    )
    parser.add_argument("--fast", action="store_true", help="one seed instead of three")
    parser.add_argument(
        "--record", action="store_true", help="write the verdict to the configured store"
    )
    parser.add_argument("--revision", default="", help="revision id (defaults to the commit)")
    parser.add_argument("--out", default="evidence/qualification.json")
    args = parser.parse_args()

    settings = get_settings()
    revision = args.revision or source_commit()
    seeds = [20260826] if args.fast else [20260826, 20260927, 20261028]
    corpus = load_corpus(include_holdout=True)

    from google.adk.version import __version__ as adk_version

    print(
        f"Qualification gate: revision {revision}, {len(corpus)} drills x {len(seeds)} seed(s)",
        flush=True,
    )

    outcomes = []
    for seed in seeds:
        for spec in corpus:
            result = await run_drill(spec, seed=seed, driver="scripted")
            outcome = result.outcome
            outcomes.append(outcome)
            mark = (
                "INFRA" if outcome.infrastructure_error else ("pass" if outcome.passed else "FAIL")
            )
            print(f"  {spec.id:<4} seed={seed} {mark}", flush=True)
            if not outcome.passed and not outcome.infrastructure_error:
                for expectation in outcome.expectations:
                    if not expectation.met:
                        print(f"        unmet {expectation.key}: {expectation.detail}", flush=True)

    run = QualificationRun(
        run_id=f"qual-{revision}-{now_iso()}",
        agent_revisions={a.value: revision for a in AgentName},
        source_commit=revision,
        adk_version=adk_version,
        model_id=settings.model_id,
        skill_revisions=skill_refs(),
        policy_versions={"semantic_governance": "local-dry-run-1.0.0"},
        model_armor_template=settings.model_armor_template,
        domain_service_version="1.0.0",
        corpus_version=CORPUS_VERSION,
        seeds=seeds,
        outcomes=outcomes,
        started_at=now_iso(),
        finished_at=now_iso(),
    )
    decision = qualify_revision(run)

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({**run.as_dict(), "decision": decision}, indent=2), encoding="utf-8"
    )

    print()
    totals = run.as_dict()["totals"]
    print(
        f"  scored {totals['scored']}  passed {totals['passed']}  failed {totals['failed']}  "
        f"infrastructure errors {totals['infrastructure_errors']}"
    )
    print(f"  decision: {decision['decision']} — {decision['reason']}")
    print(f"  written to {out_path.relative_to(ROOT)}")

    if args.record:
        _record(revision, decision["decision"], run.run_id)

    if decision["decision"] != "QUALIFIED":
        print()
        print("DEPLOY REFUSED: this revision is not qualified for operational traffic.")
        return 1
    return 0


def _record(revision: str, state: str, run_id: str) -> None:
    """Write the verdict where the running system's N10 check will read it."""
    from services.common.repository import Repository

    settings = get_settings()
    repo = Repository.create(
        settings.store_backend,
        project=settings.project_id,
        database=settings.firestore_database,
        namespace=settings.namespace,
    )
    for agent in AgentName:
        repo.store.set(
            "agentRevisions",
            f"{agent.value}@{revision}",
            {
                "agent": agent.value,
                "revision_id": revision,
                "state": "ACTIVE" if state == "QUALIFIED" else state,
                "qualified_at": now_iso(),
                "qualification_run_id": run_id,
            },
        )
    print(f"  recorded {len(list(AgentName))} revision states in {repo.store.backend}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
