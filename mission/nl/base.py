"""Shared types + defaults for NL compilers."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# Default mission-level values injected when the NL text doesn't specify them.
# max_altitude_m ~120 m (≈400 ft) keeps the "up 100 ft" (30.5 m) example valid.
DEFAULT_SAFETY: dict[str, float] = {
    "max_altitude_m": 120.0,
    "geofence_radius_m": 100.0,
    "max_speed_mps": 0.75,
}
DEFAULT_DEFAULTS: dict[str, float] = {
    "speed_mps": 0.35,
    "threshold_m": 0.15,
    "hold_time_s": 0.5,
}
# Hover with no stated duration.
DEFAULT_HOVER_S = 10.0


class NLCompileError(ValueError):
    """Raised when English cannot be turned into Mission IR."""


@runtime_checkable
class NLCompiler(Protocol):
    """Turns an English mission description into a Mission IR document (dict).

    Implementations must return a *structurally* plausible IR doc; they need not
    enforce safety — that is mission.validate.compile_mission's job.
    """

    def compile(self, text: str) -> dict[str, Any]: ...
