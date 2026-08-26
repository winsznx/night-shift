"""Runtime configuration.

Everything is environment-driven with repo-relative defaults. No developer-specific
absolute paths, ever (PRD §40).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Google Cloud -------------------------------------------------------------
    project_id: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    region: str = field(default_factory=lambda: _env("NIGHTSHIFT_REGION", "us-central1"))
    model_location: str = field(default_factory=lambda: _env("NIGHTSHIFT_MODEL_LOCATION", "global"))
    """Gemini 3.5 Flash is served from the ``global`` Vertex endpoint; regional
    infrastructure stays in ``NIGHTSHIFT_REGION`` (PRD §6.4 coherent alternative)."""

    firestore_database: str = field(
        default_factory=lambda: _env("NIGHTSHIFT_FIRESTORE_DB", "(default)")
    )
    evidence_bucket: str = field(default_factory=lambda: _env("NIGHTSHIFT_EVIDENCE_BUCKET"))
    kms_key: str = field(default_factory=lambda: _env("NIGHTSHIFT_KMS_KEY"))
    """Full resource name: projects/P/locations/L/keyRings/R/cryptoKeys/K/cryptoKeyVersions/V"""

    model_armor_template: str = field(
        default_factory=lambda: _env("NIGHTSHIFT_MODEL_ARMOR_TEMPLATE")
    )
    live_content_screen: bool = field(
        default_factory=lambda: _flag("NIGHTSHIFT_LIVE_CONTENT_SCREEN", False)
    )
    """Opt in to calling Model Armor for real.

    Deliberately independent of whether a template is configured. Keying live screening
    off the template's mere presence meant that anyone with a populated ``.env`` ran the
    "deterministic, credential-free" drill corpus against a live Google API without
    asking for it, so the suite's headline property was true only on a machine that
    happened to be unconfigured. The deployment sets this; local runs and CI do not.
    """
    memory_bank_name: str = field(default_factory=lambda: _env("NIGHTSHIFT_MEMORY_BANK"))
    agent_registry_location: str = field(
        default_factory=lambda: _env("NIGHTSHIFT_REGISTRY_LOCATION", "us-central1")
    )

    # --- Model --------------------------------------------------------------------
    model_id: str = field(default_factory=lambda: _env("NIGHTSHIFT_MODEL", "gemini-3.5-flash"))
    use_vertex: bool = field(default_factory=lambda: _flag("GOOGLE_GENAI_USE_VERTEXAI", True))

    # --- Storage backend ----------------------------------------------------------
    store_backend: str = field(default_factory=lambda: _env("NIGHTSHIFT_STORE", "memory"))
    """``memory`` for deterministic offline runs, ``firestore`` for the live plane."""

    namespace: str = field(default_factory=lambda: _env("NIGHTSHIFT_NAMESPACE", "demo"))
    """Isolates demo/drill data from operational data (PRD §27)."""

    # --- Service endpoints --------------------------------------------------------
    telemetry_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_TELEMETRY_URL"))
    inventory_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_INVENTORY_URL"))
    capacity_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_CAPACITY_URL"))
    facilities_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_FACILITIES_URL"))
    custody_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_CUSTODY_URL"))
    incident_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_INCIDENT_URL"))
    gateway_url: str = field(default_factory=lambda: _env("NIGHTSHIFT_GATEWAY_URL"))

    # --- Behaviour ----------------------------------------------------------------
    tracing_enabled: bool = field(default_factory=lambda: _flag("NIGHTSHIFT_TRACING", False))
    signer_backend: str = field(default_factory=lambda: _env("NIGHTSHIFT_SIGNER", "auto"))
    """``auto`` uses KMS when NIGHTSHIFT_KMS_KEY is set, else the local dev key."""

    agent_shared_secret: str = field(
        default_factory=lambda: _env("NIGHTSHIFT_AGENT_SECRET", "nightshift-local-dev-secret")
    )
    """HMAC secret backing local agent principal tokens. In the live plane, service
    identity is carried by Google-issued ID tokens instead; this is the offline path."""

    source_commit: str = field(default_factory=lambda: _env("NIGHTSHIFT_COMMIT", "unknown"))
    deployment_env: str = field(default_factory=lambda: _env("NIGHTSHIFT_ENV", "local"))

    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def evidence_dir(self) -> Path:
        return REPO_ROOT / "evidence"

    @property
    def fixtures_dir(self) -> Path:
        return REPO_ROOT / "fixtures"

    @property
    def corpus_dir(self) -> Path:
        return REPO_ROOT / "corpus"

    @property
    def skills_dir(self) -> Path:
        return REPO_ROOT / "skills"

    @property
    def keys_dir(self) -> Path:
        return REPO_ROOT / "keys"

    @property
    def has_gcp(self) -> bool:
        return bool(self.project_id)

    def vertex_host(self) -> str:
        if self.model_location == "global":
            return "https://aiplatform.googleapis.com"
        return f"https://{self.model_location}-aiplatform.googleapis.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def _load_dotenv() -> None:
    """Load ``.env`` from the repo root if present. Real environment always wins."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
