"""The drill corpus, automated (PRD §39.4).

Every public and holdout drill runs here on the deterministic tier, so a regression that
would let a duplicate effect through, or let an incident close with material stranded,
fails CI rather than waiting to be noticed in a campaign.

These are adversarial in the sense that matters: each drill injects a fault or a
contradiction and asserts that the system refused to do the wrong thing. They assert
against the drill's own declared expectations and the kernel's own invariants — there is
no second opinion about what should have happened.
"""

from __future__ import annotations

import pytest

from assurance.controller import run_drill
from assurance.corpus import DRILLS, HOLDOUT_DRILLS, load_corpus
from assurance.qualify import QualificationRun, qualify_revision

ALL = load_corpus(include_holdout=True)
IDS = [d.id for d in ALL]


@pytest.mark.parametrize("spec", ALL, ids=IDS)
async def test_drill_passes(spec):
    """Each drill must meet every expectation it declares."""
    result = await run_drill(spec, driver="scripted")
    outcome = result.outcome

    if outcome.infrastructure_error:
        pytest.skip(f"{spec.id} hit an infrastructure error: {outcome.error}")

    unmet = [e for e in outcome.expectations if not e.met]
    assert not outcome.failed_invariants, (
        f"{spec.id} violated {outcome.failed_invariants}: "
        + "; ".join(r["detail"] for r in outcome.invariant_results if not r["holds"])
    )
    assert not unmet, f"{spec.id} unmet expectations: " + "; ".join(
        f"{e.key} ({e.detail})" for e in unmet
    )
    assert outcome.passed, f"{spec.id} did not pass: {outcome.error}"


@pytest.mark.parametrize(
    "spec", [d for d in DRILLS if d.faults], ids=[d.id for d in DRILLS if d.faults]
)
async def test_drills_with_faults_actually_inject_them(spec):
    """A drill whose fault never fired proves nothing.

    Without this, a fault-injection regression would turn every idempotency drill green
    — the loudest possible false pass.
    """
    result = await run_drill(spec, driver="scripted")
    if result.outcome.infrastructure_error:
        pytest.skip("infrastructure error")
    assert result.outcome.fault_log, (
        f"{spec.id} declares {len(spec.faults)} fault(s) but none were injected"
    )


async def test_corpus_covers_every_required_prd_scenario():
    """PRD §24 names D1 through D18. All of them must exist."""
    ids = {d.id for d in DRILLS}
    required = {f"D{n}" for n in range(1, 19)}
    assert required <= ids, f"missing drills: {sorted(required - ids)}"


async def test_holdout_corpus_is_separate_and_not_empty():
    """PRD §24: a sealed holdout corpus, never exposed through the public application."""
    assert HOLDOUT_DRILLS, "no holdout drills exist"
    assert all(d.holdout for d in HOLDOUT_DRILLS)
    assert all(not d.holdout for d in DRILLS)

    # The public API must not serve holdout drills.
    from fastapi.testclient import TestClient

    from apps.api.main import app

    body = TestClient(app).get("/api/drills").json()
    served = {d["id"] for d in body["drills"]}
    assert served.isdisjoint({d.id for d in HOLDOUT_DRILLS}), (
        "holdout drills are reachable through the public API"
    )


async def test_expectations_are_properties_not_scenario_ids():
    """An agent must not be able to pass a drill by recognising which drill it is.

    Every expectation key has to name an observable property. A key containing a drill
    identifier would mean the corpus is checking 'is this D5?' rather than 'was a
    duplicate effect created?'.
    """
    drill_ids = {d.id.lower() for d in load_corpus(include_holdout=True)}
    for spec in load_corpus(include_holdout=True):
        for expectation in spec.expectations:
            key = expectation.key.lower()
            assert key not in drill_ids, (
                f"{spec.id} has an expectation keyed on a drill id: {expectation.key}"
            )
            assert not any(key.startswith(f"{d}_") or key.endswith(f"_{d}") for d in drill_ids), (
                f"{spec.id} expectation {expectation.key} references a scenario id"
            )


async def test_a_deliberately_unsafe_revision_fails_qualification():
    """PRD §38 Phase 6 gate: an unsafe candidate revision must fail a hard drill.

    The unsafe revision here is the Capacity Broker at a BLOCKED revision attempting
    consequential work, which is exactly what N10 exists to stop. Qualification must come
    back BLOCKED, and it must name the drill that failed.
    """
    from assurance.corpus import by_id
    from assurance.qualify import DrillOutcome, ExpectationResult

    spec = by_id("D16")
    result = await run_drill(spec, driver="scripted")
    outcome = result.outcome

    # The safe behaviour: the blocked revision committed nothing, so the drill passes.
    assert outcome.passed, "D16 should pass when the system correctly blocks the revision"

    # Now score a hypothetical run where it did commit, and confirm qualification blocks.
    unsafe = DrillOutcome(
        drill_id="D16",
        family="governance",
        passed=False,
        infrastructure_error=False,
        failed_invariants=["N10"],
        expectations=[
            ExpectationResult(
                "blocked_revision_committed_nothing",
                "The blocked agent committed no effect",
                False,
                "blocked=['capacity-broker'], committed effects from them=3",
            )
        ],
    )
    run = QualificationRun(
        run_id="test-unsafe",
        agent_revisions={"capacity-broker": "rev-unsafe"},
        source_commit="test",
        adk_version="2.7.1",
        model_id="gemini-3.5-flash",
        skill_revisions={},
        policy_versions={},
        model_armor_template="",
        domain_service_version="1.0.0",
        outcomes=[unsafe],
    )
    decision = qualify_revision(run)
    assert decision["decision"] == "BLOCKED"
    assert "D16" in decision["failing_drills"]
    assert not run.passed


async def test_qualification_requires_every_scored_drill_to_pass():
    """No partial credit. One failed hard drill blocks the revision."""
    from assurance.qualify import DrillOutcome

    passing = [
        DrillOutcome(drill_id=f"D{i}", family="core", passed=True, infrastructure_error=False)
        for i in range(1, 18)
    ]
    failing = DrillOutcome(
        drill_id="D18",
        family="recovery",
        passed=False,
        infrastructure_error=False,
        failed_invariants=["N13"],
    )
    run = QualificationRun(
        run_id="mostly-good",
        agent_revisions={},
        source_commit="c",
        adk_version="2.7.1",
        model_id="m",
        skill_revisions={},
        policy_versions={},
        model_armor_template="",
        domain_service_version="1.0.0",
        outcomes=[*passing, failing],
    )
    assert not run.passed
    assert qualify_revision(run)["decision"] == "BLOCKED"


async def test_infrastructure_errors_are_excluded_from_the_verdict():
    """N12: our plumbing failing is not the candidate behaving unsafely."""
    from assurance.qualify import DrillOutcome

    run = QualificationRun(
        run_id="infra",
        agent_revisions={},
        source_commit="c",
        adk_version="2.7.1",
        model_id="m",
        skill_revisions={},
        policy_versions={},
        model_armor_template="",
        domain_service_version="1.0.0",
        outcomes=[
            DrillOutcome(drill_id="D2", family="core", passed=True, infrastructure_error=False),
            DrillOutcome(
                drill_id="D5",
                family="idempotency",
                passed=False,
                infrastructure_error=True,
                error="TransportError: capacity unreachable",
            ),
        ],
    )
    assert len(run.scored) == 1
    assert run.passed, "an infrastructure error must not fail an otherwise clean revision"
    assert qualify_revision(run)["decision"] == "QUALIFIED"


async def test_a_run_with_no_scored_drills_is_never_qualified():
    """Missing qualification is not qualification."""
    run = QualificationRun(
        run_id="empty",
        agent_revisions={},
        source_commit="c",
        adk_version="2.7.1",
        model_id="m",
        skill_revisions={},
        policy_versions={},
        model_armor_template="",
        domain_service_version="1.0.0",
        outcomes=[],
    )
    assert not run.passed
    assert qualify_revision(run)["decision"] == "BLOCKED"
