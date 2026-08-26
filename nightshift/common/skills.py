"""Operational skill governance.

Skills are versioned, content-addressed procedural playbooks. The revision reference
stored in an incident manifest is the SHA-256 of the skill body, so "which procedure was
in force when this incident ran" is answerable from the manifest alone, and editing a
skill after the fact changes its reference rather than silently rewriting history.

When Agent Registry skill governance is available, these same bodies are registered
there and the managed resource name is recorded alongside the content hash. When it is
not, the content hash is the whole story and ``CLAIMS.json`` says so — this module never
pretends a managed SkillRevision resource exists (PRD §10.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from nightshift.common.canonical import sha256_bytes
from nightshift.common.config import get_settings

SKILL_NAMES = (
    "freezer-failure-response",
    "impact-assessment",
    "backup-capacity-placement",
    "after-hours-dispatch",
    "specimen-transfer-procedure",
    "incident-recovery-and-closeout",
)


@dataclass(frozen=True)
class SkillRevision:
    name: str
    revision: str
    """``sha256:<first 16 hex>`` — content-addressed, so the body cannot drift."""
    content_sha256: str
    body: str
    managed_resource: str | None = None
    """Agent Registry resource name when skill governance is available, else None."""

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "revision": self.revision,
            "content_sha256": self.content_sha256,
            "managed_resource": self.managed_resource,
        }


@lru_cache(maxsize=1)
def load_skills(skills_dir: str | None = None) -> dict[str, SkillRevision]:
    root = Path(skills_dir) if skills_dir else get_settings().skills_dir
    out: dict[str, SkillRevision] = {}
    for name in SKILL_NAMES:
        path = root / name / "SKILL.md"
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        digest = sha256_bytes(body.encode("utf-8"))
        out[name] = SkillRevision(
            name=name,
            revision=f"sha256:{digest[:16]}",
            content_sha256=digest,
            body=body,
        )
    return out


def skill_refs(skills_dir: str | None = None) -> dict[str, str]:
    """``{name: revision}`` for the manifest and the agent prompts."""
    return {name: rev.revision for name, rev in sorted(load_skills(skills_dir).items())}


def skills_for_agent(agent_value: str, skills_dir: str | None = None) -> dict[str, str]:
    applies = {
        "signal-investigator": ["freezer-failure-response"],
        "impact-analyst": ["impact-assessment"],
        "capacity-broker": ["backup-capacity-placement"],
        "dispatch-agent": ["after-hours-dispatch"],
        "custody-agent": ["specimen-transfer-procedure"],
        "incident-commander": ["freezer-failure-response", "incident-recovery-and-closeout"],
    }.get(agent_value, [])
    loaded = load_skills(skills_dir)
    return {name: loaded[name].revision for name in applies if name in loaded}
