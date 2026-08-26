"""Canonical JSON serialization and hashing.

Everything the verifier recomputes flows through here. The rules are deliberately
boring and stable so a manifest produced today hashes identically a year from now on a
different machine:

* object keys sorted lexicographically by their UTF-8 code points
* no insignificant whitespace
* UTF-8 output, no ASCII escaping beyond what JSON requires
* floats rendered through ``repr`` shortest-roundtrip, with ``-0.0`` normalized to ``0.0``
* non-finite floats rejected rather than silently becoming ``NaN``/``Infinity``
* enums serialize as their value, Pydantic models as their canonical dict
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel

__all__ = [
    "canonical_bytes",
    "canonical_json",
    "canonicalize",
    "sha256_bytes",
    "sha256_hex",
    "sha256_of",
]


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented deterministically."""


def canonicalize(value: Any) -> Any:
    """Reduce ``value`` to the JSON-native subset we are willing to hash."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(f"non-finite float is not canonicalizable: {value!r}")
        # -0.0 and 0.0 must not produce different hashes.
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                if isinstance(k, Enum) and isinstance(k.value, str):
                    k = k.value
                else:
                    raise CanonicalizationError(f"non-string mapping key: {k!r}")
            if k in out:
                raise CanonicalizationError(f"duplicate key after normalization: {k!r}")
            out[k] = canonicalize(v)
        return {k: out[k] for k in sorted(out)}
    if isinstance(value, (set, frozenset)):
        # Sets have no inherent order; sort their canonical forms by encoded bytes.
        items = [canonicalize(v) for v in value]
        return sorted(items, key=lambda x: canonical_bytes(x))
    if isinstance(value, Sequence):
        return [canonicalize(v) for v in value]
    raise CanonicalizationError(f"unsupported type for canonical JSON: {type(value).__name__}")


def _encode(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_encode_float(value))
    elif isinstance(value, str):
        out.append(_encode_string(value))
    elif isinstance(value, list):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for i, key in enumerate(value):
            if i:
                out.append(",")
            out.append(_encode_string(key))
            out.append(":")
            _encode(value[key], out)
        out.append("}")
    else:  # pragma: no cover - canonicalize() already narrowed the type
        raise CanonicalizationError(f"unexpected canonical type {type(value).__name__}")


def _encode_float(value: float) -> str:
    if value == int(value) and abs(value) < 1e16:
        return f"{int(value)}.0"
    return repr(value)


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _encode_string(value: str) -> str:
    parts = ['"']
    for ch in value:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            parts.append(esc)
        elif ch < "\x20":
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def canonical_json(value: Any) -> str:
    """Canonical JSON text for ``value``."""
    out: list[str] = []
    _encode(canonicalize(value), out)
    return "".join(out)


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes for ``value`` — the exact input to every hash we publish."""
    return canonical_json(value).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of(value: Any) -> str:
    """SHA-256 over the canonical JSON encoding of ``value``."""
    return sha256_bytes(canonical_bytes(value))


def sha256_hex(*parts: str) -> str:
    """SHA-256 over ``parts`` joined by ``|``.

    Used for semantic action IDs, where the input is an ordered tuple of opaque
    identifier strings rather than a structured document.
    """
    for p in parts:
        if "|" in p:
            raise CanonicalizationError(f"action id component must not contain '|': {p!r}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
