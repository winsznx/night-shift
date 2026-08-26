"""Verify every published manifest. Needs no credentials and no model.

    uv run python scripts/verify_all.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.verify.verifier import VerificationStatus, verify_manifest_file  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    directory = ROOT / "evidence" / "incidents"
    manifests = sorted(directory.glob("*.manifest.json")) if directory.exists() else []

    if not manifests:
        print("No manifests found in evidence/incidents/.")
        print("Run `make seed-demo` (needs GCP) or `make incident` to produce one.")
        return 0

    worst = 0
    for path in manifests:
        result = verify_manifest_file(path)
        print(result.render())
        print()
        if result.status is VerificationStatus.MISMATCH:
            worst = max(worst, 1)
        elif result.status is VerificationStatus.PARTIAL:
            worst = max(worst, 2)

    passed = sum(
        1 for p in manifests if verify_manifest_file(p).status is VerificationStatus.PASS
    )
    print(f"{passed}/{len(manifests)} manifest(s) verified PASS.")
    return worst


if __name__ == "__main__":
    sys.exit(main())
