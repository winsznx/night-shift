"""Transports and governance adapters for the tool broker.

``InProcessTransport`` mounts the real FastAPI apps and calls them through ASGI, so the
offline drill corpus exercises the same routes, the same identity checks, and the same
effect commit sequence as the deployed system — only the network hop is missing.

``HttpTransport`` is the Cloud Run path: one authenticated call per service, with a
Google-issued OIDC ID token so the service refuses unauthenticated callers at the edge
before the principal assertion is even parsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from nightshift.safety_kernel.authority import TOOL_REGISTRY
from services.common.identity import PRINCIPAL_HEADER

# Route table: tool name -> (method, path template, how to place the payload).
# "path" params come from the payload; the rest go to query or body.
ROUTES: dict[str, tuple[str, str, list[str]]] = {
    # telemetry
    "get_freezer_state": ("GET", "/v1/freezers/{freezer_id}", ["freezer_id"]),
    "get_temperature_window": ("GET", "/v1/freezers/{freezer_id}/window", ["freezer_id"]),
    "get_recent_door_events": ("GET", "/v1/freezers/{freezer_id}/door-events", ["freezer_id"]),
    "get_equipment_history": ("GET", "/v1/freezers/{freezer_id}/equipment-history", ["freezer_id"]),
    "get_incident_telemetry_summary": (
        "GET",
        "/v1/incidents/{incident_id}/summary",
        ["incident_id"],
    ),
    "get_backup_freezer_state": ("GET", "/v1/backups", []),
    "get_destination_temperature": (
        "GET",
        "/v1/destination-temperature/{freezer_id}",
        ["freezer_id"],
    ),
    # inventory
    "get_container_summary": ("GET", "/v1/containers/{container_id}", ["container_id"]),
    "list_impacted_containers": ("GET", "/v1/freezers/{freezer_id}/impacted", ["freezer_id"]),
    "get_placement_requirements": (
        "GET",
        "/v1/incidents/{incident_id}/placement-requirements",
        ["incident_id"],
    ),
    "get_incident_container_ids": (
        "GET",
        "/v1/incidents/{incident_id}/container-ids",
        ["incident_id"],
    ),
    "get_hold_state": ("GET", "/v1/holds/{freezer_id}", ["freezer_id"]),
    "get_study_notes": ("GET", "/v1/study-notes/{container_id}", ["container_id"]),
    "apply_containment_hold": ("POST", "/v1/holds", []),
    # capacity
    "list_qualified_destinations": ("GET", "/v1/destinations", []),
    "get_capacity": ("GET", "/v1/capacity/{freezer_id}", ["freezer_id"]),
    "get_reservation": ("GET", "/v1/reservations/{reservation_id}", ["reservation_id"]),
    "reserve_capacity": ("POST", "/v1/reservations", []),
    "release_reservation": (
        "POST",
        "/v1/reservations/{reservation_id}/release",
        ["reservation_id"],
    ),
    # facilities
    "get_responder_roster": ("GET", "/v1/responders", []),
    "get_work_order": ("GET", "/v1/work-orders/{work_order_id}", ["work_order_id"]),
    "get_dispatch_state": ("GET", "/v1/dispatches", []),
    "create_work_order": ("POST", "/v1/work-orders", []),
    "dispatch_responder": ("POST", "/v1/dispatches", []),
    "record_repair_status": ("POST", "/v1/repair-status", []),
    "send_vendor_message": ("POST", "/v1/vendor-messages", []),
    # custody
    "get_custody_state": ("GET", "/v1/incidents/{incident_id}/custody", ["incident_id"]),
    "reconcile_incident": ("GET", "/v1/incidents/{incident_id}/reconciliation", ["incident_id"]),
    "record_pickup": ("POST", "/v1/pickups", []),
    "record_destination_scan": ("POST", "/v1/destination-scans", []),
    "commit_transfer": ("POST", "/v1/commits", []),
    "commit_ready_transfers": ("POST", "/v1/commits/batch", []),
    "flag_custody_exception": ("POST", "/v1/exceptions", []),
    # incident control
    "get_incident": ("GET", "/v1/incidents/{incident_id}", ["incident_id"]),
    "get_incident_timeline": ("GET", "/v1/incidents/{incident_id}/timeline", ["incident_id"]),
    "request_incident_transition": (
        "POST",
        "/v1/incidents/{incident_id}/transitions",
        ["incident_id"],
    ),
    "request_incident_close": ("POST", "/v1/incidents/{incident_id}/close", ["incident_id"]),
}


class TransportError(RuntimeError):
    """The service was unreachable or returned an unusable response.

    Distinct from a refusal: this is infrastructure (N12 FailureClass.INFRASTRUCTURE),
    and the qualification engine must not score it as an agent safety failure.
    """


def _split_payload(tool_name: str, payload: dict[str, Any]) -> tuple[str, str, dict, dict]:
    method, template, path_params = ROUTES[tool_name]
    path = template
    rest = dict(payload)
    for name in path_params:
        value = rest.pop(name, None)
        if value is None:
            raise TransportError(f"tool {tool_name!r} requires path parameter {name!r}")
        path = path.replace("{" + name + "}", str(value))
    if method == "GET":
        return method, path, {k: v for k, v in rest.items() if v is not None}, {}
    # POST routes keep path params in the body too where the model expects them.
    body = dict(payload)
    return method, path, {}, body


@dataclass
class InProcessTransport:
    """Calls the real FastAPI apps over ASGI. No network, same code path."""

    clients: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, repository: Any) -> InProcessTransport:
        from fastapi.testclient import TestClient

        from services.capacity.app import app as capacity_app
        from services.custody.app import app as custody_app
        from services.facilities.app import app as facilities_app
        from services.incident_control.app import app as incident_app
        from services.inventory.app import app as inventory_app
        from services.telemetry.app import app as telemetry_app

        apps = {
            "telemetry": telemetry_app,
            "inventory": inventory_app,
            "capacity": capacity_app,
            "facilities": facilities_app,
            "custody": custody_app,
            "incident_control": incident_app,
        }
        clients = {}
        for name, app in apps.items():
            app.state.repository = repository
            clients[name] = TestClient(app, raise_server_exceptions=False)
        return cls(clients=clients)

    def invoke(
        self, tool_name: str, principal_token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        spec = TOOL_REGISTRY[tool_name]
        client = self.clients.get(spec.service)
        if client is None:
            raise TransportError(f"no client for service {spec.service!r}")
        method, path, params, body = _split_payload(tool_name, payload)
        headers = {PRINCIPAL_HEADER: principal_token}
        response = (
            client.get(path, params=params, headers=headers)
            if method == "GET"
            else client.post(path, json=body, headers=headers)
        )
        return _decode(tool_name, response.status_code, _body(tool_name, response))


@dataclass
class HttpTransport:
    """Cloud Run path: authenticated HTTP, one base URL per service."""

    base_urls: dict[str, str]
    timeout: float = 30.0
    _id_tokens: dict[str, str] = field(default_factory=dict, init=False)

    def _auth_header(self, base_url: str) -> dict[str, str]:
        """Fetch a Google-issued OIDC ID token audience-scoped to the target service."""
        token = self._id_tokens.get(base_url)
        if token is None:
            try:
                import google.auth.transport.requests
                import google.oauth2.id_token

                request = google.auth.transport.requests.Request()
                token = google.oauth2.id_token.fetch_id_token(request, base_url)
                self._id_tokens[base_url] = token
            except Exception:
                # Local runs against an unauthenticated service have no metadata server.
                return {}
        return {"Authorization": f"Bearer {token}"}

    def invoke(
        self, tool_name: str, principal_token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        spec = TOOL_REGISTRY[tool_name]
        base = self.base_urls.get(spec.service)
        if not base:
            raise TransportError(f"no base URL configured for service {spec.service!r}")
        method, path, params, body = _split_payload(tool_name, payload)
        headers = {PRINCIPAL_HEADER: principal_token, **self._auth_header(base)}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = (
                    client.get(f"{base}{path}", params=params, headers=headers)
                    if method == "GET"
                    else client.post(f"{base}{path}", json=body, headers=headers)
                )
        except httpx.HTTPError as exc:
            raise TransportError(f"{spec.service} unreachable: {exc}") from exc
        return _decode(tool_name, response.status_code, _body(tool_name, response))


def _body(tool_name: str, response: Any) -> dict[str, Any]:
    """Parse a response body, or fail as infrastructure rather than crashing.

    A 500 from a service returns an HTML or plain-text body. Letting the JSON decoder
    raise here surfaced as an unhandled ``JSONDecodeError`` deep in the agent loop, which
    told nobody which tool had failed. A TransportError is attributed as infrastructure
    (N12) and names the tool.
    """
    if not response.content:
        return {}
    try:
        parsed = response.json()
    except ValueError:
        snippet = response.text[:200].replace("\n", " ")
        raise TransportError(
            f"{tool_name}: service returned a non-JSON body with status "
            f"{response.status_code}: {snippet}"
        ) from None
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _decode(tool_name: str, status: int, data: dict[str, Any]) -> dict[str, Any]:
    if status == 403:
        from nightshift.safety_kernel.decision import Decision, Verdict
        from nightshift.schemas.enums import DenialReason, FailureClass
        from services.gateway.broker import BrokerDeniedError

        raise BrokerDeniedError(
            Decision(
                verdict=Verdict.REFUSE,
                reason=str(data.get("reason", "authorization denied")),
                invariant=str(data.get("invariant", "N7")),
                denial_reason=DenialReason(data.get("denial_reason", "IDENTITY_NOT_PERMITTED")),
                failure_class=FailureClass.POLICY_DENIAL,
                detail=dict(data.get("detail", {})),
            )
        )
    if status == 401:
        raise TransportError(f"{tool_name}: principal assertion rejected")
    if status >= 500:
        raise TransportError(f"{tool_name}: service error {status}")
    if status >= 400:
        raise TransportError(f"{tool_name}: {status} {data}")
    return data
