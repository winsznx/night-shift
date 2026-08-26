"""OpenTelemetry instrumentation and Cloud Trace export (PRD §30).

Every incident, action, tool call, and specialist delegation carries the same set of
attributes, so a trace can be read the way the incident timeline reads: which agent, on
which incident, attempting which action, against which tool, with which receipt.

The design constraint that matters: **tracing must never change behaviour.** If the
exporter cannot reach Cloud Trace, or the SDK is not installed, every function here
degrades to a no-op and the system runs identically. An observability layer that can
take down a rescue is worse than no observability layer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from nightshift.common.config import Settings, get_settings

log = logging.getLogger(__name__)

# Attribute names. Kept as constants so a span and a receipt cannot drift apart.
ATTR_INCIDENT = "nightshift.incident_id"
ATTR_AGENT = "nightshift.agent"
ATTR_AGENT_REVISION = "nightshift.agent_revision"
ATTR_ACTION_ID = "nightshift.action_id"
ATTR_ACTION_TYPE = "nightshift.action_type"
ATTR_TOOL = "nightshift.tool"
ATTR_SERVICE = "nightshift.service"
ATTR_RECEIPT = "nightshift.receipt_id"
ATTR_INVARIANT = "nightshift.invariant"
ATTR_DECISION = "nightshift.decision"
ATTR_DUPLICATE = "nightshift.duplicate_returned"
ATTR_POLICY = "nightshift.policy_verdict"
ATTR_SCREEN = "nightshift.content_screen"
ATTR_FAILURE_CLASS = "nightshift.failure_class"

_state: dict[str, Any] = {"tracer": None, "configured": False, "enabled": False}


def configure_tracing(
    settings: Settings | None = None, *, service_name: str = "nightshift"
) -> bool:
    """Set up the tracer once. Returns whether tracing is actually active.

    Idempotent, and safe to call from every service entrypoint.
    """
    if _state["configured"]:
        return bool(_state["enabled"])
    _state["configured"] = True

    settings = settings or get_settings()
    if not settings.tracing_enabled:
        log.debug("tracing disabled (NIGHTSHIFT_TRACING is not set)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": f"nightshift-{service_name}",
                "service.version": settings.source_commit or "unknown",
                "deployment.environment": settings.deployment_env,
                "cloud.region": settings.region,
            }
        )
        provider = TracerProvider(resource=resource)

        exporter = None
        if settings.project_id:
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

                exporter = CloudTraceSpanExporter(project_id=settings.project_id)
            except Exception as exc:
                log.warning(
                    "Cloud Trace exporter unavailable (%s); spans are created but not "
                    "exported. Trace IDs remain valid and correlated.",
                    exc,
                )
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _state["tracer"] = trace.get_tracer("nightshift")
        _state["enabled"] = True
        log.info(
            "tracing enabled for nightshift-%s (export=%s)",
            service_name,
            "cloud-trace" if exporter else "local-only",
        )
        return True
    except Exception as exc:
        log.warning("tracing could not be configured (%s); continuing without it", exc)
        _state["enabled"] = False
        return False


def _tracer() -> Any:
    if not _state["configured"]:
        configure_tracing()
    return _state["tracer"]


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span, or do nothing at all if tracing is off.

    Yields the span (or ``None``), so callers can set late attributes without caring
    whether tracing is active.
    """
    tracer = _tracer()
    if tracer is None:
        yield None
        return
    try:
        with tracer.start_as_current_span(name) as current:
            for key, value in attributes.items():
                if value is not None:
                    current.set_attribute(key, _coerce(value))
            yield current
    except Exception as exc:
        # A tracing failure must never propagate into the rescue path.
        log.debug("span %s failed: %s", name, exc)
        yield None


def _coerce(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def set_attributes(**attributes: Any) -> None:
    """Add attributes to the current span, if there is one."""
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        if current is None or not current.is_recording():
            return
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, _coerce(value))
    except Exception:
        return


def record_exception(exc: BaseException) -> None:
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        if current is not None and current.is_recording():
            current.record_exception(exc)
            current.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
    except Exception:
        return


def current_trace_id() -> str | None:
    """The current W3C trace ID as 32 hex characters, or None.

    This is what lands on a receipt and in the evidence manifest, so a judge can take an
    incident's trace ID and find the same execution in Cloud Trace.
    """
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        if current is None:
            return None
        context = current.get_span_context()
        if context is None or not context.is_valid:
            return None
        return format(context.trace_id, "032x")
    except Exception:
        return None


def cloud_trace_url(trace_id: str, project_id: str = "") -> str:
    """A console link for a trace ID. Carries no credentials or payload."""
    project_id = project_id or get_settings().project_id
    if not (trace_id and project_id):
        return ""
    return f"https://console.cloud.google.com/traces/list?project={project_id}&tid={trace_id}"


def tracing_status() -> dict[str, Any]:
    settings = get_settings()
    if not _state["configured"]:
        configure_tracing(settings)
    return {
        "enabled": bool(_state["enabled"]),
        "requested": settings.tracing_enabled,
        "project_id": settings.project_id,
        "exporter": "cloud-trace" if _state["enabled"] and settings.project_id else "none",
    }
