"""python -m nightshift.verify --manifest <url-or-path>

Verifies an incident manifest with no model and no Google Cloud credentials.
Exit code 0 for PASS, 1 for MISMATCH, 2 for PARTIAL.
"""

from __future__ import annotations

import argparse
import json
import sys

from nightshift.verify.verifier import (
    VerificationStatus,
    verify_manifest_file,
    verify_manifest_url,
)

_EXIT = {
    VerificationStatus.PASS: 0,
    VerificationStatus.MISMATCH: 1,
    VerificationStatus.PARTIAL: 2,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nightshift.verify",
        description=(
            "Independently verify a Night Shift incident manifest. Recomputes the hard "
            "verdict from the stored state snapshot using the same Safety Kernel the "
            "production services used. Requires no model and no GCP credentials."
        ),
    )
    parser.add_argument("--manifest", required=True, help="URL or filesystem path")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    target = args.manifest
    result = (
        verify_manifest_url(target)
        if target.startswith(("http://", "https://"))
        else verify_manifest_file(target)
    )

    print(json.dumps(result.as_dict(), indent=2) if args.json else result.render())
    return _EXIT[result.status]


if __name__ == "__main__":
    sys.exit(main())
