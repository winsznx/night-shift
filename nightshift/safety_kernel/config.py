"""Kernel thresholds.

These are policy constants, not tuning knobs an agent may argue with. They are part of
the manifest so a verifier reproduces the same verdict with the same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KernelConfig:
    destination_temp_max_age_s: int = 900
    """N4: destination temperature evidence older than this cannot support a commit."""

    destination_temp_ceiling_c: float = -60.0
    """N4: a destination warmer than this is unsafe for ULT specimen transfer."""

    destination_temp_floor_c: float = -95.0
    """N4: implausibly cold readings indicate a broken sensor, not a safe destination."""

    confirm_sustained_seconds: int = 600
    """Sustained warming window that distinguishes failure from a door excursion."""

    confirm_threshold_c: float = -60.0
    """Above this for the sustained window, the freezer is treated as failing."""

    recovery_validation_seconds: int = 1800
    """N13/D18: how long a repaired freezer must hold setpoint before the hold releases."""

    recovery_validation_ceiling_c: float = -70.0
    """Temperature a recovering freezer must stay below throughout validation."""

    max_tool_calls_per_incident: int = 240
    """Agent loop guard (threat model §31)."""

    max_wall_clock_seconds: int = 900
    """Agent loop guard (threat model §31)."""

    max_model_calls_per_drill: int = 60
    """Per-drill model budget (cost + abuse control)."""

    def as_dict(self) -> dict[str, float | int]:
        return {
            "destination_temp_max_age_s": self.destination_temp_max_age_s,
            "destination_temp_ceiling_c": self.destination_temp_ceiling_c,
            "destination_temp_floor_c": self.destination_temp_floor_c,
            "confirm_sustained_seconds": self.confirm_sustained_seconds,
            "confirm_threshold_c": self.confirm_threshold_c,
            "recovery_validation_seconds": self.recovery_validation_seconds,
            "recovery_validation_ceiling_c": self.recovery_validation_ceiling_c,
            "max_tool_calls_per_incident": self.max_tool_calls_per_incident,
            "max_wall_clock_seconds": self.max_wall_clock_seconds,
            "max_model_calls_per_drill": self.max_model_calls_per_drill,
        }


DEFAULT_CONFIG = KernelConfig()
