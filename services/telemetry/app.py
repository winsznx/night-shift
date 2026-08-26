"""Telemetry Service (PRD §17.1).

Read-only, always. This service has no mutating routes at all, which is the cheapest
possible way to guarantee that the Signal Investigator — the agent that reads the most
raw data — can never change anything.

The five read surfaces are deliberately *different tools with different authority
domains* rather than one `get_telemetry` with a scope parameter, because that is what
lets the Commander hold summary-only access while the Investigator holds full history.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends

from nightshift.common.clock import age_seconds, now_iso, parse_iso
from nightshift.safety_kernel.config import DEFAULT_CONFIG
from services.common.app import create_app, get_repository, require_tool
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="telemetry",
    title="Night Shift — Telemetry Service",
    description="Authoritative read-only freezer telemetry. No mutating routes exist.",
)


def _freezer_payload(repo: Repository, freezer_id: str) -> dict[str, Any]:
    f = repo.get_freezer(freezer_id)
    if f is None:
        return {"freezer_id": freezer_id, "known": False}
    now = now_iso()
    return {
        "freezer_id": f.id,
        "known": True,
        "label": f.label,
        "zone": f.zone,
        "state": f.state.value,
        "current_temp_c": f.current_temp_c,
        "setpoint_c": f.setpoint_c,
        "alarm_high_c": f.alarm_high_c,
        "last_reading_at": f.last_reading_at,
        "reading_age_s": round(age_seconds(f.last_reading_at, now), 1),
        "total_slots": f.total_slots,
        "occupied_slots": f.occupied_slots,
        "free_slots": f.free_slots,
        "is_backup_qualified": f.is_backup_qualified,
        "evaluated_at": now,
        "source": "authoritative",
    }


@app.get("/v1/freezers/{freezer_id}")
async def get_freezer_state(
    freezer_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_freezer_state")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    return _freezer_payload(repo, freezer_id)


@app.get("/v1/freezers/{freezer_id}/window")
async def get_temperature_window(
    freezer_id: str,
    minutes: int = 120,
    _p: AgentPrincipal = Depends(require_tool("get_temperature_window")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Readings over a window, plus the deterministic sustained-warming verdict.

    The verdict is computed here rather than left to the model: "has this been above
    the confirm threshold continuously for the confirm window" is arithmetic, and the
    Investigator's job is to explain *why*, not to decide the arithmetic.
    """
    readings = repo.list_readings(freezer_id)
    now = now_iso()
    cutoff = parse_iso(now).timestamp() - minutes * 60
    window = [r for r in readings if parse_iso(r.recorded_at).timestamp() >= cutoff]

    cfg = DEFAULT_CONFIG
    above = [r for r in window if r.celsius > cfg.confirm_threshold_c]
    sustained_s = 0.0
    if above:
        run_start = above[0].recorded_at
        prev = above[0]
        best = 0.0
        for r in above[1:]:
            gap = age_seconds(prev.recorded_at, r.recorded_at)
            if gap > 900:  # a break in the run
                best = max(best, age_seconds(run_start, prev.recorded_at))
                run_start = r.recorded_at
            prev = r
        sustained_s = max(best, age_seconds(run_start, prev.recorded_at))

    return {
        "freezer_id": freezer_id,
        "window_minutes": minutes,
        "evaluated_at": now,
        "reading_count": len(window),
        "readings": [
            {"id": r.id, "celsius": r.celsius, "recorded_at": r.recorded_at} for r in window
        ],
        "max_celsius": max((r.celsius for r in window), default=None),
        "min_celsius": min((r.celsius for r in window), default=None),
        "latest_celsius": window[-1].celsius if window else None,
        "confirm_threshold_c": cfg.confirm_threshold_c,
        "confirm_sustained_seconds": cfg.confirm_sustained_seconds,
        "sustained_above_threshold_s": round(sustained_s, 1),
        "sustained_warming_confirmed": sustained_s >= cfg.confirm_sustained_seconds,
    }


@app.get("/v1/freezers/{freezer_id}/door-events")
async def get_recent_door_events(
    freezer_id: str,
    hours: int = 6,
    _p: AgentPrincipal = Depends(require_tool("get_recent_door_events")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    now = now_iso()
    cutoff = parse_iso(now).timestamp() - hours * 3600
    events = [
        e for e in repo.list_door_events(freezer_id) if parse_iso(e.opened_at).timestamp() >= cutoff
    ]
    return {
        "freezer_id": freezer_id,
        "hours": hours,
        "evaluated_at": now,
        "events": [e.model_dump(mode="json") for e in events],
        "total_open_seconds": sum(e.duration_s or 0 for e in events),
    }


@app.get("/v1/freezers/{freezer_id}/equipment-history")
async def get_equipment_history(
    freezer_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_equipment_history")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Equipment context only. Contains no study or specimen metadata by construction —
    this is the surface the Dispatch Agent is allowed to see."""
    f = repo.get_freezer(freezer_id)
    if f is None:
        return {"freezer_id": freezer_id, "known": False}
    return {
        "freezer_id": f.id,
        "known": True,
        "model": f.model,
        "zone": f.zone,
        "state": f.state.value,
        "setpoint_c": f.setpoint_c,
        "current_temp_c": f.current_temp_c,
        "maintenance": [m.model_dump(mode="json") for m in f.maintenance],
    }


@app.get("/v1/incidents/{incident_id}/summary")
async def get_incident_telemetry_summary(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_incident_telemetry_summary")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Coarse summary — the Commander's entire telemetry view.

    No reading series, no door events. Enough to know whether the situation is getting
    worse, not enough to substitute for the Investigator's analysis.
    """
    incident = repo.get_incident(incident_id)
    if incident is None:
        return {"incident_id": incident_id, "known": False}
    f = repo.get_freezer(incident.failed_freezer_id)
    if f is None:
        return {"incident_id": incident_id, "known": False}
    now = now_iso()
    return {
        "incident_id": incident_id,
        "known": True,
        "freezer_id": f.id,
        "current_temp_c": f.current_temp_c,
        "setpoint_c": f.setpoint_c,
        "above_alarm_threshold": f.current_temp_c > f.alarm_high_c,
        "reading_age_s": round(age_seconds(f.last_reading_at, now), 1),
        "freezer_state": f.state.value,
        "evaluated_at": now,
    }


@app.get("/v1/backups")
async def get_backup_freezer_state(
    _p: AgentPrincipal = Depends(require_tool("get_backup_freezer_state")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Temperature and capacity headline for backup candidates — the Broker's view."""
    now = now_iso()
    return {
        "evaluated_at": now,
        "freezers": [
            {
                "freezer_id": f.id,
                "current_temp_c": f.current_temp_c,
                "last_reading_at": f.last_reading_at,
                "reading_age_s": round(age_seconds(f.last_reading_at, now), 1),
                "free_slots": f.free_slots,
                "is_backup_qualified": f.is_backup_qualified,
                "state": f.state.value,
            }
            for f in repo.list_freezers()
            if f.is_backup_qualified
        ],
    }


@app.get("/v1/destination-temperature/{freezer_id}")
async def get_destination_temperature(
    freezer_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_destination_temperature")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """The freshest destination reading, with the N4 verdict already computed.

    Returning the verdict alongside the number means the Custody Agent cannot
    accidentally reason its way past a stale reading — and the Custody Service checks
    it again at commit time regardless.
    """
    from nightshift.safety_kernel.invariants import n4_would_hold

    f = repo.get_freezer(freezer_id)
    if f is None:
        return {"freezer_id": freezer_id, "known": False}
    readings = repo.list_readings(freezer_id)
    latest = readings[-1] if readings else None
    temp = latest.celsius if latest else f.current_temp_c
    at = latest.recorded_at if latest else f.last_reading_at
    now = now_iso()
    ok, reason = n4_would_hold(temp, at, now)
    return {
        "freezer_id": freezer_id,
        "known": True,
        "reading_id": latest.id if latest else None,
        "celsius": temp,
        "recorded_at": at,
        "age_s": round(age_seconds(at, now), 1),
        "evaluated_at": now,
        "fresh_and_in_bounds": ok,
        "reason": reason,
        "max_age_s": DEFAULT_CONFIG.destination_temp_max_age_s,
        "ceiling_c": DEFAULT_CONFIG.destination_temp_ceiling_c,
    }
