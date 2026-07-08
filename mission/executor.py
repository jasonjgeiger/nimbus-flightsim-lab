"""Deterministic Mission Executor: NormalizedMission -> NimbusClient calls.

Generalizes agents/orbit_agent.py into a data-driven runner. It only ever talks
to nimbusos_sdk.NimbusClient, so the same code flies Betaflight SITL today
(./run.sh tier3) and a real NimbusOS drone later (endpoint swap).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Protocol

from mission.ir import NormalizedMission, NormalizedStep

# default bounded wait for a moving leg to reach & hold, in seconds
DEFAULT_LEG_TIMEOUT_S = 20.0


class _Client(Protocol):
    def publish_arm_state(self, armed: bool = True) -> None: ...
    def publish_waypoint_speed(self, speed_mps: float) -> None: ...
    def publish_autonomy_request(self, request_type: str, **kw: Any) -> None: ...
    def publish_relative_waypoint(self, **kw: Any) -> None: ...
    def publish_yaw_turn_command(self, delta_yaw_rad: float) -> None: ...
    def waypoint_status(self, **kw: Any): ...


class MissionExecutor:
    """Runs a validated mission against a NimbusClient-compatible endpoint.

    Parameters
    ----------
    client:
        Any object with the NimbusClient command/telemetry surface.
    leg_timeout_s:
        Bounded wait for each moving leg to reach & hold before aborting.
    log:
        Callable for progress lines (defaults to print).
    """

    def __init__(
        self,
        client: _Client,
        *,
        leg_timeout_s: float = DEFAULT_LEG_TIMEOUT_S,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._c = client
        self._leg_timeout_s = leg_timeout_s
        self._log = log or (lambda m: print(m, flush=True))
        self._armed = False
        self._speed_mps: float | None = None  # last commanded cruise speed
        self._last_seq = 0  # highest waypoint command_seq observed so far

    def run(self, mission: NormalizedMission) -> None:
        """Execute every step. On any failure, land + disarm, then re-raise."""
        self._log(f"[mission] start: {mission.name} ({len(mission.steps)} steps)")
        try:
            for i, step in enumerate(mission.steps):
                self._log(f"[mission] {i + 1}/{len(mission.steps)}: {step.describe}")
                self._run_step(step)
            self._log("[mission] complete")
        except Exception as exc:  # noqa: BLE001 - we re-raise after safe teardown
            self._log(f"[mission] ABORT: {exc} -> land + disarm")
            self._safe_teardown()
            raise

    # --- per-step dispatch --------------------------------------------------
    def _run_step(self, s: NormalizedStep) -> None:
        if s.op == "arm":
            self._c.publish_arm_state(True)
            self._armed = True
        elif s.op == "disarm":
            self._c.publish_arm_state(False)
            self._armed = False
        elif s.op == "set_speed":
            self._c.publish_waypoint_speed(s.speed_mps)
            self._speed_mps = s.speed_mps
        elif s.op == "takeoff":
            self._c.publish_autonomy_request("takeoff")
        elif s.op == "land":
            self._c.publish_autonomy_request("land")
        elif s.op == "yaw_turn":
            self._c.publish_yaw_turn_command(s.delta_yaw_rad)
        elif s.op in ("goto_relative", "hover"):
            self._fly_leg(s)
        else:  # pragma: no cover - validator guarantees a known op
            raise ValueError(f"executor cannot handle op '{s.op}'")

    def _fly_leg(self, s: NormalizedStep) -> None:
        # Learn the backend's current command sequence BEFORE issuing the new
        # waypoint, so we can ignore stale "reached" statuses left over from the
        # previous leg (each waypoint bumps command_seq on the backend).
        baseline = self._current_seq()
        if s.speed_mps is not None:
            self._c.publish_waypoint_speed(s.speed_mps)
            self._speed_mps = s.speed_mps
        self._c.publish_relative_waypoint(
            forward=s.forward_m,
            right=s.right_m,
            down=s.down_m,
            mode="override",
            threshold_m=s.threshold_m,
            hold_time_s=s.hold_time_s,
        )
        self._wait_reached(self._leg_budget_s(s), min_seq=baseline + 1)

    def _leg_budget_s(self, s: NormalizedStep) -> float:
        """Adaptive wait: allow real travel time (distance/speed) + hold + margin,
        never less than the configured floor."""
        dist = (s.forward_m ** 2 + s.right_m ** 2 + s.down_m ** 2) ** 0.5
        speed = self._speed_mps or 0.3  # conservative if no speed was ever set
        travel = dist / speed if speed > 0 else 0.0
        return max(self._leg_timeout_s, travel * 3.0 + s.hold_time_s + 15.0)

    def _current_seq(self) -> int:
        """Peek the stream briefly to capture the backend's current command_seq."""
        end = time.monotonic() + 0.4
        for status in self._c.waypoint_status(timeout_sec=0.4):
            self._last_seq = max(self._last_seq, int(getattr(status, "command_seq", 0)))
            if time.monotonic() >= end:
                break
        return self._last_seq

    def _wait_reached(self, timeout_s: float, *, min_seq: int) -> None:
        deadline = time.monotonic() + timeout_s
        for status in self._c.waypoint_status(timeout_sec=timeout_s):
            seq = int(getattr(status, "command_seq", 0))
            self._last_seq = max(self._last_seq, seq)
            # ignore statuses from before this waypoint was accepted (stale)
            if seq < min_seq:
                if time.monotonic() > deadline:
                    break
                continue
            if getattr(status, "reached", False) and getattr(status, "held", False):
                dist = getattr(status, "distance_m", float("nan"))
                self._log(f"[mission]   reached (distance={dist:.2f} m)")
                return
            if time.monotonic() > deadline:
                break
        raise TimeoutError(
            f"leg did not reach & hold within {timeout_s:.0f} s"
        )

    def _safe_teardown(self) -> None:
        try:
            self._c.publish_autonomy_request("land")
            time.sleep(0.2)
            self._c.publish_arm_state(False)
        except Exception as exc:  # noqa: BLE001 - best-effort teardown
            self._log(f"[mission] teardown error (ignored): {exc}")


class DryRunClient:
    """A NimbusClient stand-in that logs calls instead of flying — for previews
    and tests. ``waypoint_status`` yields one immediately-reached status."""

    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self._log = log or (lambda m: print(m, flush=True))
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._seq = 0  # models backend command_seq (bumped per waypoint)

    def _rec(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))
        self._log(f"[dry-run] {name}({', '.join(f'{k}={v}' for k, v in kw.items())})")

    def publish_arm_state(self, armed: bool = True) -> None:
        self._rec("publish_arm_state", armed=armed)

    def publish_waypoint_speed(self, speed_mps: float) -> None:
        self._rec("publish_waypoint_speed", speed_mps=speed_mps)

    def publish_autonomy_request(self, request_type: str, **kw: Any) -> None:
        self._seq += 1
        self._rec("publish_autonomy_request", request_type=request_type, **kw)

    def publish_relative_waypoint(self, **kw: Any) -> None:
        self._seq += 1
        self._rec("publish_relative_waypoint", **kw)

    def publish_yaw_turn_command(self, delta_yaw_rad: float) -> None:
        self._seq += 1
        self._rec("publish_yaw_turn_command", delta_yaw_rad=delta_yaw_rad)

    def waypoint_status(self, **kw: Any):
        self._rec("waypoint_status", **kw)
        seq = self._seq

        class _S:
            reached = True
            held = True
            distance_m = 0.0
            command_seq = seq

        yield _S()
