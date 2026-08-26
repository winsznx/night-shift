"""Time handling.

The Safety Kernel never reads a clock — callers pass ``now`` explicitly so a drill and
its replay evaluate identically. This module is the only place that formats or parses
timestamps, so every stored value is the same RFC3339 shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

__all__ = ["FrozenClock", "now_iso", "parse_iso", "to_iso", "age_seconds", "shift_iso"]

_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def to_iso(dt: datetime) -> str:
    """RFC3339 UTC with millisecond precision, always ``Z``-suffixed."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime(_FMT)[:-3] + "Z"


def parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def now_iso() -> str:
    return to_iso(datetime.now(UTC))


def age_seconds(timestamp: str, now: str) -> float:
    """Seconds elapsed from ``timestamp`` to ``now``. Negative if in the future."""
    return (parse_iso(now) - parse_iso(timestamp)).total_seconds()


def shift_iso(timestamp: str, seconds: float) -> str:
    return to_iso(parse_iso(timestamp) + timedelta(seconds=seconds))


class FrozenClock:
    """Deterministic clock for fixtures, drills, and replay.

    Advancing is explicit, so a scenario that depends on 20 minutes passing says so in
    the scenario file rather than sleeping.
    """

    __slots__ = ("_current",)

    def __init__(self, start: str) -> None:
        self._current = parse_iso(start)

    def now(self) -> str:
        return to_iso(self._current)

    def advance(self, seconds: float) -> str:
        self._current += timedelta(seconds=seconds)
        return self.now()

    def peek(self, seconds: float) -> str:
        return to_iso(self._current + timedelta(seconds=seconds))
