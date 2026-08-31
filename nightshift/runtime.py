"""Assemble a complete Night Shift runtime.

One place that wires repository, broker, governance, agents, and the field simulator
together, so the CLI, the drill controller, the tests, and the deployed ingestor all get
identically-configured systems rather than four slightly different ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nightshift.common import otel
from nightshift.common.config import Settings, get_settings
from nightshift.common.skills import skill_refs
from nightshift.schemas.enums import AgentName
from services.common.identity import issue_principal_token
from services.common.repository import Repository
from services.gateway.broker import ToolBroker, ToolCallRecord
from services.gateway.governance import (
    HeuristicScreen,
    LocalSemanticPolicy,
    build_content_screen,
)
from services.gateway.identity_tokens import AgentTokenMinter
from services.gateway.transport import HttpTransport, InProcessTransport


@dataclass
class Runtime:
    settings: Settings
    repo: Repository
    broker: ToolBroker
    semantic_policy: LocalSemanticPolicy
    content_screen: Any
    tool_records: list[ToolCallRecord] = field(default_factory=list)

    @property
    def skill_refs(self) -> dict[str, str]:
        return skill_refs()

    def seed_revisions(self, state: str = "ACTIVE", revision: str = "rev-1") -> None:
        """Mark every agent revision qualified. Drills override individual entries."""
        for agent in AgentName:
            self.repo.store.set(
                "agentRevisions",
                f"{agent.value}@{revision}",
                {"agent": agent.value, "revision_id": revision, "state": state},
            )

    def set_revision_state(self, agent: AgentName, revision: str, state: str) -> None:
        self.repo.store.set(
            "agentRevisions",
            f"{agent.value}@{revision}",
            {"agent": agent.value, "revision_id": revision, "state": state},
        )

    def add_memory_note(self, incident_id: str, note: str, *, note_id: str = "") -> None:
        """Write a non-authoritative Memory Bank note.

        Nothing reads these as evidence. They exist so an agent can be *told* something
        remembered and still be required to re-read authoritative state (N8, D9).
        """
        nid = note_id or f"MEM-{abs(hash(note)) % 10**10}"
        self.repo.store.set(
            "memoryNotes",
            nid,
            {"id": nid, "incident_id": incident_id, "note": note, "authoritative": False},
        )

    def memory_context(self, incident_id: str) -> list[str]:
        return [str(n.get("note", "")) for n in self.repo.memory_notes(incident_id)]


def build_runtime(
    *,
    settings: Settings | None = None,
    namespace: str | None = None,
    store_backend: str | None = None,
    semantic_mode: str = "dry_run",
    use_live_content_screen: bool | None = None,
    fault_hook: Any = None,
) -> Runtime:
    settings = settings or get_settings()
    otel.configure_tracing(settings, service_name="runtime")
    namespace = namespace or settings.namespace
    backend = store_backend or settings.store_backend

    repo = Repository.create(
        backend,
        project=settings.project_id,
        database=settings.firestore_database,
        namespace=namespace,
    )

    # Live screening stays keyed on the explicit opt-in, not on whether a template or a
    # Gemma model happens to be configured. A populated .env must not quietly turn the
    # credential-free drill corpus into something that calls two live Google APIs.
    live_screen = (
        use_live_content_screen
        if use_live_content_screen is not None
        else (
            settings.live_content_screen
            and bool(settings.model_armor_template or settings.gemma_screen_model)
        )
    )
    content_screen = (
        build_content_screen(
            settings.model_armor_template,
            settings.region,
            project=settings.project_id,
            gemma_model=settings.gemma_screen_model,
            model_location=settings.model_location,
        )
        if live_screen
        else HeuristicScreen()
    )
    semantic_policy = LocalSemanticPolicy(mode=semantic_mode)

    service_urls = {
        "telemetry": settings.telemetry_url,
        "inventory": settings.inventory_url,
        "capacity": settings.capacity_url,
        "facilities": settings.facilities_url,
        "custody": settings.custody_url,
        "incident_control": settings.incident_url,
    }
    transport: Any
    if all(service_urls.values()):
        # Over HTTP each call is made as the calling agent's own service account, so the
        # §11.3 matrix is enforced by Cloud Run IAM and not only by our own checks.
        transport = HttpTransport(
            base_urls=service_urls,
            minter=AgentTokenMinter(project_id=settings.project_id),
        )
    else:
        transport = InProcessTransport.build(repo)

    records: list[ToolCallRecord] = []
    broker = ToolBroker(
        transport=transport,
        principal_token_for=lambda agent: issue_principal_token(
            agent, "rev-1", settings.agent_shared_secret
        ),
        content_screen=content_screen,
        semantic_policy=semantic_policy,
        fault_hook=fault_hook,
        on_record=records.append,
    )

    runtime = Runtime(
        settings=settings,
        repo=repo,
        broker=broker,
        semantic_policy=semantic_policy,
        content_screen=content_screen,
        tool_records=records,
    )
    runtime.seed_revisions()
    return runtime
