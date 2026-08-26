"""A platform denial must survive the transport layer as a denial.

Cloud Run refuses an unauthorized caller at its edge, before the request reaches any
Night Shift code. That refusal arrives as an HTML error page, not JSON — Google's edge
has no reason to speak our content type.

The transport used to parse the body before looking at the status, so those denials
raised ``TransportError`` and were attributed to N12 INFRASTRUCTURE. That is the failure
class the qualification engine is designed to *excuse*, which means the single most
valuable result the system can produce — the platform refusing a forbidden call — was
being filed as noise and silently dropped out of the safety score.

These tests pin the ordering: status first, body second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from nightshift.schemas.enums import AgentName, DenialReason, FailureClass
from services.gateway.broker import BrokerDeniedError
from services.gateway.transport import HttpTransport, TransportError

CLOUD_RUN_403_HTML = (
    "<html><head><title>403 Forbidden</title></head>\n"
    "<body><h1>Error: Forbidden</h1>\n"
    "<h2>Your client does not have permission to get URL <code>/v1/study-notes/C-1</code> "
    "from this server.</h2></body></html>"
)
CLOUD_RUN_401_HTML = (
    "<html><head><title>401 Unauthorized</title></head>\n"
    "<body><h1>Error: Unauthorized</h1>\n"
    "<h2>Your client does not have permission.</h2></body></html>"
)


@dataclass
class _Response:
    """Just enough of an httpx response. Parses real JSON, raises on anything else."""

    status_code: int
    text: str

    @property
    def content(self) -> bytes:
        return self.text.encode()

    def json(self) -> Any:
        return json.loads(self.text)


class _StubClient:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.sent_headers: dict[str, str] = {}

    def __enter__(self) -> _StubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, params: Any = None, headers: Any = None) -> _Response:
        self.sent_headers = dict(headers or {})
        return self._response

    post = get


@dataclass
class _StubMinter:
    """Stands in for IAM Credentials impersonation."""

    token: str | None = "id-token-for-ns-dispatch"
    reason: str = ""

    def service_account(self, agent: AgentName) -> str:
        return f"ns-{agent.value}@example.iam.gserviceaccount.com"

    def mint(self, agent: AgentName, audience: str) -> tuple[str | None, str]:
        return self.token, self.reason


def _transport(response: _Response, minter: Any = None) -> tuple[HttpTransport, _StubClient]:
    client = _StubClient(response)
    transport = HttpTransport(
        base_urls={"inventory": "https://inventory.example"},
        minter=minter,
    )
    return transport, client


def _invoke(transport: HttpTransport, client: _StubClient, monkeypatch: Any) -> dict[str, Any]:
    monkeypatch.setattr("httpx.Client", lambda **_: client)
    return transport.invoke("get_study_notes", "principal-token", {"container_id": "C-1"})


def test_cloud_run_edge_403_is_a_denial_not_an_outage(monkeypatch):
    transport, client = _transport(_Response(403, CLOUD_RUN_403_HTML))

    with pytest.raises(BrokerDeniedError) as caught:
        _invoke(transport, client, monkeypatch)

    decision = caught.value.decision
    assert decision.invariant == "N7"
    assert decision.failure_class is FailureClass.POLICY_DENIAL
    assert decision.denial_reason is DenialReason.IDENTITY_NOT_PERMITTED


def test_cloud_run_edge_401_is_a_denial_not_an_outage(monkeypatch):
    transport, client = _transport(_Response(401, CLOUD_RUN_401_HTML))

    with pytest.raises(BrokerDeniedError) as caught:
        _invoke(transport, client, monkeypatch)

    assert caught.value.decision.failure_class is FailureClass.POLICY_DENIAL
    assert caught.value.decision.detail["layer"] == "cloud-run-iam"


def test_a_genuine_outage_is_still_infrastructure(monkeypatch):
    """The guard must not swallow real failures — a 500 stays a TransportError."""
    transport, client = _transport(_Response(500, "<html>Internal Server Error</html>"))

    with pytest.raises(TransportError):
        _invoke(transport, client, monkeypatch)


def test_successful_impersonation_is_recorded(monkeypatch):
    """An empty note list must never be readable as 'everything was impersonated'."""
    transport, client = _transport(_Response(200, "{}"), minter=_StubMinter())
    monkeypatch.setattr("httpx.Client", lambda **_: client)
    transport.invoke(
        "get_study_notes",
        "principal-token",
        {"container_id": "C-1"},
        agent=AgentName.DISPATCH_AGENT,
    )

    assert len(transport.identity_notes) == 1
    note = transport.identity_notes[0]
    assert note["impersonated"] == "yes"
    assert note["principal"].startswith("ns-dispatch-agent@")
    assert client.sent_headers["Authorization"] == "Bearer id-token-for-ns-dispatch"


def test_failed_impersonation_is_recorded_with_its_reason(monkeypatch):
    """Degrading is allowed. Degrading quietly is not."""
    minter = _StubMinter(token=None, reason="PermissionDenied: missing tokenCreator")
    transport, client = _transport(_Response(200, "{}"), minter=minter)
    monkeypatch.setattr("httpx.Client", lambda **_: client)
    transport.invoke(
        "get_study_notes",
        "principal-token",
        {"container_id": "C-1"},
        agent=AgentName.DISPATCH_AGENT,
    )

    note = transport.identity_notes[0]
    assert note["impersonated"] == "no"
    assert "tokenCreator" in note["reason"]
    assert "Authorization" not in client.sent_headers
