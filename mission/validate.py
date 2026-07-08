"""Semantic validation: structure + unit conversion (imperial->SI) + safety caps.

``compile_mission(doc)`` turns a raw Mission IR document into a
``NormalizedMission`` whose every value is SI and safe to execute, or raises
``MissionValidationError`` with a human-readable reason. The LLM lives *outside*
this boundary: a wrong translation still cannot produce a flyable unsafe mission.
"""
from __future__ import annotations

import math
from typing import Any

from mission.ir import (
    FEET_TO_M,
    RESERVED_OPS,
    SDK_SPEED_MAX_MPS,
    SDK_SPEED_MIN_MPS,
    SUPPORTED_OPS,
    NormalizedMission,
    NormalizedStep,
    validate_structure,
)

# Rough altitude the auto-takeoff climbs to; used only for the dead-reckoning
# safety estimate, not for control.
TAKEOFF_EST_ALT_M = 1.0
_EPS = 1e-6


class MissionValidationError(ValueError):
    """Raised when a mission is structurally or semantically invalid/unsafe."""


def compile_mission(doc: dict[str, Any]) -> NormalizedMission:
    """Validate + normalize a raw IR document into an executable mission (SI)."""
    validate_structure(doc)

    imperial = doc.get("units_in", "imperial") == "imperial"
    defaults = doc.get("defaults", {})
    safety = doc.get("safety", {})

    max_alt = safety.get("max_altitude_m")
    geofence = safety.get("geofence_radius_m")
    speed_cap = min(SDK_SPEED_MAX_MPS, safety.get("max_speed_mps", SDK_SPEED_MAX_MPS))

    default_threshold_m = float(defaults.get("threshold_m", 0.05))
    default_hold_s = float(defaults.get("hold_time_s", 0.0))
    default_speed_mps = defaults.get("speed_mps")

    warnings: list[str] = []

    def dist(v: float) -> float:
        return float(v) * FEET_TO_M if imperial else float(v)

    def speed(v: float) -> float:
        return float(v) * FEET_TO_M if imperial else float(v)

    def clamp_speed(mps: float, where: str) -> float:
        c = min(max(mps, SDK_SPEED_MIN_MPS), speed_cap)
        if abs(c - mps) > 1e-4:
            warnings.append(f"{where}: speed {mps:.3f} m/s clamped to {c:.3f} m/s")
        return c

    def resolve_leg_speed(step: dict[str, Any], where: str) -> float | None:
        if "speed" in step:
            return clamp_speed(speed(step["speed"]), where)
        if default_speed_mps is not None:
            return clamp_speed(float(default_speed_mps), f"{where} (default)")
        return None

    steps: list[NormalizedStep] = []
    for i, raw in enumerate(doc["steps"]):
        op = raw["op"]
        where = f"step {i + 1} ({op})"

        if op in RESERVED_OPS:
            raise MissionValidationError(
                f"{where}: not supported in v1 — {RESERVED_OPS[op]}"
            )
        if op not in SUPPORTED_OPS:
            raise MissionValidationError(f"{where}: unknown op '{op}'")

        if op in ("arm", "disarm", "takeoff", "land"):
            ns = NormalizedStep(op=op, describe=op)

        elif op == "set_speed":
            mps = clamp_speed(speed(raw["speed"]), where)
            ns = NormalizedStep(op=op, speed_mps=mps, describe=f"set speed {mps:.2f} m/s")

        elif op == "yaw_turn":
            rad = math.radians(float(raw["degrees"]))
            ns = NormalizedStep(
                op=op, delta_yaw_rad=rad,
                describe=f"yaw {float(raw['degrees']):+.0f}deg",
            )

        elif op == "hover":
            secs = float(raw["seconds"])
            ns = NormalizedStep(op=op, hold_time_s=secs, describe=f"hover {secs:g} s")

        elif op in ("goto_relative", "climb"):
            down_m = _vertical_to_down(raw, dist)
            fwd = dist(raw.get("forward", 0.0)) if op == "goto_relative" else 0.0
            rgt = dist(raw.get("right", 0.0)) if op == "goto_relative" else 0.0
            thr = dist(raw["threshold"]) if "threshold" in raw else default_threshold_m
            hold = float(raw["hold"]) if "hold" in raw else default_hold_s
            ns = NormalizedStep(
                op="goto_relative",
                forward_m=fwd, right_m=rgt, down_m=down_m,
                speed_mps=resolve_leg_speed(raw, where),
                threshold_m=thr, hold_time_s=hold,
                describe=_describe_move(fwd, rgt, down_m, hold),
            )
        else:  # pragma: no cover - guarded by schema + checks above
            raise MissionValidationError(f"{where}: unhandled op '{op}'")

        steps.append(ns)

    _enforce_safety(steps, max_alt, geofence)

    return NormalizedMission(
        name=doc.get("name", "mission"),
        steps=steps,
        max_altitude_m=max_alt,
        geofence_radius_m=geofence,
        max_speed_mps=speed_cap,
        warnings=warnings,
    )


def _vertical_to_down(raw: dict[str, Any], dist) -> float:
    if "up" in raw and "down" in raw:
        raise MissionValidationError("a move cannot set both 'up' and 'down'")
    if "up" in raw:
        return -dist(raw["up"])  # NED: up is negative down
    if "down" in raw:
        return dist(raw["down"])
    return 0.0


def _describe_move(fwd: float, rgt: float, down_m: float, hold: float) -> str:
    parts = []
    if abs(fwd) > _EPS:
        parts.append(f"{'fwd' if fwd > 0 else 'back'} {abs(fwd):.2f} m")
    if abs(rgt) > _EPS:
        parts.append(f"{'right' if rgt > 0 else 'left'} {abs(rgt):.2f} m")
    if abs(down_m) > _EPS:
        parts.append(f"{'up' if down_m < 0 else 'down'} {abs(down_m):.2f} m")
    if not parts:
        parts.append("hold position")
    desc = "move " + ", ".join(parts)
    if hold > _EPS:
        desc += f" (hold {hold:g} s)"
    return desc


def _enforce_safety(
    steps: list[NormalizedStep],
    max_alt: float | None,
    geofence: float | None,
) -> None:
    """Dead-reckon the mission pose and reject cap violations before flight."""
    x = y = z = yaw = 0.0  # world NED-ish; altitude_up = -z
    for i, s in enumerate(steps):
        where = f"step {i + 1} ({s.op})"
        if s.op == "takeoff":
            z = min(z, -TAKEOFF_EST_ALT_M)
        elif s.op == "land":
            z = 0.0
        elif s.op == "yaw_turn":
            yaw += s.delta_yaw_rad
        elif s.op == "goto_relative":
            x += s.forward_m * math.cos(yaw) - s.right_m * math.sin(yaw)
            y += s.forward_m * math.sin(yaw) + s.right_m * math.cos(yaw)
            z += s.down_m

        alt_up = -z
        if max_alt is not None and alt_up > max_alt + _EPS:
            raise MissionValidationError(
                f"{where}: altitude ~{alt_up:.1f} m exceeds max_altitude_m {max_alt:.1f} m"
            )
        horiz = math.hypot(x, y)
        if geofence is not None and horiz > geofence + _EPS:
            raise MissionValidationError(
                f"{where}: horizontal ~{horiz:.1f} m exceeds geofence_radius_m {geofence:.1f} m"
            )


def preview(mission: NormalizedMission) -> list[str]:
    """Human-readable, one-line-per-step preview for the confirm screen."""
    lines = [f"Mission: {mission.name}"]
    caps = []
    if mission.max_altitude_m is not None:
        caps.append(f"max alt {mission.max_altitude_m:g} m")
    if mission.geofence_radius_m is not None:
        caps.append(f"geofence {mission.geofence_radius_m:g} m")
    caps.append(f"max speed {mission.max_speed_mps:g} m/s")
    lines.append("Safety: " + ", ".join(caps))
    for i, s in enumerate(mission.steps):
        lines.append(f"  {i + 1:>2}. {s.describe}")
    for w in mission.warnings:
        lines.append(f"  ! {w}")
    return lines
