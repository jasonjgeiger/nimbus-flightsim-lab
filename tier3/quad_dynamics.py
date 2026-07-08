"""Quad rigid-body dynamics that close the loop with Betaflight SITL (Tier 3).

Betaflight SITL ships no physics: it outputs 4 normalized motor commands and
expects to be fed back IMU (gyro + orientation) and state. This module is that
"external dynamics feeder" the README (Section 7) describes -- it replaces the
Tier 2 point-mass integrator with a 6-DOF rigid body whose geometry matches
Betaflight's QUADX mixer so the real firmware PIDs stabilise it.

Frames: body = FRD (x forward, y right, z down); world = NED (z down).
Motor order matches BF QUADX: M0 rear-right, M1 front-right, M2 rear-left,
M3 front-left.

The sign constants near the top let you flip conventions quickly if the closed
loop diverges during bring-up (see tier3/README notes).
"""
from __future__ import annotations

import math

G = 9.80665

# --- vehicle parameters (a small 5" quad ballpark) ---------------------------
MASS = 0.5            # kg
ARM = 0.12           # m, motor distance from center along each axis (X arms)
THRUST_MAX = 4.0     # N per motor at full command (~1.6 kg total -> ~3.2:1 TWR)
K_YAW = 0.06         # yaw drag torque per Newton of thrust (m)
IXX = 3.0e-3         # kg m^2
IYY = 3.0e-3
IZZ = 5.0e-3
LIN_DRAG = 0.10      # translational drag coeff (N per m/s)
ANG_DRAG = 2.0e-3    # rotational drag (N m per rad/s)

# Sign conventions (flip if BF's control loop pushes the craft the wrong way).
ROLL_SIGN = 1.0
PITCH_SIGN = 1.0
YAW_SIGN = 1.0

# Motor geometry: (x, y) body position and BF yaw-mixer factor per motor.
#   BF QUADX yaw column: M0 -1, M1 +1, M2 +1, M3 -1.
_MOTORS = [
    (-ARM, +ARM, -1.0),  # M0 rear-right
    (+ARM, +ARM, +1.0),  # M1 front-right
    (-ARM, -ARM, +1.0),  # M2 rear-left
    (+ARM, -ARM, -1.0),  # M3 front-left
]


def _quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def _quat_normalize(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def _rotate_body_to_world(q, v):
    """Rotate a body-frame vector into the world frame using quaternion q (w,x,y,z)."""
    w, x, y, z = q
    vx, vy, vz = v
    # r = q * (0,v) * q_conj
    t = _quat_mul(_quat_mul(q, (0.0, vx, vy, vz)), (w, -x, -y, -z))
    return (t[1], t[2], t[3])


def _rotate_world_to_body(q, v):
    w, x, y, z = q
    return _rotate_body_to_world((w, -x, -y, -z), v)


class QuadDynamics:
    """6-DOF quad integrated from Betaflight's 4 normalized motor commands."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.pos = [0.0, 0.0, 0.0]      # NED world, z down (negative = up)
        self.vel = [0.0, 0.0, 0.0]      # NED world
        self.q = (1.0, 0.0, 0.0, 0.0)   # body->world, level
        self.omega = [0.0, 0.0, 0.0]    # body rates rad/s (roll, pitch, yaw)
        self.t = 0.0
        self._total_thrust = 0.0        # N, last commanded total thrust

    def step(self, motors: tuple[float, float, float, float], dt: float) -> None:
        thrusts = [max(0.0, min(1.0, m)) * THRUST_MAX for m in motors]

        # --- torques (body frame) from thrust geometry + prop drag ---
        tx = ty = tz = 0.0
        for (x, y, yaw_factor), f in zip(_MOTORS, thrusts):
            tx += -y * f            # roll:  (r x F)_x = -y*f
            ty += x * f             # pitch: (r x F)_y =  x*f
            tz += yaw_factor * K_YAW * f
        tx = ROLL_SIGN * tx - ANG_DRAG * self.omega[0]
        ty = PITCH_SIGN * ty - ANG_DRAG * self.omega[1]
        tz = YAW_SIGN * tz - ANG_DRAG * self.omega[2]

        # --- angular acceleration: I w_dot = tau - w x (I w) ---
        wx, wy, wz = self.omega
        Iw = (IXX * wx, IYY * wy, IZZ * wz)
        gyro_cross = (
            wy * Iw[2] - wz * Iw[1],
            wz * Iw[0] - wx * Iw[2],
            wx * Iw[1] - wy * Iw[0],
        )
        wdot = [
            (tx - gyro_cross[0]) / IXX,
            (ty - gyro_cross[1]) / IYY,
            (tz - gyro_cross[2]) / IZZ,
        ]
        self.omega = [w + a * dt for w, a in zip(self.omega, wdot)]

        # --- attitude integration ---
        q_dot = _quat_mul(self.q, (0.0, self.omega[0], self.omega[1], self.omega[2]))
        self.q = _quat_normalize(tuple(c + 0.5 * qd * dt for c, qd in zip(self.q, q_dot)))

        # --- translational dynamics ---
        total_thrust = sum(thrusts)
        self._total_thrust = total_thrust
        # thrust acts along body -z (up); express in world
        thrust_world = _rotate_body_to_world(self.q, (0.0, 0.0, -total_thrust))
        acc = [
            thrust_world[0] / MASS - LIN_DRAG * self.vel[0] / MASS,
            thrust_world[1] / MASS - LIN_DRAG * self.vel[1] / MASS,
            thrust_world[2] / MASS + G - LIN_DRAG * self.vel[2] / MASS,
        ]
        self.vel = [v + a * dt for v, a in zip(self.vel, acc)]
        self.pos = [p + v * dt for p, v in zip(self.pos, self.vel)]

        # --- ground contact (z down; z >= 0 is at/below ground) ---
        if self.pos[2] > 0.0:
            self.pos[2] = 0.0
            if self.vel[2] > 0.0:
                self.vel[2] = 0.0
            # settle rotation/horizontal drift while landed
            self.omega = [0.0, 0.0, 0.0]

        self.t += dt

    # --- outputs ----------------------------------------------------------
    def gyro(self) -> tuple[float, float, float]:
        return tuple(self.omega)

    def accel_body(self) -> tuple[float, float, float]:
        """Specific force in body frame (what an accelerometer reads), m/s^2 NED."""
        # specific force (world) = a_world - gravity = thrust_world / m
        thrust_world = _rotate_body_to_world(self.q, (0.0, 0.0, -self._total_thrust))
        spec_world = (thrust_world[0] / MASS, thrust_world[1] / MASS, thrust_world[2] / MASS)
        return _rotate_world_to_body(self.q, spec_world)

    def quat(self) -> tuple[float, float, float, float]:
        return self.q

    def position_ned(self) -> tuple[float, float, float]:
        return tuple(self.pos)

    def velocity_ned(self) -> tuple[float, float, float]:
        return tuple(self.vel)
