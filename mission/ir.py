"""Mission IR: schema location, JSON loading, and normalized (SI) data model.

Structure validation lives here (JSON Schema). Semantic validation — unit
conversion, safety caps, and rejecting reserved perception ops — lives in
mission/validate.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- unit constants ---------------------------------------------------------
FEET_TO_M = 0.3048

# --- SDK constraints --------------------------------------------------------
SDK_SPEED_MIN_MPS = 0.05
SDK_SPEED_MAX_MPS = 0.75

# --- vocabulary -------------------------------------------------------------
# Ops the M0 executor can actually fly.
SUPPORTED_OPS: frozenset[str] = frozenset(
    {
        "arm",
        "disarm",
        "set_speed",
        "takeoff",
        "land",
        "goto_relative",
        "climb",
        "yaw_turn",
        "hover",
    }
)
# Ops reserved in the grammar but not flyable yet (need M2/M3 work). The
# validator rejects these with a clear reason.
RESERVED_OPS: dict[str, str] = {
    "return_to_start": "return_to_start needs absolute-pose tracking (M2)",
    "goto_target": "goto_target needs perception (M3)",
    "hover_in_front_of": "hover_in_front_of needs perception (M3)",
    "goto_top_of": "goto_top_of needs perception (M3)",
}

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "mission-control"
    / "mission-ir.schema.json"
)


def load_schema() -> dict[str, Any]:
    """Load the Mission IR JSON Schema."""
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)


def load_mission_file(path: str | Path) -> dict[str, Any]:
    """Load a raw Mission IR document from a JSON file (no validation)."""
    with Path(path).open() as fh:
        return json.load(fh)


def validate_structure(doc: dict[str, Any]) -> None:
    """Validate document structure against the JSON Schema.

    Raises jsonschema.ValidationError on the first structural problem.
    """
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.path) or "<root>"
        raise first.__class__(f"IR structure invalid at {loc}: {first.message}")


# --- normalized (post-validation, SI-unit) model ----------------------------
@dataclass
class NormalizedStep:
    """One executable step, fully resolved to SI units.

    Fields used depend on ``op`` (see docs/mission-control/mission-ir.md):
      - set_speed:     speed_mps
      - goto_relative: forward_m, right_m, down_m, speed_mps?, threshold_m, hold_time_s
      - climb:         down_m, speed_mps?, hold_time_s
      - yaw_turn:      delta_yaw_rad
      - hover:         hold_time_s
      - arm/disarm/takeoff/land: no extra fields
    """

    op: str
    forward_m: float = 0.0
    right_m: float = 0.0
    down_m: float = 0.0
    speed_mps: float | None = None
    threshold_m: float = 0.05
    hold_time_s: float = 0.0
    delta_yaw_rad: float = 0.0
    # human-readable one-line description, filled by the validator for preview
    describe: str = ""


@dataclass
class NormalizedMission:
    """A validated mission, ready to execute. All values are SI."""

    name: str
    steps: list[NormalizedStep]
    max_altitude_m: float | None = None
    geofence_radius_m: float | None = None
    max_speed_mps: float = SDK_SPEED_MAX_MPS
    warnings: list[str] = field(default_factory=list)
