"""Offline verifier.

Reads a manifest, checks its signature, and recomputes the hard verdict from the stored
state snapshot using the same kernel the production services used. No model. No network
beyond fetching the manifest itself.
"""

from nightshift.verify.verifier import (
    VerificationResult,
    VerificationStatus,
    verify_manifest,
    verify_manifest_file,
)

__all__ = [
    "VerificationResult",
    "VerificationStatus",
    "verify_manifest",
    "verify_manifest_file",
]
