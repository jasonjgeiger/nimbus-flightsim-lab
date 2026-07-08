#!/usr/bin/env python3
"""Tier 2 kinematic mock NimbusOS (README Section 6).

Plays the role of a running NimbusOS instance so you can develop and test agents
with a real closed loop -- no drone, no physics engine, hardware-free.

  * Binds tcp://127.0.0.1:7771 (SUB) and decodes the SDK's FlatBuffer commands:
        arm_state, waypoint_speed, autonomy_request, yaw_turn_command
  * Binds tcp://127.0.0.1:7772 (PUB) and emits schema-accurate FlatBuffers:
        selected_state, waypoint_status, telemetry
    so the SDK's *typed* helpers (client.selected_state(), client.waypoint_status(),
    client.telemetry()) work unmodified -- the same code runs against real NimbusOS.

Model: a simple point mass that moves toward the commanded relative waypoint at
the current waypoint speed. Deterministic and fast. Restart between runs for a
clean start.

Usage (from the repo root, venv activated):
    python mock_nimbus.py
"""
from __future__ import annotations

import math
import threading
import time

import flatbuffers
import zmq

from nimbusos_sdk.schema import ensure_generated_schema_on_path, load_message_class

# Make the generated FlatBuffers schema modules importable, then import them.
ensure_generated_schema_on_path()
from droneforge.schema import (  # noqa: E402  (import after path setup)
    AttitudeData as AD,
    BatterySensorData as BSD,
    EulerAngles3D as EA,
    LinkStatisticsData as LSD,
    LocalFrameVector3D as V3,
    Quaternion as QT,
    State as St,
    StateMessage as SM,
    TelemetryMessage as TM,
    WaypointStatusMessage as WSM,
)

CMD_ENDPOINT = "tcp://127.0.0.1:7771"    # commands IN (SDK publishes here)
STATE_ENDPOINT = "tcp://127.0.0.1:7772"  # state OUT (SDK subscribes here)

# AutonomyRequestType enum (from the schema): Takeoff=0, Land=1, RelativeWaypoint=2,
# ReturnHome=3, LandPerimeterBreach=4.
REQ_TAKEOFF, REQ_LAND, REQ_RELATIVE_WAYPOINT, REQ_RETURN_HOME = 0, 1, 2, 3

TAKEOFF_ALT_M = 1.5   # local-frame z is negative-up; takeoff climbs to -1.5 m
STATE_HZ = 20.0
TELEM_HZ = 5.0


class Drone:
    """Minimal point-mass drone state in the local frame (meters, radians)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.armed = False
        self.speed_mps = 0.35
        self.x = self.y = self.z = 0.0
        self.tx = self.ty = self.tz = 0.0  # target
        self.yaw = 0.0
        self.threshold_m = 0.05
        self.hold_time_s = 0.0
        self.active = False
        self.reached_at: float | None = None
        self.command_seq = 0

    # --- command handlers -------------------------------------------------
    def set_armed(self, armed: bool) -> None:
        with self.lock:
            self.armed = armed

    def set_speed(self, speed_mps: float) -> None:
        with self.lock:
            self.speed_mps = speed_mps

    def yaw_turn(self, delta_rad: float) -> None:
        with self.lock:
            self.yaw = (self.yaw + delta_rad + math.pi) % (2 * math.pi) - math.pi

    def autonomy_request(self, req_type: int, offset, threshold_m: float,
                         hold_time_s: float) -> None:
        with self.lock:
            self.command_seq += 1
            self.threshold_m = max(threshold_m, 1e-3)
            self.hold_time_s = hold_time_s
            self.reached_at = None
            if req_type == REQ_TAKEOFF:
                self.tz = -TAKEOFF_ALT_M
                self.active = True
            elif req_type in (REQ_LAND, REQ_RETURN_HOME):
                if req_type == REQ_RETURN_HOME:
                    self.tx = self.ty = 0.0
                self.tz = 0.0
                self.active = True
            elif req_type == REQ_RELATIVE_WAYPOINT and offset is not None:
                fwd, right, down = offset.Forward(), offset.Right(), offset.Down()
                # body-frame -> local-frame using current yaw
                self.tx = self.x + fwd * math.cos(self.yaw) - right * math.sin(self.yaw)
                self.ty = self.y + fwd * math.sin(self.yaw) + right * math.cos(self.yaw)
                self.tz = self.z + down
                self.active = True

    # --- integrator -------------------------------------------------------
    def step(self, dt: float) -> None:
        with self.lock:
            if not self.armed:
                return
            dx, dy, dz = self.tx - self.x, self.ty - self.y, self.tz - self.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            max_step = max(self.speed_mps, 1e-3) * dt
            if dist <= max_step or dist == 0.0:
                self.x, self.y, self.z = self.tx, self.ty, self.tz
            else:
                s = max_step / dist
                self.x += dx * s
                self.y += dy * s
                self.z += dz * s
            # waypoint-status bookkeeping
            if self.active and dist <= self.threshold_m:
                if self.reached_at is None:
                    self.reached_at = time.monotonic()

    def snapshot(self):
        with self.lock:
            dx, dy, dz = self.tx - self.x, self.ty - self.y, self.tz - self.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            reached = self.reached_at is not None
            held = reached and (time.monotonic() - self.reached_at) >= self.hold_time_s
            return {
                "x": self.x, "y": self.y, "z": self.z, "yaw": self.yaw,
                "active": self.active, "reached": reached, "held": held,
                "dist": dist, "command_seq": self.command_seq,
            }


# --- FlatBuffers encoders (schema-accurate; typed helpers can decode them) ---

def encode_state(seq: int, snap: dict) -> bytes:
    b = flatbuffers.Builder(256)
    St.StateStart(b)
    St.StateAddValid(b, True)
    St.StateAddPosition(b, V3.CreateLocalFrameVector3D(b, snap["x"], snap["y"], snap["z"]))
    St.StateAddVelocity(b, V3.CreateLocalFrameVector3D(b, 0.0, 0.0, 0.0))
    St.StateAddForward(b, V3.CreateLocalFrameVector3D(b, math.cos(snap["yaw"]), math.sin(snap["yaw"]), 0.0))
    St.StateAddRight(b, V3.CreateLocalFrameVector3D(b, -math.sin(snap["yaw"]), math.cos(snap["yaw"]), 0.0))
    St.StateAddAttitude(b, EA.CreateEulerAngles3D(b, 0.0, 0.0, snap["yaw"]))
    St.StateAddOrientation(b, QT.CreateQuaternion(b, math.cos(snap["yaw"] / 2), 0.0, 0.0, math.sin(snap["yaw"] / 2)))
    state = St.StateEnd(b)
    SM.StateMessageStart(b)
    SM.StateMessageAddSeq(b, seq)
    SM.StateMessageAddTNs(b, time.monotonic_ns())
    SM.StateMessageAddState(b, state)
    b.Finish(SM.StateMessageEnd(b))
    return bytes(b.Output())


def encode_waypoint_status(seq: int, snap: dict) -> bytes:
    b = flatbuffers.Builder(128)
    WSM.WaypointStatusMessageStart(b)
    WSM.WaypointStatusMessageAddSeq(b, seq)
    WSM.WaypointStatusMessageAddTNs(b, time.monotonic_ns())
    WSM.WaypointStatusMessageAddCommandSeq(b, snap["command_seq"])
    WSM.WaypointStatusMessageAddActive(b, snap["active"])
    WSM.WaypointStatusMessageAddReached(b, snap["reached"])
    WSM.WaypointStatusMessageAddHeld(b, snap["held"])
    WSM.WaypointStatusMessageAddDistanceM(b, snap["dist"])
    WSM.WaypointStatusMessageAddWaypointIndex(b, 0)
    b.Finish(WSM.WaypointStatusMessageEnd(b))
    return bytes(b.Output())


def encode_telemetry(seq: int, armed: bool) -> bytes:
    b = flatbuffers.Builder(256)
    rf_mode = b.CreateString("mock")
    LSD.LinkStatisticsDataStart(b)
    LSD.LinkStatisticsDataAddUplinkLinkQuality(b, 100)
    LSD.LinkStatisticsDataAddRfMode(b, rf_mode)
    link = LSD.LinkStatisticsDataEnd(b)

    TM.TelemetryMessageStart(b)
    TM.TelemetryMessageAddSeq(b, seq)
    TM.TelemetryMessageAddTNs(b, time.monotonic_ns())
    # structs are written inline within the table build
    TM.TelemetryMessageAddBattery(
        b, BSD.CreateBatterySensorData(b, 16.0, 0.0, 1500.0, 100.0, time.monotonic_ns())
    )
    TM.TelemetryMessageAddAttitude(
        b, AD.CreateAttitudeData(b, 0.0, 0.0, 0.0, time.monotonic_ns())
    )
    TM.TelemetryMessageAddLinkStats(b, link)
    b.Finish(TM.TelemetryMessageEnd(b))
    return bytes(b.Output())


# --- command dispatch ---------------------------------------------------------

_COMMAND_CLASSES = {
    "arm_state": "ArmMessage",
    "waypoint_speed": "WaypointSpeedMessage",
    "autonomy_request": "AutonomyRequestMessage",
    "yaw_turn_command": "YawTurnCommandMessage",
}


def _decode(topic: str, payload: bytes):
    cls = load_message_class(_COMMAND_CLASSES[topic])
    return cls.GetRootAs(payload, 0)


def handle_commands(drone: Drone, sock: zmq.Socket) -> None:
    while True:
        parts = sock.recv_multipart()
        topic = parts[0].decode(errors="replace")
        payload = parts[1] if len(parts) > 1 else b""
        if topic not in _COMMAND_CLASSES:
            print(f"[mock] rx unknown topic={topic}")
            continue
        try:
            msg = _decode(topic, payload)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[mock] failed to decode {topic}: {exc}")
            continue
        if topic == "arm_state":
            drone.set_armed(bool(msg.Armed()))
            print(f"[mock] rx arm_state armed={bool(msg.Armed())}")
        elif topic == "waypoint_speed":
            drone.set_speed(float(msg.SpeedMps()))
            print(f"[mock] rx waypoint_speed speed={float(msg.SpeedMps()):.2f} m/s")
        elif topic == "yaw_turn_command":
            drone.yaw_turn(float(msg.DeltaYawRad()))
            print(f"[mock] rx yaw_turn delta={float(msg.DeltaYawRad()):+.2f} rad")
        elif topic == "autonomy_request":
            drone.autonomy_request(
                int(msg.Type()), msg.BodyOffset(),
                float(msg.ThresholdM()), float(msg.HoldTimeS()),
            )
            print(f"[mock] rx autonomy_request type={int(msg.Type())} "
                  f"threshold={float(msg.ThresholdM()):.2f} hold={float(msg.HoldTimeS()):.2f}")


def main() -> None:
    ctx = zmq.Context.instance()

    cmd = ctx.socket(zmq.SUB)
    cmd.bind(CMD_ENDPOINT)
    cmd.setsockopt_string(zmq.SUBSCRIBE, "")

    state = ctx.socket(zmq.PUB)
    state.bind(STATE_ENDPOINT)

    drone = Drone()
    threading.Thread(target=handle_commands, args=(drone, cmd), daemon=True).start()

    print(f"[mock] NimbusOS stand-in running.")
    print(f"[mock]   commands  IN  <- {CMD_ENDPOINT}")
    print(f"[mock]   state     OUT -> {STATE_ENDPOINT}")
    print("[mock] emitting selected_state / waypoint_status / telemetry (Ctrl-C to stop)")

    dt = 1.0 / STATE_HZ
    telem_every = max(1, int(STATE_HZ / TELEM_HZ))
    seq = 0
    try:
        while True:
            drone.step(dt)
            snap = drone.snapshot()
            seq += 1
            state.send_multipart([b"selected_state", encode_state(seq, snap)])
            state.send_multipart([b"waypoint_status", encode_waypoint_status(seq, snap)])
            if seq % telem_every == 0:
                state.send_multipart([b"telemetry", encode_telemetry(seq, snap["active"])])
            time.sleep(dt)
    except KeyboardInterrupt:
        print("\n[mock] stopped.")


if __name__ == "__main__":
    main()
