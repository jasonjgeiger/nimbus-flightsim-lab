"""Low-level link to a running Betaflight SITL instance (README Section 7, Tier 3).

Betaflight SITL is the *flight controller firmware* only -- it has no physics.
This module speaks its UDP simulator protocol so an external dynamics model can
close the loop:

    us  --fdm_packet--> BF   UDP 9003   (our simulated IMU/state -> FC sensors)
    BF  --servo_packet--> us UDP 9002   (FC motor mixer output   -> our dynamics)
    us  --rc_packet--> BF   UDP 9004   (our RC channels          -> FC receiver)

BF also exposes UART1 as a TCP CLI/MSP port on 5761, used here to one-time
configure arming + modes.

Packet layouts are taken verbatim from Betaflight
src/platform/SIMULATOR/target/SITL/target.h.
"""
from __future__ import annotations

import socket
import struct
import time

# --- endpoints ---------------------------------------------------------------
BF_HOST = "127.0.0.1"
PORT_PWM = 9002    # motor output  (BF  -> us)
PORT_STATE = 9003  # fdm state     (us  -> BF)
PORT_RC = 9004     # rc channels   (us  -> BF)
PORT_CLI = 5761    # UART1 as TCP  (CLI / MSP)

G = 9.80665  # m/s^2, matches BF's "sim 1G = 9.80665"

# Betaflight SITL maps the fdm angular-velocity onto its body gyro axes as
# roll=+rpy0, pitch=-rpy1, yaw=-rpy2 (legacy bridge, ENABLE_GAZEBO_BRIDGE=0;
# see src/platform/SIMULATOR/sitl_gyro.h). Composed with Betaflight's internal
# attitude sign conventions, the net result (verified by single-axis bring-up
# tests -- roll->East, pitch->North, yaw holds heading) is that BF expects our
# raw body rates unchanged: sending the FRD (roll, pitch, yaw) rates directly
# keeps the firmware's rate loop consistent with the body-FRD->world-NED
# quaternion we also send. Any non-identity here reintroduced axis divergence.
GYRO_TO_BF = (1.0, 1.0, 1.0)

# --- packet formats (little-endian, natural alignment, no padding) -----------
# fdm_packet: 18 doubles = 144 bytes
#   timestamp, gyro[3](rad/s), accel[3](m/s^2 NED body), quat[4](w,x,y,z),
#   vel[3](m/s earth), pos[3](m NED), pressure
_FDM_FMT = "<18d"
FDM_SIZE = struct.calcsize(_FDM_FMT)  # 144

# servo_packet: 4 floats (normalized motor speeds [0,1])
_SERVO_FMT = "<4f"
SERVO_SIZE = struct.calcsize(_SERVO_FMT)  # 16

# rc_packet: double timestamp + uint16 channels[16]
_RC_FMT = "<d16H"
RC_SIZE = struct.calcsize(_RC_FMT)  # 40


def pack_fdm(timestamp: float, gyro_xyz, accel_xyz, quat_wxyz, vel_xyz, pos_xyz,
             pressure: float = 101325.0) -> bytes:
    return struct.pack(
        _FDM_FMT,
        timestamp,
        gyro_xyz[0], gyro_xyz[1], gyro_xyz[2],
        accel_xyz[0], accel_xyz[1], accel_xyz[2],
        quat_wxyz[0], quat_wxyz[1], quat_wxyz[2], quat_wxyz[3],
        vel_xyz[0], vel_xyz[1], vel_xyz[2],
        pos_xyz[0], pos_xyz[1], pos_xyz[2],
        pressure,
    )


def unpack_servo(data: bytes) -> tuple[float, float, float, float]:
    return struct.unpack(_SERVO_FMT, data[:SERVO_SIZE])


def pack_rc(channels: list[int], timestamp: float | None = None) -> bytes:
    ch = list(channels)[:16]
    ch += [1500] * (16 - len(ch))  # pad centered
    return struct.pack(_RC_FMT, timestamp if timestamp is not None else time.time(), *ch)


class BetaflightLink:
    """UDP sockets for the Betaflight SITL simulator protocol."""

    def __init__(self, host: str = BF_HOST) -> None:
        self.host = host
        # Receive motor PWM from BF on 9002 (BF connects/sends here -> we bind).
        self.motor_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.motor_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.motor_sock.bind((host, PORT_PWM))
        self.motor_sock.settimeout(2.0)
        # Send fdm state (9003) and rc (9004) to BF.
        self.state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rc_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_fdm(self, timestamp, gyro_xyz, accel_xyz, quat_wxyz, vel_xyz, pos_xyz,
                 pressure: float = 101325.0) -> None:
        # Apply the BF gyro-axis convention (see GYRO_TO_BF) so the firmware's
        # rate loop is consistent with the quaternion attitude we report.
        gyro_bf = (gyro_xyz[0] * GYRO_TO_BF[0],
                   gyro_xyz[1] * GYRO_TO_BF[1],
                   gyro_xyz[2] * GYRO_TO_BF[2])
        payload = pack_fdm(timestamp, gyro_bf, accel_xyz, quat_wxyz, vel_xyz,
                           pos_xyz, pressure)
        self.state_sock.sendto(payload, (self.host, PORT_STATE))

    def send_rc(self, channels: list[int]) -> None:
        self.rc_sock.sendto(pack_rc(channels), (self.host, PORT_RC))

    def recv_motors(self) -> tuple[float, float, float, float] | None:
        try:
            data, _ = self.motor_sock.recvfrom(256)
        except socket.timeout:
            return None
        if len(data) < SERVO_SIZE:
            return None
        return unpack_servo(data)

    def close(self) -> None:
        for s in (self.motor_sock, self.state_sock, self.rc_sock):
            try:
                s.close()
            except OSError:
                pass


def configure_via_cli(commands: list[str], host: str = BF_HOST, port: int = PORT_CLI,
                      settle_s: float = 0.4) -> str:
    """Open the SITL UART1 TCP port, enter CLI, run commands, save.

    Betaflight's CLI runs over the serial-as-TCP link. Sending '#' enters CLI
    mode; 'save' persists to eeprom.bin and reboots the FC.
    """
    transcript: list[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    sock.connect((host, port))
    time.sleep(0.2)

    def _send(line: str) -> None:
        sock.sendall((line + "\r\n").encode())
        time.sleep(settle_s)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                transcript.append(chunk.decode(errors="replace"))
        except socket.timeout:
            pass

    _send("#")  # enter CLI
    for cmd in commands:
        _send(cmd)
    sock.close()
    return "".join(transcript)
