"""Inter-agent routing has to survive a worker that fails without deciding anything.

Two failures are not agent decisions and must not be treated as one:

* the model endpoint is unreachable or unwell, and
* the agent returns text the output schema rejects.

Before this, only HTTP 429 was retried, so a routine Vertex 503 on the Commander made
``_commander_step`` return ``None``, which breaks the whole run loop. One busy data
centre aborted a 42-container rescue. Malformed output had no recovery at all.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.orchestrator import (
    IncidentOrchestrator,
    SpecialistResult,
    _repair_prompt,
    _transient_class,
)
from fixtures.estate import build_estate, seed_repository
from nightshift.common.store import MemoryStore
from nightshift.schemas.enums import AgentName
from services.common.repository import Repository
from services.gateway.broker import ToolBroker


class TestTransientClassification:
    @pytest.mark.parametrize(
        "message",
        [
            "429 Too Many Requests",
            "RESOURCE_EXHAUSTED: quota exceeded for model",
            "rate limit reached, retry later",
        ],
    )
    def test_quota_failures_are_classified_as_quota(self, message: str) -> None:
        assert _transient_class(RuntimeError(message)) == "quota"

    @pytest.mark.parametrize(
        "message",
        [
            "503 Service Unavailable",
            "ServerError: 500 internal error encountered",
            "504 Deadline Exceeded",
            "connection reset by peer",
            "Server disconnected without sending a response",
        ],
    )
    def test_transport_failures_are_classified_as_transport(self, message: str) -> None:
        """The class that used to end the whole rescue on its first occurrence."""
        assert _transient_class(RuntimeError(message)) == "transport"

    @pytest.mark.parametrize(
        "message",
        [
            "tool authorization denied: dispatch agent may not read inventory",
            "schema validation failed: 2 error(s)",
            "no JSON object found in the final message",
        ],
    )
    def test_agent_outcomes_are_not_transient(self, message: str) -> None:
        """A refusal or a bad answer is a decision. Retrying it would be asking the
        authority layer to change its mind."""
        assert _transient_class(RuntimeError(message)) is None


class TestRepairPrompt:
    def _failed(self, error: str) -> SpecialistResult:
        return SpecialistResult(
            agent=AgentName.SIGNAL_INVESTIGATOR, ok=False, output=None, raw_text="", error=error
        )

    def test_malformed_output_earns_one_corrective_reask(self) -> None:
        prompt = _repair_prompt("original objective", self._failed("schema validation failed: 1"))

        assert prompt is not None
        assert "original objective" in prompt
        assert "schema validation failed: 1" in prompt

    def test_prose_where_json_was_required_earns_a_reask(self) -> None:
        assert _repair_prompt("obj", self._failed("no JSON object found in the final")) is not None

    def test_a_broker_denial_is_never_reasked(self) -> None:
        denial = self._failed("tool authorization denied: not permitted")

        assert _repair_prompt("obj", denial) is None

    def test_a_transport_failure_is_never_reasked_here(self) -> None:
        """``_invoke_once`` has already exhausted its backoff by this point."""
        assert _repair_prompt("obj", self._failed("ServerError: 503")) is None

    def test_a_successful_result_is_never_reasked(self) -> None:
        ok = SpecialistResult(
            agent=AgentName.COMMANDER, ok=True, output={"a": 1}, raw_text="{}", error=None
        )

        assert _repair_prompt("obj", ok) is None


@pytest.fixture
def orchestrator() -> IncidentOrchestrator:
    store = MemoryStore()
    repo = Repository(store, namespace="test")
    seed_repository(repo, build_estate())
    incident = repo.list_incidents()[0] if repo.list_incidents() else None
    incident_id = incident.id if incident else "INC-TEST"
    return IncidentOrchestrator(
        repo,
        ToolBroker(repo, incident_id),
        incident_id,
        model="gemini-3.5-flash",
    )


class TestReinvokeOnMalformedOutput:
    def _recovery_events(self, orch: IncidentOrchestrator) -> list[str]:
        return [
            e.summary for e in orch.repo.list_events(orch.incident_id) if e.kind == "agent_recovery"
        ]

    def test_a_hallucinating_agent_is_re_asked_once_and_recovers(
        self, orchestrator: IncidentOrchestrator
    ) -> None:
        attempts: list[str] = []

        async def fake_invoke_once(name: AgentName, message: str) -> SpecialistResult:
            attempts.append(message)
            if len(attempts) == 1:
                return SpecialistResult(
                    agent=name,
                    ok=False,
                    output=None,
                    raw_text="Sure! Here is my assessment in prose.",
                    error="no JSON object found in the final message",
                )
            return SpecialistResult(
                agent=name, ok=True, output={"assessment": "ok"}, raw_text="{}", error=None
            )

        orchestrator._invoke_once = fake_invoke_once  # type: ignore[method-assign]
        result = asyncio.run(orchestrator._invoke(AgentName.COMMANDER, "assess the incident"))

        assert result.ok is True
        assert len(attempts) == 2
        assert "no JSON object found" in attempts[1], "the parser error is handed back to the agent"
        assert any("re-asking once" in s for s in self._recovery_events(orchestrator))
        assert any(
            "recovered" in s or "valid output" in s for s in self._recovery_events(orchestrator)
        )

    def test_the_repair_loop_is_bounded(self, orchestrator: IncidentOrchestrator) -> None:
        """An agent that never converges must stop, not spin."""
        calls = {"n": 0}

        async def always_malformed(name: AgentName, message: str) -> SpecialistResult:
            calls["n"] += 1
            return SpecialistResult(
                agent=name,
                ok=False,
                output=None,
                raw_text="nope",
                error="schema validation failed: 3 error(s)",
            )

        orchestrator._invoke_once = always_malformed  # type: ignore[method-assign]
        result = asyncio.run(orchestrator._invoke(AgentName.COMMANDER, "assess"))

        assert result.ok is False
        assert calls["n"] == 1 + IncidentOrchestrator._MAX_REPAIR_ATTEMPTS

    def test_a_denied_tool_call_is_not_re_asked(self, orchestrator: IncidentOrchestrator) -> None:
        calls = {"n": 0}

        async def denied(name: AgentName, message: str) -> SpecialistResult:
            calls["n"] += 1
            return SpecialistResult(
                agent=name,
                ok=False,
                output=None,
                raw_text="",
                error="tool authorization denied: dispatch may not read inventory",
            )

        orchestrator._invoke_once = denied  # type: ignore[method-assign]
        result = asyncio.run(orchestrator._invoke(AgentName.DISPATCH_AGENT, "fetch inventory"))

        assert result.ok is False
        assert calls["n"] == 1
        assert self._recovery_events(orchestrator) == []
