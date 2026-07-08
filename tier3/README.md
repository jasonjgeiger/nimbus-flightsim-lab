# Tier 3 — Betaflight SITL bridge

This is the concrete, working implementation of README **Section 7**: a bridge that
puts the *real* Betaflight flight-control firmware in the loop for control realism.
Your agent talks plain Nimbus ZMQ; the bridge translates to/from Betaflight and runs
a small guidance loop, while Betaflight itself runs the actual PID controllers and
QUADX motor mixer.

```
 Agent (SDK) --ZMQ 7771--> [bridge guidance] --RC/UDP 9004--> Betaflight SITL
                                                                    |
                    tier3/quad_dynamics.py <--motor PWM/UDP 9002----+
                          |  (6-DOF physics; feeds IMU/state back on 9003)
 Agent (SDK) <--ZMQ 7772-- [bridge state] <-- dynamics state
```

- `bf_link.py` — low-level UDP link + CLI configurator for Betaflight SITL.
- `quad_dynamics.py` — 6-DOF rigid-body physics matching the BF QUADX geometry.
- `bridge.py` — the bridge: ZMQ ↔ guidance ↔ Betaflight, plus BF process supervision.

## Quick start

```bash
# one-time: build Betaflight SITL (see "Build" below)
./run.sh tier3                       # bridge + agents/orbit_agent.py
./run.sh tier3 agents/your_agent.py  # bridge + a different agent
```

`run.sh tier3` starts the bridge (which boots, one-time-configures, and supervises
Betaflight), waits for the bridge's **readiness handshake**, then launches the agent.
The default `orbit_agent.py` arms → takes off → flies a 1 m square (4 relative legs
with a 90° yaw turn between each) → lands → disarms.

To run the bridge by itself:

```bash
.venv/bin/python tier3/bridge.py     # then run any agent in another terminal
```

## Build (required — do not skip the OPTIONS)

```bash
cd .betaflight
make TARGET=SITL OPTIONS="ENABLE_GAZEBO_BRIDGE=0"
# output: .betaflight/obj/main/betaflight_SITL.elf   (incremental rebuild ~7 s)
```

**`ENABLE_GAZEBO_BRIDGE=0` is mandatory.** A bare `make TARGET=SITL` defaults the
Gazebo bridge **on**, which applies an internal `Rz(90°)` transform to the attitude
quaternion and assumes a Gazebo frame — this cross-couples the axes and makes the
quad diverge. The legacy bridge (`=0`) consumes our body-FRD → world-NED quaternion
directly, which is what `quad_dynamics.py` produces.

## Watch it live in the Betaflight App (Chrome) — via a WebSocket proxy

You can open the Betaflight App and watch SITL's attitude/receiver/motors while the
bridge flies it. There's a catch on modern setups:

- The current Betaflight App (`app.betaflight.com`, 2025.12+) is a **browser PWA**.
  Its SITL connection is a **WebSocket** (`ws://…`); browsers can't open raw TCP.
- **There is no longer a native macOS desktop build** (recent releases ship only the
  web PWA + an Android `.apk`), so "just install the desktop app" isn't an option.
- SITL only serves **raw TCP** on `5761`.

Bridge the gap with the included proxy:

```bash
# 1. start SITL (standalone, or ./run.sh tier3 which supervises it)
.betaflight/obj/main/betaflight_SITL.elf
# 2. start the TCP -> WebSocket proxy
.venv/bin/python tier3/sitl_ws_proxy.py       # ws://localhost:5762 -> tcp 127.0.0.1:5761
```

Then in **Chrome/Edge** at [app.betaflight.com](https://app.betaflight.com):

1. Open **Options** (gear icon) and enable **manual connection mode**
   (the default USB/Bluetooth/DFU dropdown has no TCP/SITL entry — this is why
   "Connect" appears to do nothing for SITL until manual mode is on).
2. In the port dropdown pick **Manual**, enter `ws://localhost:5762`, click **Connect**.

The App speaks MSP over the WebSocket; the proxy forwards it to SITL's UART1. Verified
against our firmware (MSP API 1.48). Because the proxy uses port 5761 (MSP/CLI) and the
bridge flies over UDP (9002–9004), you can run `./run.sh tier3` and the App/proxy at the
same time and watch the quad move as the agent flies. Start the proxy/App after the
bridge prints `[bridge] READY` so you don't collide with its one-time config phase.

## Frames & sign conventions

- Physics/state use **body-FRD** (forward-right-down) and **world-NED**.
- FDM gyro is sent as **raw FRD body rates — identity mapping** (`GYRO_TO_BF =
  (1, 1, 1)` in `bf_link.py`). This was determined empirically with single-axis
  tests; composed with Betaflight's internal attitude sign conventions it is the
  mapping that keeps roll→East, pitch→North, and yaw-hold correct.
- Stick → motion (angle mode): `+roll stick (>1500) → +East`,
  `+pitch stick (>1500) → nose-forward → +North`. The position controller therefore
  uses `roll = MID + KP_VEL·right_err` and `pitch = MID + KP_VEL·fwd_err`.
- RC channels are **AETR**: `[0]=roll [1]=pitch [2]=throttle [3]=yaw
  [4]=AUX1(arm) [5]=AUX2(angle)`; `RC_MIN/MID/MAX = 1000/1500/2000`.

## Why the bridge is built the way it is (gotchas)

These cost real debugging time; keep them in mind before changing the loop.

1. **Strict 1:1 lock-step.** Betaflight SITL unlocks exactly **one** motor/servo
   packet per **one** FDM packet (via an internal mutex), and derives its clock from
   the FDM `timestamp`. The main loop therefore **advances an explicit sim clock every
   exchange** and **paces to wall-clock**. If you hold the timestamp constant, only one
   servo packet ever comes back and the sim stalls.
2. **Arming sequence.** Betaflight needs the arm switch seen **LOW at boot**, then an
   **OFF→ON transition**, with **throttle LOW at arm**, after a ~5 s boot-grace. The
   bridge streams AUX1-low from the first frame; the agent's arm command supplies the
   transition. The **arm-spool gate** (`ARM_SPOOL_S`) holds throttle at idle for 1.5 s
   after arming so motors spin up before the altitude PID demands lift.
3. **Readiness handshake.** The bridge only reports ready (writes `$NIMBUS_TIER3_READY`
   / prints `[bridge] READY`) after its loop has streamed low-AUX1 RC through BF's
   boot-grace. `run.sh` waits for this before starting the agent, so the agent's first
   arm command lands as a clean OFF→ON transition and no ZMQ commands are dropped.
4. **BF stdout is fully buffered** to pipes/files and lost on terminate — to see BF's
   own log lines (`Arming disabled: ...`) during debugging, read it from a **PTY**
   (`pty.openpty()`), not a normal pipe.
5. **Stale BF instances hold port 5761** (UART1 CLI); a new instance then dies with
   SIGTRAP ("bind port 5761 failed"). Ensure a clean slate: `pgrep -fl betaflight_SITL`
   and kill leftovers before relaunching.

## One-time Betaflight config (applied automatically)

`bridge.configure_betaflight()` pushes this over the CLI (TCP 5761) and `save`s it to
`eeprom.bin` on first run: `feature -GPS`, `aux 0 0 0 1700 2100` (ARM on AUX1),
`aux 1 1 1 1700 2100` (ANGLE on AUX2), `set small_angle = 180`,
`set runaway_takeoff_prevention = OFF`. Re-run the bridge after rebuilding the binary
so the fresh firmware re-persists this config.

## Ports

| Port | Dir | Purpose |
| ---- | --- | ------- |
| 7771 | agent → bridge | Nimbus commands (SUB) |
| 7772 | bridge → agent | Nimbus state / telemetry / waypoint_status (PUB) |
| 9002 | BF → bridge | motor PWM (bridge binds) |
| 9003 | bridge → BF | FDM state (IMU/attitude/pos) |
| 9004 | bridge → BF | RC channels |
| 5761 | TCP | Betaflight UART1 CLI (config only) |
