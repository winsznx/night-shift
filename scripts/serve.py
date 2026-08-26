"""Container entrypoint. Resolves NIGHTSHIFT_SERVICE to an ASGI app and serves it."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVICES = {
    "telemetry": "services.telemetry.app:app",
    "inventory": "services.inventory.app:app",
    "capacity": "services.capacity.app:app",
    "facilities": "services.facilities.app:app",
    "custody": "services.custody.app:app",
    "incident_control": "services.incident_control.app:app",
    "bff": "apps.api.main:app",
}


def main() -> int:
    import uvicorn

    service = os.environ.get("NIGHTSHIFT_SERVICE", "").strip()
    if service not in SERVICES:
        print(
            f"NIGHTSHIFT_SERVICE={service!r} is not one of {sorted(SERVICES)}",
            file=sys.stderr,
        )
        return 2

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(
        SERVICES[service],
        host="0.0.0.0",  # noqa: S104 - Cloud Run requires binding all interfaces
        port=port,
        log_level=os.environ.get("NIGHTSHIFT_LOG_LEVEL", "info"),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
