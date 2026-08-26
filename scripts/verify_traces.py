"""Confirm Night Shift spans actually reached Cloud Trace, and record what was found.

PRD §30 asks for trace IDs a judge can follow into Cloud Trace. Emitting spans and
exporting them are different things: a misconfigured exporter fails silently by design,
because tracing must never take down a rescue. So the only honest way to claim the
export works is to read the spans back out of Cloud Trace.

    uv run python scripts/verify_traces.py [--hours 3]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.clock import now_iso
from nightshift.common.config import get_settings

ROOT = Path(__file__).resolve().parents[1]

# Spans Night Shift creates itself. Domain-service HTTP routes also appear in Cloud
# Trace, but those could come from any FastAPI app; these names are ours.
NIGHTSHIFT_SPAN_PREFIXES = ("incident.", "effect.", "tool.", "agent.", "invocation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=3.0)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.project_id:
        print("no project configured")
        return 1

    from google.cloud import trace_v1

    client = trace_v1.TraceServiceClient()
    end = datetime.datetime.now(datetime.UTC)
    start = end - datetime.timedelta(hours=args.hours)

    counts: dict[str, int] = {}
    trace_ids: list[str] = []
    total = 0
    for trace in client.list_traces(
        request=trace_v1.ListTracesRequest(
            project_id=settings.project_id,
            start_time=start,
            end_time=end,
            view=trace_v1.ListTracesRequest.ViewType.COMPLETE,
        )
    ):
        total += 1
        ours = False
        for sp in trace.spans:
            if sp.name.startswith(NIGHTSHIFT_SPAN_PREFIXES):
                counts[sp.name] = counts.get(sp.name, 0) + 1
                ours = True
        if ours and len(trace_ids) < 25:
            trace_ids.append(trace.trace_id)
        if total >= 500:
            break

    document: dict[str, Any] = {
        "generated_at": now_iso(),
        "project": settings.project_id,
        "window_hours": args.hours,
        "traces_examined": total,
        "nightshift_traces": len(trace_ids),
        "span_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "sample_trace_ids": trace_ids,
        "console_url_template": (
            f"https://console.cloud.google.com/traces/list?project={settings.project_id}"
        ),
        "exported": bool(counts),
        "note": (
            "Span names listed here are created by Night Shift itself, not by the web "
            "framework, so their presence shows our instrumentation reached Cloud Trace "
            "rather than that something served HTTP."
        ),
    }
    out = ROOT / "evidence" / "traces.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"examined {total} trace(s) in the last {args.hours}h")
    print(f"Night Shift traces: {len(trace_ids)}")
    for name, count in list(document["span_counts"].items())[:12]:
        print(f"  {count:>5}  {name}")
    print(f"\nexported: {document['exported']}")
    print(f"written to {out.relative_to(ROOT)}")
    return 0 if document["exported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
