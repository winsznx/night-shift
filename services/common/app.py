"""FastAPI application factory shared by every domain service.

Each domain service is a separate app with a separate authority boundary and, in the
live plane, a separate Cloud Run service and service account. They share this factory
and one container image; ``NIGHTSHIFT_SERVICE`` selects which app the image serves.

Every agent-callable mutating route depends on ``require_tool(...)``, which re-runs the
§11.3 check server-side. That is deliberate belt-and-braces: the tool broker already
refused the call, and the service refuses it again, so skipping the broker buys an
attacker nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from nightshift.common import otel
from nightshift.common.config import Settings, get_settings
from nightshift.safety_kernel.decision import Decision
from services.common.identity import (
    PRINCIPAL_HEADER,
    AgentPrincipal,
    PrincipalError,
    authorize,
    verify_principal_token,
)
from services.common.repository import Repository


class AuthorizationDenied(HTTPException):
    """403 with the kernel's own refusal payload, so the UI and ledger agree."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(status_code=403, detail=decision.as_dict())
        self.decision = decision


def get_repository(request: Request) -> Repository:
    return request.app.state.repository  # type: ignore[no-any-return]


def get_service_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_principal(
    request: Request,
    x_nightshift_principal: str | None = Header(default=None, alias=PRINCIPAL_HEADER),
) -> AgentPrincipal | None:
    if not x_nightshift_principal:
        return None
    settings: Settings = request.app.state.settings
    try:
        return verify_principal_token(x_nightshift_principal, settings.agent_shared_secret)
    except PrincipalError as exc:
        raise HTTPException(status_code=401, detail={"error": str(exc)}) from exc


def require_tool(tool_name: str) -> Callable[..., Any]:
    """Dependency that enforces the permission matrix for one registered tool."""

    async def _dep(principal: AgentPrincipal | None = Depends(get_principal)) -> AgentPrincipal:
        decision = authorize(principal, tool_name)
        if not decision.allowed:
            raise AuthorizationDenied(decision)
        assert principal is not None
        return principal

    return _dep


def create_app(
    *,
    service_name: str,
    title: str,
    description: str,
    settings: Settings | None = None,
    repository: Repository | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    otel.configure_tracing(settings, service_name=service_name)
    app = FastAPI(title=title, description=description, version="1.0.0")
    app.state.settings = settings
    app.state.service_name = service_name
    app.state.repository = repository or Repository.create(
        settings.store_backend,
        project=settings.project_id,
        namespace=settings.namespace,
    )

    @app.exception_handler(AuthorizationDenied)
    async def _denied(_request: Request, exc: AuthorizationDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content=exc.detail)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, Any]:
        return {
            "service": service_name,
            "status": "ok",
            "store": app.state.repository.store.backend,
            "namespace": app.state.repository.namespace,
            "env": settings.deployment_env,
            "commit": settings.source_commit,
            "tracing": otel.tracing_status(),
        }

    return app
