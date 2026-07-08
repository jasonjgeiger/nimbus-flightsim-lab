#!/usr/bin/env python3
"""Standalone self-test for the mission package (no pytest needed).

    .venv/bin/python -m mission.selftest

Covers: unit conversion, safety-cap rejection, reserved-op rejection, structural
rejection, and a full dry-run execution. Exits non-zero on any failure.
"""
from __future__ import annotations

import math

from mission.executor import DryRunClient, MissionExecutor
from mission.ir import FEET_TO_M
from mission.nl import RuleBasedCompiler
from mission.validate import MissionValidationError, compile_mission


def _expect_reject(doc: dict, needle: str) -> None:
    try:
        compile_mission(doc)
    except (MissionValidationError, Exception) as exc:  # noqa: BLE001
        assert needle in str(exc), f"expected '{needle}' in error, got: {exc}"
        return
    raise AssertionError(f"expected rejection containing '{needle}', but it passed")


def test_unit_conversion() -> None:
    m = compile_mission(
        {
            "version": 1,
            "units_in": "imperial",
            "steps": [
                {"op": "goto_relative", "forward": 20, "up": 100},
                {"op": "yaw_turn", "degrees": 90},
            ],
        }
    )
    leg = m.steps[0]
    assert abs(leg.forward_m - 20 * FEET_TO_M) < 1e-9, leg.forward_m
    assert abs(leg.down_m - (-100 * FEET_TO_M)) < 1e-9, leg.down_m  # up -> negative down
    assert abs(m.steps[1].delta_yaw_rad - math.radians(90)) < 1e-9


def test_si_passthrough() -> None:
    m = compile_mission(
        {"version": 1, "units_in": "si", "steps": [{"op": "goto_relative", "forward": 5}]}
    )
    assert abs(m.steps[0].forward_m - 5.0) < 1e-9


def test_speed_clamped() -> None:
    m = compile_mission(
        {"version": 1, "units_in": "si", "steps": [{"op": "set_speed", "speed": 10.0}]}
    )
    assert m.steps[0].speed_mps == 0.75, m.steps[0].speed_mps
    assert any("clamped" in w for w in m.warnings), m.warnings


def test_altitude_cap() -> None:
    _expect_reject(
        {
            "version": 1,
            "units_in": "si",
            "safety": {"max_altitude_m": 10.0},
            "steps": [{"op": "takeoff"}, {"op": "climb", "up": 30}],
        },
        "max_altitude_m",
    )


def test_geofence_cap() -> None:
    _expect_reject(
        {
            "version": 1,
            "units_in": "si",
            "safety": {"geofence_radius_m": 5.0},
            "steps": [{"op": "goto_relative", "forward": 20}],
        },
        "geofence_radius_m",
    )


def test_reserved_ops_rejected() -> None:
    for op in ("return_to_start", "goto_target", "hover_in_front_of", "goto_top_of"):
        step = {"op": op}
        if op in ("goto_target", "goto_top_of"):
            step["target"] = "tree"
        if op == "hover_in_front_of":
            step.update(target="tree", distance=3, seconds=5)
        _expect_reject({"version": 1, "steps": [step]}, "not supported in v1")


def test_structural_rejection() -> None:
    _expect_reject({"version": 1, "steps": [{"op": "barrel_roll"}]}, "structure invalid")
    _expect_reject({"version": 1, "steps": [{"op": "arm", "x": 1}]}, "structure invalid")
    _expect_reject(
        {"version": 1, "steps": [{"op": "goto_relative", "up": 1, "down": 1}]},
        "structure invalid",
    )


def test_geofence_respects_yaw() -> None:
    # forward 4 then yaw 180 then forward 4 returns near origin -> within a tight fence
    m = compile_mission(
        {
            "version": 1,
            "units_in": "si",
            "safety": {"geofence_radius_m": 5.0},
            "steps": [
                {"op": "goto_relative", "forward": 4},
                {"op": "yaw_turn", "degrees": 180},
                {"op": "goto_relative", "forward": 4},
            ],
        }
    )
    assert len(m.steps) == 3


def test_nl_rule_example_a() -> None:
    ir = RuleBasedCompiler().compile("Fly forward 20 ft, then go up 100 ft and hover.")
    assert ir["units_in"] == "imperial"
    ops = [s["op"] for s in ir["steps"]]
    assert ops == ["arm", "takeoff", "goto_relative", "climb", "hover", "land", "disarm"]
    m = compile_mission(ir)  # must validate + convert cleanly
    assert abs(m.steps[3].down_m - (-100 * FEET_TO_M)) < 1e-6


def test_nl_rule_metric_and_yaw() -> None:
    ir = RuleBasedCompiler().compile(
        "take off, fly forward 5 meters, turn left 90 degrees, hover for 5 seconds, land"
    )
    assert ir["units_in"] == "si"
    yaw = next(s for s in ir["steps"] if s["op"] == "yaw_turn")
    assert yaw["degrees"] == -90.0  # left is negative
    compile_mission(ir)


def test_nl_rule_perception_rejected() -> None:
    ir = RuleBasedCompiler().compile("fly to the tree and hover")
    assert any(s["op"] == "goto_target" for s in ir["steps"])
    _expect_reject(ir, "not supported in v1")


def test_full_dry_run() -> None:
    m = compile_mission(
        {
            "version": 1,
            "name": "t",
            "units_in": "imperial",
            "safety": {"max_altitude_m": 40, "geofence_radius_m": 50, "max_speed_mps": 0.75},
            "steps": [
                {"op": "arm"},
                {"op": "takeoff"},
                {"op": "goto_relative", "forward": 20, "hold": 0.5},
                {"op": "climb", "up": 100},
                {"op": "hover", "seconds": 2},
                {"op": "land"},
                {"op": "disarm"},
            ],
        }
    )
    client = DryRunClient(log=lambda _m: None)
    MissionExecutor(client, log=lambda _m: None).run(m)
    names = [c[0] for c in client.calls]
    assert names.count("publish_relative_waypoint") == 3  # 2 legs + hover
    assert names[0] == "publish_arm_state" and names[-1] == "publish_arm_state"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR  {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
