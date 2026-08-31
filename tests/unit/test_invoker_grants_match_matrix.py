"""The Cloud Run invoker grants must be exactly what the permission matrix implies.

This drift is invisible to every other test in the suite. The drill corpus runs through
``InProcessTransport``, where there is no network hop and therefore no Cloud Run edge, so
a missing ``run.invoker`` grant changes nothing offline and 126 runs pass green.

It surfaced the first time a rescue was driven over HTTP against real services. The
Capacity Broker holds ``inventory.placement_view`` in the matrix but was not an invoker
on the Inventory service, so ``get_placement_requirements`` came back as a platform
denial, the broker placed nothing, and the Commander escalated a rescue that should have
completed.

Missing grants and extra grants are both failures. A missing one breaks a rescue. An
extra one quietly widens an agent's reach past the matrix the whole security argument
rests on, and would weaken the recorded denial in ``evidence/iam-denial.json``.
"""

from __future__ import annotations

import re
from pathlib import Path

from nightshift.safety_kernel.authority import TOOL_REGISTRY, tools_for
from nightshift.schemas.enums import AgentName
from services.gateway.identity_tokens import AGENT_SERVICE_ACCOUNTS

DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "deploy_services.sh"

SERVICE_TO_CLOUD_RUN = {
    "telemetry": "nightshift-telemetry",
    "inventory": "nightshift-inventory",
    "capacity": "nightshift-capacity",
    "facilities": "nightshift-facilities",
    "custody": "nightshift-custody",
    "incident_control": "nightshift-incident",
}

ALWAYS_INVOKER = {"ns-svc-bff"}
"""The BFF calls every domain service on behalf of the responder flow and the read paths.

It is not an agent identity and carries no agent authority, so it sits outside the
matrix rather than being derived from it.
"""


def matrix_invokers() -> dict[str, set[str]]:
    """Which service accounts the permission matrix says must reach each service."""
    required: dict[str, set[str]] = {name: set(ALWAYS_INVOKER) for name in SERVICE_TO_CLOUD_RUN}
    for agent in AgentName:
        account = AGENT_SERVICE_ACCOUNTS.get(agent)
        if not account:
            continue
        for tool_name in tools_for(agent):
            spec = TOOL_REGISTRY.get(tool_name)
            if spec is None or spec.service not in required:
                continue
            required[spec.service].add(account)
    return required


def script_invokers() -> dict[str, set[str]]:
    """Which service accounts the deploy script actually grants, per service."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    granted: dict[str, set[str]] = {name: set() for name in SERVICE_TO_CLOUD_RUN}
    pattern = re.compile(r"for sa in ([^;]+); do\s*\n\s*invoker (nightshift-[a-z]+) ", re.MULTILINE)
    reverse = {v: k for k, v in SERVICE_TO_CLOUD_RUN.items()}
    for accounts, cloud_run_name in pattern.findall(text):
        service = reverse.get(cloud_run_name)
        if service is None:
            continue
        granted[service].update(accounts.split())
    return granted


def test_the_deploy_script_grants_every_service_the_matrix_requires() -> None:
    required = matrix_invokers()
    granted = script_invokers()

    missing = {
        service: sorted(required[service] - granted[service])
        for service in required
        if required[service] - granted[service]
    }

    assert not missing, (
        "the permission matrix grants these agents a tool on a service the deploy script "
        f"never makes them an invoker on, so the call dies at the Cloud Run edge: {missing}"
    )


def test_the_deploy_script_grants_nothing_the_matrix_does_not() -> None:
    required = matrix_invokers()
    granted = script_invokers()

    extra = {
        service: sorted(granted[service] - required[service])
        for service in required
        if granted[service] - required[service]
    }

    assert not extra, (
        "the deploy script makes these agents invokers on services the matrix gives them "
        f"no tool on, which widens their reach past the matrix: {extra}"
    )


def test_the_parser_actually_found_the_grant_blocks() -> None:
    """A regex that silently matches nothing would make both tests above vacuous."""
    granted = script_invokers()

    assert set(granted) == set(SERVICE_TO_CLOUD_RUN)
    for service, accounts in granted.items():
        assert accounts, f"no invoker block parsed for {service}"


def test_dispatch_is_not_an_inventory_invoker() -> None:
    """The specific denial evidence/iam-denial.json records, pinned so a well-meaning
    grant cannot quietly retire the project's only platform-level refusal."""
    assert AGENT_SERVICE_ACCOUNTS[AgentName.DISPATCH_AGENT] == "ns-dispatch"
    assert "ns-dispatch" not in matrix_invokers()["inventory"]
    assert "ns-dispatch" not in script_invokers()["inventory"]
