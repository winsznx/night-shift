"""Manifest signing.

Cloud KMS asymmetric signing is the delivered path. A local EC key is the offline
fallback so ``make verify-demo`` works with no GCP credentials at all — and the two
produce the same ECDSA P-256 / SHA-256 signature format, so the verifier does not care
which one signed a manifest as long as it can find the matching public key.

Which backend actually signed a given manifest is recorded *in* the manifest, so nobody
can mistake a locally-signed artifact for a KMS-signed one.
"""

from __future__ import annotations

import base64
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from nightshift.common.config import Settings, get_settings

SIGNATURE_ALGORITHM = "EC_SIGN_P256_SHA256"


@dataclass(frozen=True)
class Signature:
    algorithm: str
    backend: str
    key_ref: str
    signature_b64: str
    public_key_pem: str
    digest_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "backend": self.backend,
            "key_ref": self.key_ref,
            "signature_b64": self.signature_b64,
            "public_key_pem": self.public_key_pem,
            "digest_sha256": self.digest_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signature:
        return cls(
            algorithm=data["algorithm"],
            backend=data["backend"],
            key_ref=data["key_ref"],
            signature_b64=data["signature_b64"],
            public_key_pem=data["public_key_pem"],
            digest_sha256=data["digest_sha256"],
        )


class Signer(ABC):
    backend: str

    @abstractmethod
    def sign(self, payload: bytes) -> Signature: ...

    @abstractmethod
    def public_key_pem(self) -> str: ...


class NullSigner(Signer):
    """No signature available. The manifest still hashes; it just is not signed.

    Used only when neither KMS nor a local key is reachable. The verifier reports
    ``PARTIAL`` for such a manifest rather than pretending it verified.
    """

    backend = "none"

    def sign(self, payload: bytes) -> Signature:
        return Signature(
            algorithm="none",
            backend="none",
            key_ref="",
            signature_b64="",
            public_key_pem="",
            digest_sha256=hashlib.sha256(payload).hexdigest(),
        )

    def public_key_pem(self) -> str:
        return ""


class LocalSigner(Signer):
    """ECDSA P-256 over a locally generated key.

    The private key lives in ``keys/`` (gitignored). The public key is committed so a
    clean clone can verify the published reference manifest without credentials.
    """

    backend = "local-ec-p256"

    def __init__(self, key_dir: Path) -> None:
        self._key_dir = key_dir
        self._private_path = key_dir / "evidence-signer.key.pem"
        self._public_path = key_dir / "evidence-signer.pub.pem"
        self._private = self._load_or_create()

    def _load_or_create(self) -> ec.EllipticCurvePrivateKey:
        if self._private_path.exists():
            loaded = serialization.load_pem_private_key(
                self._private_path.read_bytes(), password=None
            )
            if not isinstance(loaded, ec.EllipticCurvePrivateKey):
                raise TypeError("local signing key is not an EC private key")
            return loaded

        key = ec.generate_private_key(ec.SECP256R1())
        self._key_dir.mkdir(parents=True, exist_ok=True)
        self._private_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self._private_path.chmod(0o600)
        self._public_path.write_bytes(self._public_bytes(key))
        return key

    @staticmethod
    def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
        return key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def public_key_pem(self) -> str:
        return self._public_bytes(self._private).decode("ascii")

    def sign(self, payload: bytes) -> Signature:
        digest = hashlib.sha256(payload).digest()
        raw = self._private.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
        return Signature(
            algorithm=SIGNATURE_ALGORITHM,
            backend=self.backend,
            key_ref=str(self._public_path.name),
            signature_b64=base64.b64encode(raw).decode("ascii"),
            public_key_pem=self.public_key_pem(),
            digest_sha256=digest.hex(),
        )


class KmsSigner(Signer):
    """Cloud KMS asymmetric signing (PRD §28). The delivered production path."""

    backend = "cloud-kms"

    def __init__(self, key_version: str) -> None:
        from google.cloud import kms

        self._key_version = key_version
        self._client = kms.KeyManagementServiceClient()
        self._public_pem: str | None = None

    def public_key_pem(self) -> str:
        if self._public_pem is None:
            self._public_pem = self._client.get_public_key(request={"name": self._key_version}).pem
        return self._public_pem

    def sign(self, payload: bytes) -> Signature:
        digest = hashlib.sha256(payload).digest()
        response = self._client.asymmetric_sign(
            request={"name": self._key_version, "digest": {"sha256": digest}}
        )
        return Signature(
            algorithm=SIGNATURE_ALGORITHM,
            backend=self.backend,
            key_ref=self._key_version,
            signature_b64=base64.b64encode(response.signature).decode("ascii"),
            public_key_pem=self.public_key_pem(),
            digest_sha256=digest.hex(),
        )


def get_signer(settings: Settings | None = None) -> Signer:
    """Pick a backend. ``auto`` prefers KMS and falls back loudly, never silently."""
    settings = settings or get_settings()
    choice = settings.signer_backend

    if choice == "none":
        return NullSigner()
    if choice == "local":
        return LocalSigner(settings.keys_dir)
    if choice == "kms":
        return KmsSigner(settings.kms_key)

    if settings.kms_key:
        try:
            signer = KmsSigner(settings.kms_key)
            signer.public_key_pem()  # prove the key is reachable before committing to it
            return signer
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Cloud KMS signer unavailable (%s); falling back to the local signing key. "
                "This is recorded in the manifest as backend=local-ec-p256.",
                exc,
            )
    return LocalSigner(settings.keys_dir)


def verify_signature(payload: bytes, signature: Signature) -> tuple[bool, str]:
    """Verify a detached signature against ``payload``.

    Returns ``(ok, reason)``. Requires no model and no network — the public key travels
    inside the manifest and can also be checked against the published KMS key.
    """
    digest = hashlib.sha256(payload).hexdigest()
    if signature.algorithm == "none":
        return False, "manifest is unsigned"
    if digest != signature.digest_sha256:
        return False, (
            f"payload digest {digest[:16]}… does not match the signed digest "
            f"{signature.digest_sha256[:16]}…"
        )
    if not signature.public_key_pem:
        return False, "no public key accompanies the signature"

    try:
        public_key = serialization.load_pem_public_key(signature.public_key_pem.encode("ascii"))
    except Exception as exc:
        return False, f"public key could not be parsed: {exc}"
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        return False, "public key is not an EC key"

    try:
        public_key.verify(
            base64.b64decode(signature.signature_b64),
            bytes.fromhex(signature.digest_sha256),
            ec.ECDSA(Prehashed(hashes.SHA256())),
        )
    except InvalidSignature:
        return False, "signature does not verify against the public key"
    except Exception as exc:
        return False, f"signature verification error: {exc}"
    return True, ""
