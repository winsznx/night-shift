"""The public keys a Night Shift manifest is allowed to have been signed by.

A manifest's signature block carries the public key that signed it, and the verifier
used that key to check that signature. That is a closed loop. Replace the body, sign it
with a key you generated, write your own public key into the block, leave the real Cloud
KMS ``key_ref`` string untouched, and the verifier reports ``RESULT: PASS``. That was
reproduced against the published flagship manifest before this module existed.

Verification has to start from keys the verifier already trusts, not from the key the
document nominates. That is what pinning means and it is the whole content of this file.

The PEMs are embedded in source rather than read from ``keys/`` because the verifier has
to reach the same verdict in three places that do not share a filesystem:

* a clean-room extraction of ``git archive``, which has no working tree;
* the Cloud Run image, which deliberately does not ship ``keys/`` so the private half
  can never be within reach of a running service; and
* a judge's laptop holding one downloaded manifest and nothing else.

A public key is public. Carrying it in source costs nothing and is the only way the pin
holds everywhere the verifier runs.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

KMS_EVIDENCE_SIGNER_PUB = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE7zmdy0CR8Xwk5WlAERW95OR/ohBT
JUGhskxKJDC7Pe47CI2gm2cTUcT0BW8qRIANGBkyss8aB5mUSQ0oo8X6Uw==
-----END PUBLIC KEY-----
"""
"""Cloud KMS ``nightshift/evidence-signer`` version 1, the delivered signing path.

Byte-identical to the tracked ``keys/kms-evidence-signer.pub.pem``, which was exported
from KMS with ``gcloud kms keys versions get-public-key``. Rotating to version 2 adds a
constant here; it does not orphan a manifest, because a manifest signed by version 1
stays verifiable for as long as version 1's public half is listed.
"""

LOCAL_EVIDENCE_SIGNER_PUB = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE8dNNNQwoSaZPYqRLt/t7pNP+4D7M
sD1IenXs6PfIjjWYkdb5zVy/nYoVeqLNo3uX7KRoWpdmVI/04nNoOQbPiA==
-----END PUBLIC KEY-----
"""
"""The offline fallback signer, so ``make verify-demo`` works with no GCP credentials.

Trusted for the same reason the KMS key is: it is this project's key. Which backend
actually signed a manifest is recorded in the manifest and rendered separately, so a
locally-signed artifact is never presentable as a KMS-signed one.
"""

TRUSTED_PUBLIC_KEYS: tuple[str, ...] = (
    KMS_EVIDENCE_SIGNER_PUB,
    LOCAL_EVIDENCE_SIGNER_PUB,
)


def spki_der(pem: str) -> bytes | None:
    """The DER SubjectPublicKeyInfo bytes of a PEM public key, or ``None``.

    Comparison happens on parsed key material, never on PEM text. A string compare would
    turn a trailing newline, CRLF line endings, or a re-wrapped base64 body into a false
    MISMATCH, and this check runs server-side on every request to ``/verify``.
    """
    if not pem:
        return None
    try:
        key = serialization.load_pem_public_key(pem.encode("ascii"))
    except Exception:
        return None
    if not isinstance(key, ec.EllipticCurvePublicKey):
        return None
    return key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def trusted_spki() -> set[bytes]:
    return {der for der in (spki_der(pem) for pem in TRUSTED_PUBLIC_KEYS) if der is not None}


def _claims_kms_provenance(backend: str, key_ref: str) -> bool:
    """Does this signature block assert that Cloud KMS produced it?"""
    return backend == "cloud-kms" or "/cryptoKeyVersions/" in key_ref


def key_is_pinned(
    public_key_pem: str, *, backend: str = "", key_ref: str = ""
) -> tuple[bool | None, str]:
    """Is this the public half of a key Night Shift actually signs with?

    Three outcomes, because there are genuinely three situations and collapsing them
    would either wave a forgery through or break the credential-free path.

    ``True`` — the key is one of the two published Night Shift signing keys. This is
    every manifest in ``evidence/incidents/``.

    ``False`` — the block claims Cloud KMS provenance but was not signed by the
    published KMS key. This is precisely the reproduced forgery: an edited body,
    re-signed with a generated key, with the real ``key_ref`` string left in place so it
    still reads as ours. A document cannot claim to have been signed by a key that did
    not sign it. Fails the whole verification.

    ``None`` — the signature is self-consistent and claims only local provenance, but
    the key is not one this verifier recognises. That is what a manifest *you* generated
    on your own laptop looks like: ``make incident`` mints a fresh EC key, and refusing
    it outright would mean the offline path produced evidence its own verifier rejects.
    Reported as a check that could not be performed, which yields PARTIAL and never
    PASS.
    """
    der = spki_der(public_key_pem)
    if der is None:
        return False, "signing key is missing or is not a parseable EC public key"
    if der in trusted_spki():
        which = (
            "Cloud KMS evidence-signer v1"
            if der == spki_der(KMS_EVIDENCE_SIGNER_PUB)
            else "offline evidence-signer"
        )
        return True, f"pinned to the published {which} public key"
    if _claims_kms_provenance(backend, key_ref):
        return False, (
            "claims Cloud KMS provenance but is not signed by the published KMS key; "
            "the signature is internally consistent and the signer is not Night Shift"
        )
    return None, (
        "signed by a key this verifier does not publish, claiming only local "
        "provenance — consistent with a manifest generated on this machine, so "
        "provenance is not established rather than disproved"
    )
