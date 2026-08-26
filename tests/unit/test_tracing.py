"""Tracing must be observable when on and completely inert when off.

The property that matters most is the second one: an observability layer that can take
down a rescue is worse than no observability layer. Every function in
``nightshift.common.otel`` is expected to degrade to a no-op rather than raise, whatever
the state of the SDK, the exporter, or the credentials.
"""

from __future__ import annotations

import pytest

from nightshift.common import otel


@pytest.fixture(autouse=True)
def _reset_tracing():
    """Each test configures tracing from scratch."""
    original = dict(otel._state)
    otel._state.update({"tracer": None, "configured": False, "enabled": False})
    yield
    otel._state.update(original)


# --------------------------------------------------------------------------------------
# Inert when disabled
# --------------------------------------------------------------------------------------


def test_span_is_a_no_op_when_tracing_is_disabled(monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_TRACING", "0")
    from nightshift.common.config import reload_settings

    reload_settings()

    with otel.span("anything", **{otel.ATTR_INCIDENT: "INC-1"}) as current:
        assert current is None
    assert otel.current_trace_id() is None


def test_helpers_never_raise_without_a_span():
    """Called from inside the rescue path, so they must be unconditionally safe."""
    otel.set_attributes(**{otel.ATTR_TOOL: "reserve_capacity"})
    otel.record_exception(RuntimeError("boom"))
    assert otel.current_trace_id() is None


def test_a_failing_tracer_does_not_propagate(monkeypatch):
    class ExplodingTracer:
        def start_as_current_span(self, _name):
            raise RuntimeError("tracer exploded")

    otel._state.update({"tracer": ExplodingTracer(), "configured": True, "enabled": True})
    with otel.span("effect.capacity_reserve") as current:
        assert current is None  # swallowed, not raised


def test_configure_is_idempotent(monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_TRACING", "0")
    from nightshift.common.config import reload_settings

    reload_settings()
    assert otel.configure_tracing() is False
    assert otel.configure_tracing() is False


# --------------------------------------------------------------------------------------
# Real spans when enabled
# --------------------------------------------------------------------------------------


def test_spans_carry_correlated_trace_ids_when_enabled():
    """With a real in-memory SDK tracer, nested spans share one trace ID."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel._state.update({"tracer": provider.get_tracer("test"), "configured": True, "enabled": True})

    with otel.span("incident.run", **{otel.ATTR_INCIDENT: "INC-1"}):
        outer = otel.current_trace_id()
        with otel.span(
            "tool.reserve_capacity",
            **{otel.ATTR_TOOL: "reserve_capacity", otel.ATTR_AGENT: "capacity-broker"},
        ):
            inner = otel.current_trace_id()
            otel.set_attributes(**{otel.ATTR_DECISION: "ALLOW"})

    assert outer is not None and len(outer) == 32
    assert inner == outer, "a tool call must join its incident's trace"

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"incident.run", "tool.reserve_capacity"}
    tool_span = spans["tool.reserve_capacity"]
    assert tool_span.attributes[otel.ATTR_TOOL] == "reserve_capacity"
    assert tool_span.attributes[otel.ATTR_AGENT] == "capacity-broker"
    assert tool_span.attributes[otel.ATTR_DECISION] == "ALLOW"


def test_cloud_trace_url_is_credential_free():
    url = otel.cloud_trace_url("a" * 32, project_id="my-project")
    assert url.startswith("https://console.cloud.google.com/traces/list")
    assert "my-project" in url and "a" * 32 in url
    for secret_marker in ("key", "token", "secret", "password"):
        assert secret_marker not in url.lower()


def test_cloud_trace_url_falls_back_to_the_configured_project(monkeypatch):
    """An omitted project uses the configured one; only a truly absent one yields ''."""
    # No trace id means no link, whatever the project.
    assert otel.cloud_trace_url("", project_id="p") == ""

    # An omitted project falls back to settings, which is the useful default.
    from nightshift.common.config import get_settings

    configured = get_settings().project_id
    fallback = otel.cloud_trace_url("a" * 32, project_id="")
    if configured:
        assert configured in fallback
    else:
        assert fallback == ""


# --------------------------------------------------------------------------------------
# The receipt / trace join
# --------------------------------------------------------------------------------------


def test_effect_commits_record_the_trace_they_ran_under():
    """A receipt without a trace id cannot be joined back to its execution."""
    from opentelemetry.sdk.trace import TracerProvider

    from fixtures.estate import build_estate, seed_repository
    from nightshift.common.config import get_settings
    from nightshift.common.store import MemoryStore
    from nightshift.schemas.enums import AgentName
    from services.common.identity import issue_principal_token
    from services.common.repository import Repository
    from services.gateway.broker import ToolBroker
    from services.gateway.transport import InProcessTransport

    otel._state.update(
        {"tracer": TracerProvider().get_tracer("test"), "configured": True, "enabled": True}
    )

    store = MemoryStore()
    repo = Repository(store, namespace="test")
    seed_repository(repo, build_estate())
    for agent in AgentName:
        store.set(
            "agentRevisions",
            f"{agent.value}@rev-1",
            {"agent": agent.value, "revision_id": "rev-1", "state": "ACTIVE"},
        )

    secret = get_settings().agent_shared_secret
    broker = ToolBroker(
        transport=InProcessTransport.build(repo),
        principal_token_for=lambda a: issue_principal_token(a, "rev-1", secret),
    )

    with otel.span("incident.run", **{otel.ATTR_INCIDENT: "INC-TRACE"}):
        result = broker.call(
            AgentName.INGESTOR,
            "apply_containment_hold",
            {"incident_id": "INC-TRACE", "freezer_id": "F-17", "reason": "trace test"},
        )

    # The hold is refused (no such incident), and the refusal receipt still carries the
    # trace — a refusal is exactly the thing an auditor most wants to trace back.
    receipt = result["receipt"]
    assert receipt["trace_id"] is not None
    assert len(receipt["trace_id"]) == 32
    assert broker.records[0].trace_id == receipt["trace_id"]
