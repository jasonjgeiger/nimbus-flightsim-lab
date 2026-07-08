#!/usr/bin/env python3
"""Tier 3 bridge: Nimbus SDK  <->  Betaflight SITL  (README Section 7).

This is the "Nimbus <-> Sim bridge" from the README. It puts the *real*
Betaflight firmware in the loop for control realism:

    Agent (SDK) --ZMQ 7771--> [bridge guidance] --RC/UDP 9004--> Betaflight SITL
                                                                        |
                       tier3.quad_dynamics  <--motor PWM/UDP 9002-------+
                              |  (6-DOF physics; feeds IMU back on 9003)
    Agent (SDK) <--ZMQ 7772-- [bridge state] <-- dynamics state

Responsibilities (README Section 7):
  1. State out : dynamics -> schema-accurate Nimbus selected_state / telemetry /
     waypoint_status (reuses the Tier 2 FlatBuffer encoders).
  2. Commands in: decode Nimbus arm/autonomy/yaw/speed -> a guidance loop that
     produces RC stick values -> Betaflight (which runs the actual PID + mixer).
  3. Waypoint feedback: distance-to-target -> waypoint_status.

The bridge also launches, one-time-configures (arm + angle mode via CLI), and
supervises the Betaflight SITL process.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time

import zmq

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Reuse the Tier 2 schema-accurate encoders and the SDK command decoder.
from mock_nimbus import encode_state, encode_telemetry, encode_waypoint_status  # noqa: E402
from nimbusos_sdk.schema import load_message_class  # noqa: E402

from tier3 import bf_link, quad_dynamics  # noqa: E402

# --- ZMQ (Nimbus side) -------------------------------------------------------
CMD_ENDPOINT = "tcp://127.0.0.1:7771"    # commands IN
STATE_ENDPOINT = "tcp://127.0.0.1:7772"  # state OUT

BF_BINARY = os.path.join(_REPO_ROOT, ".betaflight", "obj", "main", "betaflight_SITL.elf")
BF_CWD = os.path.join(_REPO_ROOT, ".betaflight")

SIM_HZ = 500.0     # inner physics / FC exchange rate
STATE_HZ = 50.0    # Nimbus state publish rate
TELEM_HZ = 5.0

TAKEOFF_ALT_M = 1.5

# RC channel indices (default AETR map): 0=roll 1=pitch 2=throttle 3=yaw 4=AUX1(arm) 5=AUX2(angle)
RC_MIN, RC_MID, RC_MAX = 1000, 1500, 2000

# One-time Betaflight configuration (persisted to eeprom.bin).
CLI_CONFIG = [
    "feature -GPS",
    "aux 0 0 0 1700 2100",   # ARM (permId 0) on AUX1
    "aux 1 1 1 1700 2100",   # ANGLE (permId 1) on AUX2
    "set small_angle = 180",
    "set runaway_takeoff_prevention = OFF",
    "save",
]

# --- guidance gains (tunable) ------------------------------------------------
HOVER_THROTTLE = 1250
KP_ALT = 400.0     # throttle us per meter of altitude error
KD_ALT = 120.0     # throttle us per (m/s) climb-rate error
KP_POS = 0.6       # desired horizontal speed per meter of position error
KP_VEL = 180.0     # lean-angle stick us per (m/s) velocity error
KP_YAW = 500.0     # yaw stick us per rad heading error
STICK_LEAN_LIMIT = 220   # max roll/pitch stick offset from center (~lean angle cap)
YAW_RATE_LIMIT = 300
ARM_SPOOL_S = 1.5        # hold throttle at idle after arming so BF arms (throttle must be low)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Guidance:
    """Turns Nimbus commands into an RC setpoint the FC can fly."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.armed = False
        self.mode = "idle"           # idle | fly | land
        self.speed_mps = 0.35
        self.tx = self.ty = 0.0      # target NED horizontal (m)
        self.tz = 0.0                # target NED down (m); negative = up
        self.target_yaw = 0.0
        self.command_seq = 0
        self.threshold_m = 0.15
        self.hold_time_s = 0.5
        self.reached_at: float | None = None
        self.armed_since: float | None = None

    def on_arm(self, armed: bool) -> None:
        with self.lock:
            if armed and not self.armed:
                self.armed_since = time.monotonic()
            self.armed = armed
            if not armed:
                self.mode = "idle"
                self.armed_since = None

    def on_speed(self, v: float) -> None:
        with self.lock:
            self.speed_mps = clamp(v, 0.05, 0.75)

    def on_yaw(self, delta: float) -> None:
        with self.lock:
            self.target_yaw = math.atan2(
                math.sin(self.target_yaw + delta), math.cos(self.target_yaw + delta)
            )

    def on_autonomy(self, req_type: int, offset, threshold_m: float, hold_time_s: float,
                    cur_pos, cur_yaw: float) -> None:
        with self.lock:
            self.command_seq += 1
            self.threshold_m = max(threshold_m, 0.05)
            self.hold_time_s = hold_time_s
            self.reached_at = None
            if req_type == 0:            # takeoff
                self.tz = -TAKEOFF_ALT_M
                self.mode = "fly"
            elif req_type in (1, 3):      # land / return_home
                if req_type == 3:
                    self.tx = self.ty = 0.0
                self.tz = 0.0
                self.mode = "land"
            elif req_type == 2 and offset is not None:  # relative waypoint
                fwd, right, down = offset.Forward(), offset.Right(), offset.Down()
                self.tx = cur_pos[0] + fwd * math.cos(cur_yaw) - right * math.sin(cur_yaw)
                self.ty = cur_pos[1] + fwd * math.sin(cur_yaw) + right * math.cos(cur_yaw)
                self.tz = cur_pos[2] + down
                self.mode = "fly"

    def compute_rc(self, dyn: quad_dynamics.QuadDynamics) -> tuple[list[int], dict]:
        with self.lock:
            armed, mode = self.armed, self.mode
            tx, ty, tz, tyaw = self.tx, self.ty, self.tz, self.target_yaw
            speed = self.speed_mps
            threshold, hold_time = self.threshold_m, self.hold_time_s
            armed_since = self.armed_since

        # Betaflight only arms with the throttle stick low; right after the arm
        # switch flips we must keep throttle at idle long enough for BF to arm
        # (and spin motors up) before the altitude loop demands lift.
        spooling = armed and armed_since is not None and (
            time.monotonic() - armed_since) < ARM_SPOOL_S

        pos = dyn.position_ned()
        vel = dyn.velocity_ned()
        yaw = _yaw_from_quat(dyn.quat())

        # --- altitude -> throttle (NED: up is negative z) ---
        alt_err_up = -(tz) - (-pos[2])          # desired_up - actual_up
        climb_up = -vel[2]
        desired_climb = clamp(0.8 * alt_err_up, -1.0, 1.0)
        throttle = HOVER_THROTTLE + KP_ALT * alt_err_up + KD_ALT * (desired_climb - climb_up)

        # --- horizontal position -> desired velocity -> lean stick ---
        ex, ey = tx - pos[0], ty - pos[1]        # world north/east errors
        des_vx = clamp(KP_POS * ex, -speed, speed)
        des_vy = clamp(KP_POS * ey, -speed, speed)
        evx, evy = des_vx - vel[0], des_vy - vel[1]
        # rotate world velocity error into body frame (forward/right).
        # Stick->motion signs verified by single-axis bring-up tests:
        # +pitch stick -> +North (forward), +roll stick -> +East (right).
        fwd_err = evx * math.cos(yaw) + evy * math.sin(yaw)
        right_err = -evx * math.sin(yaw) + evy * math.cos(yaw)
        pitch = RC_MID + clamp(KP_VEL * fwd_err, -STICK_LEAN_LIMIT, STICK_LEAN_LIMIT)
        roll = RC_MID + clamp(KP_VEL * right_err, -STICK_LEAN_LIMIT, STICK_LEAN_LIMIT)

        # --- yaw hold ---
        yaw_err = math.atan2(math.sin(tyaw - yaw), math.cos(tyaw - yaw))
        yaw_stick = RC_MID + clamp(KP_YAW * yaw_err, -YAW_RATE_LIMIT, YAW_RATE_LIMIT)

        if mode == "idle" or not armed:
            throttle = RC_MIN
            roll = pitch = yaw_stick = RC_MID
        elif spooling:
            throttle = RC_MIN
            roll = pitch = RC_MID
            yaw_stick = RC_MID

        arm_ch = RC_MAX if armed else RC_MIN
        rc = [int(clamp(roll, RC_MIN, RC_MAX)),
              int(clamp(pitch, RC_MIN, RC_MAX)),
              int(clamp(throttle, RC_MIN, RC_MAX)),
              int(clamp(yaw_stick, RC_MIN, RC_MAX)),
              arm_ch,      # AUX1 arm
              RC_MAX,      # AUX2 angle mode (always on)
              ]

        # --- waypoint status bookkeeping + auto-disarm after landing ---
        dist = math.sqrt(ex * ex + ey * ey + (tz - pos[2]) ** 2)
        with self.lock:
            if mode in ("fly", "land"):
                if dist <= threshold:
                    if self.reached_at is None:
                        self.reached_at = time.monotonic()
                elif dist > max(threshold * 4.0, threshold + 1.0):
                    # departed the target by a gross margin (e.g. altitude
                    # overshoot): restart the hold timer so "held" means
                    # genuinely settled. Small settle-jitter within the band
                    # is tolerated so a hover can accumulate its hold time.
                    self.reached_at = None
            reached = self.reached_at is not None
            held = reached and (time.monotonic() - self.reached_at) >= hold_time
            if mode == "land" and (-pos[2]) < 0.08:
                self.armed = False
                self.mode = "idle"
            status = {"active": mode in ("fly", "land"), "reached": reached,
                      "held": held, "dist": dist, "command_seq": self.command_seq,
                      "yaw": yaw, "pos": pos, "vel": vel}
        return rc, status


def _yaw_from_quat(q):
    w, x, y, z = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


# --- Nimbus state encoding from dynamics -------------------------------------

def _nimbus_snapshot(status: dict) -> dict:
    pos, vel = status["pos"], status["vel"]
    return {
        "x": pos[0], "y": pos[1], "z": pos[2], "yaw": status["yaw"],
        "active": status["active"], "reached": status["reached"],
        "held": status["held"], "dist": status["dist"],
        "command_seq": status["command_seq"],
    }


# --- command decoding (Nimbus ZMQ -> guidance) -------------------------------
_COMMAND_CLASSES = {
    "arm_state": "ArmMessage",
    "waypoint_speed": "WaypointSpeedMessage",
    "autonomy_request": "AutonomyRequestMessage",
    "yaw_turn_command": "YawTurnCommandMessage",
}


def command_thread(guid: Guidance, dyn: quad_dynamics.QuadDynamics, sock: zmq.Socket) -> None:
    while True:
        parts = sock.recv_multipart()
        topic = parts[0].decode(errors="replace")
        payload = parts[1] if len(parts) > 1 else b""
        cls = _COMMAND_CLASSES.get(topic)
        if cls is None:
            continue
        msg = load_message_class(cls).GetRootAs(payload, 0)
        if topic == "arm_state":
            guid.on_arm(bool(msg.Armed()))
            print(f"[bridge] arm_state={bool(msg.Armed())}")
        elif topic == "waypoint_speed":
            guid.on_speed(float(msg.SpeedMps()))
        elif topic == "yaw_turn_command":
            guid.on_yaw(float(msg.DeltaYawRad()))
        elif topic == "autonomy_request":
            guid.on_autonomy(int(msg.Type()), msg.BodyOffset(), float(msg.ThresholdM()),
                             float(msg.HoldTimeS()), dyn.position_ned(),
                             _yaw_from_quat(dyn.quat()))
            print(f"[bridge] autonomy_request type={int(msg.Type())}")


# --- Betaflight process supervision ------------------------------------------

def _wait_port(host: str, port: int, timeout: float = 10.0) -> bool:
    import socket as _s
    end = time.time() + timeout
    while time.time() < end:
        try:
            with _s.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start_betaflight() -> subprocess.Popen:
    if not os.path.exists(BF_BINARY):
        raise SystemExit(f"Betaflight SITL binary not found: {BF_BINARY}\n"
                         f"Build it with: (cd .betaflight && make TARGET=SITL)")
    proc = subprocess.Popen([BF_BINARY], cwd=BF_CWD,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_port("127.0.0.1", bf_link.PORT_CLI, timeout=10.0)
    time.sleep(0.5)
    return proc


def configure_betaflight() -> None:
    """Start BF, push CLI config (save -> BF exits), leave eeprom.bin configured."""
    print("[bridge] configuring Betaflight (one-time) ...")
    proc = start_betaflight()
    try:
        bf_link.configure_via_cli(CLI_CONFIG)
    except OSError as exc:
        print(f"[bridge] CLI config warning: {exc}")
    # 'save' triggers systemReset -> exit(0); wait for the process to go.
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
    print("[bridge] configuration saved to eeprom.bin")


def main() -> None:
    # run.sh (and most supervisors) stop us with SIGTERM; translate it into a
    # normal exit so the `finally` below always tears Betaflight down. Otherwise
    # BF is orphaned and keeps port 5761, breaking the next launch.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    configure_betaflight()
    bf = start_betaflight()

    link = bf_link.BetaflightLink()
    dyn = quad_dynamics.QuadDynamics()
    guid = Guidance()

    ctx = zmq.Context.instance()
    cmd = ctx.socket(zmq.SUB)
    cmd.bind(CMD_ENDPOINT)
    cmd.setsockopt_string(zmq.SUBSCRIBE, "")
    state = ctx.socket(zmq.PUB)
    state.bind(STATE_ENDPOINT)

    threading.Thread(target=command_thread, args=(guid, dyn, cmd), daemon=True).start()

    print("[bridge] Tier 3 running: Betaflight SITL in the loop.")
    print(f"[bridge]   Nimbus commands IN  <- {CMD_ENDPOINT}")
    print(f"[bridge]   Nimbus state    OUT -> {STATE_ENDPOINT}")

    dt = 1.0 / SIM_HZ
    state_every = max(1, int(SIM_HZ / STATE_HZ))
    telem_every = max(1, int(SIM_HZ / TELEM_HZ))
    seq = 0
    last_status = {"pos": (0, 0, 0), "vel": (0, 0, 0), "yaw": 0.0, "active": False,
                   "reached": False, "held": False, "dist": 0.0, "command_seq": 0}

    # Betaflight SITL is a strict 1:1 lock-step: each fdm_packet unlocks exactly
    # one servo_packet, and BF derives its internal clock from the fdm timestamp.
    # We therefore advance an explicit sim clock every exchange (decoupled from
    # motor receipt) and pace the loop to wall-clock so BF's simRate stays ~1.0.
    link.motor_sock.settimeout(0.1)
    simt = 0.0
    motors = [0.0, 0.0, 0.0, 0.0]

    def _send_fdm() -> None:
        link.send_fdm(simt, dyn.gyro(), dyn.accel_body(), dyn.quat(),
                      dyn.velocity_ned(), dyn.position_ned())

    _send_fdm()  # prime the FC
    wall_start = time.perf_counter()

    # Readiness handshake: only signal ready once the loop has streamed RC
    # (AUX1 held low) through Betaflight's boot-grace, so the agent's first arm
    # command lands as a clean OFF->ON transition after the FC is armable.
    ready_file = os.environ.get("NIMBUS_TIER3_READY")
    ready_grace = float(os.environ.get("NIMBUS_TIER3_READY_GRACE", "6.0"))
    ready_signaled = False
    try:
        while True:
            got = link.recv_motors()
            if got is not None:
                motors = list(got)

            dyn.step(motors, dt)
            simt += dt
            rc, last_status = guid.compute_rc(dyn)
            link.send_rc(rc)
            _send_fdm()

            seq += 1
            if seq % state_every == 0:
                snap = _nimbus_snapshot(last_status)
                state.send_multipart([b"selected_state", encode_state(seq, snap)])
                state.send_multipart([b"waypoint_status", encode_waypoint_status(seq, snap)])
            if seq % telem_every == 0:
                state.send_multipart([b"telemetry", encode_telemetry(seq, guid.armed)])

            # Pace to real time so BF's simulated clock tracks wall-clock.
            sleep_s = (wall_start + simt) - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)

            if not ready_signaled and simt >= ready_grace:
                ready_signaled = True
                print("[bridge] READY (Betaflight armable; agent may connect).")
                if ready_file:
                    try:
                        with open(ready_file, "w") as fh:
                            fh.write("ready\n")
                    except OSError as exc:
                        print(f"[bridge] could not write ready file: {exc}")
    except KeyboardInterrupt:
        print("\n[bridge] stopping.")
    finally:
        link.close()
        bf.terminate()
        try:
            bf.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            bf.kill()


if __name__ == "__main__":
    main()
