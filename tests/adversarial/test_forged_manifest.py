"""A manifest signed by a key that is not ours must never verify.

The attack this closes was reproduced against the published flagship manifest. Edit the
body, generate your own EC P-256 key, re-sign the edited body with it, write your own
public key into the signature block, and leave the real Cloud KMS ``key_ref`` string
untouched. Every check passed and the verifier printed ``RESULT: PASS``, because it
checked the signature against the key the document itself supplied.

Two forged documents claiming the same ``incident_id`` both verifying is worse than no
verifier at all, so this is asserted from the attacker's side rather than described.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from nightshift.common.canonical import canonical_bytes
from nightshift.verify.trusted_keys import KMS_EVIDENCE_SIGNER_PUB, key_is_pinned
from nightshift.verify.verifier import VerificationStatus, verify_manifest

MANIFESTS = sorted(
    (Path(__file__).resolve().parents[2] / "evidence" / "incidents").glob("*.manifest.json")
)


@pytest.fixture
def genuine() -> dict[str, Any]:
    if not MANIFESTS:
        pytest.skip("no published manifest to forge against")
    return json.loads(MANIFESTS[0].read_text(encoding="utf-8"))


def _resign_with_attacker_key(manifest: dict[str, Any]) -> dict[str, Any]:
    """Re-sign a manifest with a freshly generated key, exactly as an attacker would."""
    attacker = ec.generate_private_key(ec.SECP256R1())
    body = {k: v for k, v in manifest.items() if k != "signature"}
    payload = canonical_bytes(body)
    digest = hashlib.sha256(payload).hexdigest()
    raw = attacker.sign(bytes.fromhex(digest), ec.ECDSA(Prehashed(hashes.SHA256())))

    forged = copy.deepcopy(manifest)
    forged["signature"] = {
        **manifest["signature"],
        # The real KMS key reference is left in place. This is the tell the old
        # verifier never looked at.
        "signature_b64": base64.b64encode(raw).decode("ascii"),
        "digest_sha256": digest,
        "public_key_pem": attacker.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii"),
    }
    return forged


class TestForgedManifest:
    def test_the_genuine_manifest_still_verifies(self, genuine: dict[str, Any]) -> None:
        """Guard rail. If pinning broke the real artifact, this fails first."""
        assert verify_manifest(genuine).status is VerificationStatus.PASS

    def test_an_edited_body_resigned_with_an_attacker_key_is_rejected(
        self, genuine: dict[str, Any]
    ) -> None:
        tampered = copy.deepcopy(genuine)
        tampered["incident_state"] = "CLOSED"
        forged = _resign_with_attacker_key(tampered)

        result = verify_manifest(forged)

        assert result.status is VerificationStatus.MISMATCH
        pin = next(c for c in result.checks if c.name.startswith("signing key"))
        assert pin.ok is False
        assert "claims Cloud KMS provenance" in pin.detail

    def test_an_unedited_body_resigned_with_an_attacker_key_is_still_rejected(
        self, genuine: dict[str, Any]
    ) -> None:
        """The signature is internally valid here. Only the pin catches it."""
        forged = _resign_with_attacker_key(genuine)

        result = verify_manifest(forged)

        assert result.status is VerificationStatus.MISMATCH
        signature_check = next(c for c in result.checks if c.name.startswith("signature"))
        assert signature_check.ok is True, "the forged signature is cryptographically valid"
        assert next(c for c in result.checks if c.name.startswith("signing key")).ok is False

    def test_a_detached_signature_is_pinned_too(self, genuine: dict[str, Any]) -> None:
        forged = _resign_with_attacker_key(genuine)

        result = verify_manifest(genuine, signature=forged["signature"])

        assert result.status is VerificationStatus.MISMATCH


class TestKeyPinning:
    def test_the_published_kms_key_is_trusted(self) -> None:
        ok, detail = key_is_pinned(KMS_EVIDENCE_SIGNER_PUB)

        assert ok is True
        assert "Cloud KMS" in detail

    def test_whitespace_differences_do_not_break_the_pin(self) -> None:
        """A trailing newline must not read as a forgery on a live request path."""
        assert key_is_pinned(KMS_EVIDENCE_SIGNER_PUB.strip())[0] is True
        assert key_is_pinned(KMS_EVIDENCE_SIGNER_PUB + "\n\n")[0] is True

    def _fresh_pem(self) -> str:
        return (
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

    def test_a_fresh_key_claiming_kms_provenance_is_a_hard_failure(self) -> None:
        """The forgery signature: our key_ref, someone else's key."""
        ok, detail = key_is_pinned(
            self._fresh_pem(),
            backend="cloud-kms",
            key_ref="projects/p/locations/us-central1/keyRings/nightshift/"
            "cryptoKeys/evidence-signer/cryptoKeyVersions/1",
        )

        assert ok is False
        assert "claims Cloud KMS provenance" in detail

    def test_a_fresh_key_claiming_only_local_provenance_is_unestablished(self) -> None:
        """What `make incident` produces on a laptop with no credentials."""
        ok, detail = key_is_pinned(self._fresh_pem(), backend="local-ec-p256", key_ref="local")

        assert ok is None
        assert "provenance is not established" in detail

    @pytest.mark.parametrize("pem", ["", "not a pem", "-----BEGIN PUBLIC KEY-----\nzz\n"])
    def test_unparseable_keys_fail_closed(self, pem: str) -> None:
        assert key_is_pinned(pem)[0] is False
