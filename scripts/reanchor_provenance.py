"""Re-anchor published evidence onto rewritten commit SHAs, and re-sign it.

Every manifest records the ``source_commit`` it was produced from, so a reader can walk
from a signed artifact back to the exact tree that made it. Rewriting history — as
correcting commit authorship does — changes every SHA while leaving every tree byte
identical, which silently turns that pointer into a dead reference.

Rewriting the field alone is not enough: the commit is inside the signed body, so the
signature must be recomputed or the manifest verifies as tampered. That is the honest
outcome, and the fix is to re-sign with the same key rather than to weaken the check.

This translates old SHAs to new ones using a mapping produced from the two histories,
and re-signs each manifest. It refuses to invent a mapping it was not given: an
unrecognised commit is reported and left alone.

    uv run python scripts/reanchor_provenance.py --map old-to-new.tsv [--dry-run]

The mapping file is two whitespace-separated columns, ``<old-sha> <new-sha>``, as
produced by walking both histories in reverse:

    paste <(git rev-list --reverse <old-ref>) <(git rev-list --reverse <new-ref>)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.canonical import canonical_bytes
from nightshift.evidence.signing import get_signer

ROOT = Path(__file__).resolve().parents[1]


def load_map(path: Path) -> dict[str, str]:
    """Read the SHA mapping, indexed by every prefix length the evidence might use."""
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        old, new = parts
        # Evidence records commits at several abbreviation lengths, so index them all
        # rather than guessing which one a given file happened to store.
        for length in range(7, len(old) + 1):
            mapping[old[:length]] = new[:length]
    return mapping


def translate(value: str, mapping: dict[str, str]) -> tuple[str, bool]:
    new = mapping.get(value)
    return (new, True) if new else (value, False)


def reanchor_manifest(path: Path, mapping: dict[str, str], dry_run: bool) -> str:
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    old_commit = str(manifest.get("source_commit") or "")
    new_commit, found = translate(old_commit, mapping)

    if not old_commit:
        return f"  {path.name}: no source_commit, skipped"
    if not found:
        return f"  {path.name}: source_commit {old_commit} not in the map, LEFT ALONE"
    if new_commit == old_commit:
        return f"  {path.name}: already anchored at {old_commit}"
    if dry_run:
        return f"  {path.name}: would re-anchor {old_commit} -> {new_commit} and re-sign"

    body = {k: v for k, v in manifest.items() if k != "signature"}
    body["source_commit"] = new_commit

    signer = get_signer()
    signature = signer.sign(canonical_bytes(body))
    signed = {**body, "signature": signature.as_dict()}

    path.write_text(json.dumps(signed, indent=2), encoding="utf-8")
    # The sidecar and public key travel with the manifest and are checked independently,
    # so leaving either at the old signature would fail verification for the honest
    # reason that they no longer describe this body.
    sidecar = path.with_suffix(path.suffix + ".sig")
    if sidecar.exists() or True:
        sidecar.write_text(json.dumps(signature.as_dict(), indent=2), encoding="utf-8")
    if signature.public_key_pem:
        stem = path.name.replace(".manifest.json", "")
        (path.parent / f"{stem}.pub.pem").write_text(signature.public_key_pem, encoding="utf-8")
    return f"  {path.name}: re-anchored {old_commit} -> {new_commit}, re-signed ({signer.backend})"


def reanchor_json_field(path: Path, mapping: dict[str, str], dry_run: bool) -> str:
    """Rewrite commit references in an unsigned JSON artifact."""
    raw = path.read_text(encoding="utf-8")
    replaced = 0
    for old, new in mapping.items():
        if old in raw:
            raw = raw.replace(old, new)
            replaced += 1
    if not replaced:
        return f"  {path.name}: no commit references"
    if dry_run:
        return f"  {path.name}: would rewrite {replaced} commit reference(s)"
    path.write_text(raw, encoding="utf-8")
    return f"  {path.name}: rewrote {replaced} commit reference(s)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path, help="old<TAB>new SHA mapping")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mapping = load_map(args.map)
    if not mapping:
        print("ERROR: mapping file produced no entries", file=sys.stderr)
        return 1
    print(f"Loaded {len(mapping)} SHA prefix mappings\n")

    print("Signed manifests (re-signed):")
    for manifest_path in sorted((ROOT / "evidence" / "incidents").glob("*.manifest.json")):
        print(reanchor_manifest(manifest_path, mapping, args.dry_run))

    print("\nUnsigned artifacts:")
    for name in ("evidence/qualification.json",):
        path = ROOT / name
        if path.exists():
            print(reanchor_json_field(path, mapping, args.dry_run))

    print("\nRegenerate docs/CLAIMS.json and README.md from the current tree afterwards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
