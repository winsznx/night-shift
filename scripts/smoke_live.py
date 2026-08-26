"""Smoke test the deployed public API.

    uv run python scripts/smoke_live.py [BASE_URL]
"""

from __future__ import annotations

import json
import os
import sys

import httpx

DEFAULT = os.environ.get("NIGHTSHIFT_API_URL", "")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).rstrip("/")
    if not base:
        print("Set NIGHTSHIFT_API_URL or pass a base URL.", file=sys.stderr)
        return 2

    checks = [
        ("meta", "/api/meta"),
        ("overview", "/api/overview"),
        ("fleet", "/api/fleet"),
        ("drills", "/api/drills"),
        ("evidence", "/api/evidence"),
    ]

    failures = 0
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for label, path in checks:
            try:
                response = client.get(f"{base}{path}")
                ok = response.status_code == 200
                detail = ""
                if ok and label == "meta":
                    body = response.json()
                    detail = (
                        f"model={body.get('model_id')} store={body.get('store_backend')} "
                        f"signer={body.get('signer_backend')} env={body.get('deployment_env')}"
                    )
                elif ok and label == "overview":
                    body = response.json()
                    detail = (
                        f"{len(body.get('freezers', []))} freezers, "
                        f"{body.get('total_incidents')} incident(s)"
                    )
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            print(f"  {'PASS' if ok else 'FAIL'}  {label:<10} {path:<20} {detail}")
            failures += 0 if ok else 1

    print()
    print(f"{len(checks) - failures}/{len(checks)} live checks passed against {base}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
