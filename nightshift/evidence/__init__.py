"""Deterministic Evidence Compiler.

Not an agent. No LLM output may alter anything in this package (PRD §8.7).
"""

from nightshift.evidence.manifest import (
    MANIFEST_VERSION,
    build_manifest,
    manifest_hash,
)
from nightshift.evidence.signing import (
    KmsSigner,
    LocalSigner,
    NullSigner,
    Signature,
    Signer,
    get_signer,
    verify_signature,
)

__all__ = [
    "MANIFEST_VERSION",
    "KmsSigner",
    "LocalSigner",
    "NullSigner",
    "Signature",
    "Signer",
    "build_manifest",
    "get_signer",
    "manifest_hash",
    "verify_signature",
]
