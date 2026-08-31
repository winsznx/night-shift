"""Measure what the orchestrator does when a worker agent fails without deciding anything.

The Multi-Agent Nexus criterion asks how the system recovers if a worker agent loops or
returns a hallucination. This answers it with a run rather than a paragraph.

Three failures are injected into a real ``IncidentOrchestrator`` against the real
repository and the real event writer. Only the model call itself is replaced, so the
recorded timeline is the same timeline a live incident produces.

    uv run python scripts/measure_agent_recovery.py

No credentials, no model, no network. Deterministic, so the published artifact is
reproducible from a fresh clone.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.orchestrator import IncidentOrchestrator, SpecialistResult
from fixtures.estate import build_estate, seed_repository
from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings
from nightshift.common.store import MemoryStore
from nightshift.schemas.enums import AgentName
from services.common.repository import Repository
from services.gateway.broker import ToolBroker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _orchestrator() -> IncidentOrchestrator:
    repo = Repository(MemoryStore(), namespace="recovery-measure")
    seed_repository(repo, build_estate())
    incident_id = "INC-RECOVERY-PROBE"
    return IncidentOrchestrator(
        repo,
        ToolBroker(repo, incident_id),
        incident_id,
        model=get_settings().model_id,
    )


async def _scenario(
    name: str,
    description: str,
    responses: list[Any],
) -> dict[str, Any]:
    """Drive one agent through a scripted sequence of model outcomes.

    ``responses`` entries are either an exception to raise from the transport, or a dict
    to return as validated output, or ``None`` to return unparseable prose.
    """
    orch = _orchestrator()
    calls = {"n": 0}

    async def scripted(agent: AgentName, message: str) -> SpecialistResult:
        index = min(calls["n"], len(responses) - 1)
        outcome = responses[index]
        calls["n"] += 1
        if isinstance(outcome, SpecialistResult):
            return outcome
        if isinstance(outcome, BaseException):
            # Reproduce what _invoke_once returns once its backoff is exhausted, so the
            # measurement exercises the real classification rather than a stand-in.
            return SpecialistResult(
                agent=agent,
                ok=False,
                output=None,
                raw_text="",
                error=f"{type(outcome).__name__}: {outcome}",
            )
        if outcome is None:
            return SpecialistResult(
                agent=agent,
                ok=False,
                output=None,
                raw_text="Certainly. Here is my assessment, written out in prose.",
                error="no JSON object found in the final message",
            )
        return SpecialistResult(agent=agent, ok=True, output=outcome, raw_text="{}", error=None)

    orch._invoke_once = scripted  # type: ignore[method-assign]
    result = await orch._invoke(AgentName.COMMANDER, "assess the incident")

    events = [
        {"kind": e.kind, "source": e.source, "summary": e.summary, "detail": e.detail}
        for e in orch.repo.list_events(orch.incident_id)
    ]
    return {
        "scenario": name,
        "description": description,
        "model_outcomes_scripted": len(responses),
        "invocations_made": calls["n"],
        "recovered": result.ok,
        "final_error": result.error,
        "timeline_events": events,
        "recovery_events": [e for e in events if e["kind"] == "agent_recovery"],
    }


def _write(path: str, text: str) -> None:
    """Blocking write, kept out of the coroutine so the async lint rule stays meaningful."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


async def main() -> int:
    from agents.orchestrator import _transient_class

    scenarios = [
        await _scenario(
            "hallucination-recovered",
            "The agent answers in prose where a JSON object was required. It is re-asked "
            "once with the parser's own error attached and returns valid output.",
            [None, {"assessment": "freezer F-17 is failing", "next_steps": []}],
        ),
        await _scenario(
            "hallucination-persistent",
            "The agent never returns parseable output. The repair budget is one, so it "
            "stops after two attempts instead of looping.",
            [None, None, None, None],
        ),
        await _scenario(
            "authorization-denied-not-retried",
            "The agent reached for a tool it does not hold. A denial is a decision by the "
            "authority layer, so it is recorded and never re-asked.",
            [
                SpecialistResult(
                    agent=AgentName.DISPATCH_AGENT,
                    ok=False,
                    output=None,
                    raw_text="",
                    error="tool authorization denied: dispatch may not read inventory",
                )
            ],
        ),
    ]

    # Classification is the half that decides whether a failure is retried at all, so it
    # is published next to the runs rather than left implicit in them.
    classification = {
        message: _transient_class(RuntimeError(message))
        for message in (
            "429 Too Many Requests",
            "RESOURCE_EXHAUSTED: quota exceeded",
            "ServerError: 503 Service Unavailable",
            "ServerError: 500 internal error encountered",
            "504 Deadline Exceeded",
            "connection reset by peer",
            "tool authorization denied: not permitted",
            "schema validation failed: 2 error(s)",
        )
    }

    document = {
        "generated_at": now_iso(),
        "source_commit": get_settings().source_commit,
        "note": (
            "Recovery from a worker that failed without deciding anything. Only the model "
            "call is replaced; the orchestrator, the repository and the event writer are "
            "the ones a live incident uses, so these timeline entries are the entries a "
            "live incident produces. Retry used to match HTTP 429 only, so a routine "
            "Vertex 503 on the Commander produced no plan, and the run loop breaks on "
            "that. One busy data centre aborted a 42-container rescue."
        ),
        "backoff": {
            "quota_s": list(IncidentOrchestrator._QUOTA_BACKOFF_S),
            "transport_s": list(IncidentOrchestrator._TRANSPORT_BACKOFF_S),
            "max_repair_attempts": IncidentOrchestrator._MAX_REPAIR_ATTEMPTS,
        },
        "failure_classification": classification,
        "scenarios": scenarios,
    }

    out = os.path.join(ROOT, "evidence", "agent-recovery.json")
    _write(out, json.dumps(document, indent=2) + "\n")

    print(f"Measured {len(scenarios)} recovery scenarios\n")
    for row in scenarios:
        print(
            f"  {row['scenario']:<36} invocations={row['invocations_made']} "
            f"recovered={row['recovered']}"
        )
        for event in row["recovery_events"]:
            print(f"      timeline: {event['summary']}")
    print("\nFailure classification:")
    for message, verdict in classification.items():
        print(f"  {verdict or 'agent decision'!s:<14} {message}")
    print("\nWritten to evidence/agent-recovery.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
