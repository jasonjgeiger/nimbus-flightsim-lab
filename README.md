# Experimenting with Droneforge Nimbus (NimbusOS) SDK Against a Flight Simulator

A setup guide and knowledge base for prototyping autonomy agents on the **NimbusOS SDK**
*before* buying a Nimbus module or drone. The goal: run agent code in a closed loop against
a simulator instead of real hardware.

> **Status note:** NimbusOS is actively evolving and its docs "are expected to change to
> always represent the newest release." Re-check the official docs before each build:
> - Product: https://thedroneforge.com/ and https://thedroneforge.com/specifications
> - SDK docs: https://droneforge.gitbook.io/droneforge-docs
> - SDK source/examples: https://github.com/Droneforge-Inc/NimbusOS-sdk-sandbox
> - Desktop app notes: https://github.com/droneforge/NimbusOS-Desktop
> - PyPI: `nimbusos-sdk`

---

## Quick setup (automated)

Clone the repo, then run the script for your platform. Each script installs Python + Git (if
missing), creates a `.venv`, and installs `nimbusos-sdk` + `pyzmq`. Both are idempotent.

**Windows on ARM (ARM64):**
```powershell
git clone https://github.com/jasonjgeiger/nimbus-flightsim-lab.git
cd nimbus-flightsim-lab
pwsh -ExecutionPolicy Bypass -File .\scripts\setup-windows-arm.ps1
.\.venv\Scripts\Activate.ps1
```

**macOS (Apple Silicon or Intel):**
```bash
git clone https://github.com/jasonjgeiger/nimbus-flightsim-lab.git
cd nimbus-flightsim-lab
chmod +x scripts/setup-macos.sh
./scripts/setup-macos.sh
source .venv/bin/activate
```

After activation, jump to **Section 8** for the day-one workflow. For manual setup, see
**Section 4**.

---

## 1. How Nimbus actually works (the mental model)

Understanding the architecture is what makes simulation possible.

- **Nimbus** is a ~10 g **ground-side** module. It does *not* fly on the drone. It plugs into
  your computer and talks to an **ExpressLRS**-based drone wirelessly (control + analog video +
  telemetry, ~15 ms latency, up to ~1 km).
- **NimbusOS** (internally **DF1**) is the desktop software that runs the autonomy stack on your
  PC: perception/AI, mapping, route planning, guidance, and control. The drone just executes
  commands and reports flight state.
- Because *all the intelligence runs on your laptop*, the drone is effectively a
  "dumb" actuator + sensor endpoint. **This is the key insight**: if you can feed NimbusOS (or
  the SDK) simulated state and absorb its commands, you never need the physical aircraft to
  develop and test agent logic.

**Target hardware (for context, so your sim mirrors reality):** ExpressLRS multicopters with a
**Betaflight**-compatible flight controller, an optical-flow/rangefinder sensor (e.g. MTF-02),
and analog or HDMI-out video.

### Two places you can build an "agent"

1. **NimbusOS Desktop (node/expression editor)** — a visual, node-based agent builder. Blocks
   are wired together and driven by *expressions* (spreadsheet-like formulas). Good for quick
   behaviors; runs inside the app.
2. **Python SDK (`nimbusos-sdk`)** — a code-first wrapper around NimbusOS's ZeroMQ pub/sub
   topics. This is the path most useful for "experimenting with agents" and the focus of this
   document.

---

## 2. The integration contract: ZeroMQ pub/sub

The SDK does **not** talk to the drone directly. It talks to a running **NimbusOS instance**
over **ZeroMQ (ZMQ)** using **FlatBuffers**-encoded messages. This decoupling is exactly what
lets you substitute a simulator for NimbusOS.

| Direction | What flows | Default endpoint | Override |
| --------- | ---------- | ---------------- | -------- |
| **Publish** (SDK → NimbusOS) | commands | `tcp://127.0.0.1:7771` | `DF_ZMQ_PUB_ENDPOINT` env var or `NimbusClient(pub_endpoint=...)` |
| **Subscribe** (NimbusOS → SDK) | state/telemetry/video | `tcp://127.0.0.1:7772` | `DF_ZMQ_SUB_ENDPOINT` env var or `NimbusClient(sub_endpoint=...)` |

### Topics you can subscribe to (state coming *from* NimbusOS)

| Topic | Typed helper | Payload |
| ----- | ------------ | ------- |
| `telemetry` | `client.telemetry()` | battery, attitude (deg), link quality |
| `selected_state` | `client.selected_state()` | local-frame position, velocity, attitude, orientation |
| `camera` | `client.camera_frames()` | core-selected JPEG stream |
| `live_camera` | `client.live_camera_frames()` | raw JPEG stream (pre-selection) |
| `waypoint_status` | `client.waypoint_status()` | active waypoint progress, reached/held, distance |
| `autonomy_status` | `client.autonomy_status()` | high-level state (e.g. `idle`, `landing`, `landed_manual`) |
| `camera_overlay` | `client.subscribe_camera_overlay()` | inference overlay drawing instructions |

### Topics you can publish to (commands going *to* NimbusOS)

| Topic | Method | Meaning |
| ----- | ------ | ------- |
| `arm_state` | `client.publish_arm_state(armed)` | arm / disarm |
| `autonomy_request` | `client.publish_autonomy_request("takeoff"\|"land"\|"return_home"\|"relative_waypoint", ...)` | high-level flight request |
| `autonomy_request` | `client.publish_relative_waypoint(forward, right, down, mode, threshold_m, hold_time_s)` | body-frame waypoint convenience helper |
| `waypoint_speed` | `client.publish_waypoint_speed(speed_mps)` | path speed, **0.05–0.75 m/s** |
| `yaw_turn_command` | `client.publish_yaw_turn_command(delta_yaw_rad)` | relative yaw turn (radians) |
| `camera_overlay` | `client.publish_camera_overlay(...)` | draw boxes/labels on the camera view |

### Key typed data objects (what your agent reads)

- `Telemetry` → `seq, t_ns, battery, attitude, link`
  - `BatteryTelemetry(voltage, current, remaining_capacity)`
  - `AttitudeTelemetry(roll_deg, pitch_deg, yaw_deg)`
  - `LinkTelemetry(uplink_link_quality, rf_mode)`
- `State` (selected_state) → `seq, t_ns, valid, position, velocity, forward, right, attitude, orientation`
  - `LocalFramePosition(x_m, y_m, z_m)`, `LocalFrameVelocity(x_mps, y_mps, z_mps)`
  - `StateAttitude(roll_deg, pitch_deg, yaw_deg)`, `StateOrientation(w, x, y, z)`
- `CameraFrame` → `seq, t_ns, width, height, jpeg`
- `WaypointStatus` → `active, reached, held, distance_m, waypoint_index, ...`
- `AutonomyStatus` → `seq, t_ns, status`

> **Coordinate/units conventions to mirror in your sim:** body-frame commands use
> `forward` (+ = forward), `right` (+ = right), `down` (+ = down), meters. Attitude is exposed
> in **degrees** in the typed SDK objects (converted from radians on the wire). Waypoint speed
> is clamped to **0.05–0.75 m/s**.

---

## 3. Does Nimbus ship a simulator? (Honest answer)

**No first-party SITL/simulator is documented today.** The docs and CLI repeatedly say to run
commands "only against a safe vehicle, **simulator**, or controlled NimbusOS test environment,"
and the SDK lets you point at any host via `--pub-endpoint` / `--sub-endpoint` — but Droneforge
does not (yet) publish a downloadable simulator or a documented SITL mode.

That leaves three practical ways to experiment before buying hardware, in increasing realism
and effort. **Start with Tier 1**, then move up.

### ⚠️ The one real gotcha: the wire format is FlatBuffers

The SDK **decodes** state messages as FlatBuffers into typed dataclasses. To make the *typed*
subscription helpers (`client.telemetry()`, `client.selected_state()`, ...) return data, your
simulator must publish bytes in the **exact FlatBuffer schema** NimbusOS uses. Those schemas are
not part of the public docs today. Plan around this:

- **Easiest / fully supported:** don't fake the *state* stream at all. Design and validate your
  agent's **command** logic, and observe it with the CLI / your own raw ZMQ SUB socket (you
  control decoding). See Tier 1.
- **Medium:** build a **raw-topic** simulator. Your agent uses `client.subscribe_*` (raw
  `ReceivedMessage`, `.payload` bytes) and your sim publishes a format *you* define — you own
  both ends, so no schema dependency. You lose the typed helpers but gain a full closed loop.
- **Best fidelity, needs schemas:** get the FlatBuffer schemas (ask Droneforge, or read them
  from the installed `nimbusos_sdk` package / NimbusOS app) and have your sim emit
  schema-accurate messages so the **typed** helpers work unchanged. This is the only path that
  exercises your production agent code byte-for-byte.

> Before investing in Tier 2/3, check the installed package for `.fbs` schema files or generated
> Python modules:
> ```bash
> pip show -f nimbusos-sdk
> python -c "import nimbusos_sdk, os; print(os.path.dirname(nimbusos_sdk.__file__))"
> ```
> and email Droneforge to confirm whether an official simulator/SITL or the schemas are
> available. It will save you the most time.

---

## 4. Prerequisites & SDK install

**Requirements**
- Python **>=3.10, <4.0**
- A ZMQ endpoint to talk to (NimbusOS, or your simulator from Tier 2/3)
- `pip` or `uv`

**Install**
```bash
# with pip
pip install nimbusos-sdk pyzmq

# or with uv
uv add nimbusos-sdk pyzmq
```

**Verify the install and CLI tools**
```bash
python -c "from nimbusos_sdk import NimbusClient; print(NimbusClient)"
nimbusos-subscribe --help
nimbusos-arm --help
nimbusos-autonomy-request --help
nimbusos-waypoint-speed --help
nimbusos-yaw-turn-command --help
```

**Point the SDK at a simulator instead of localhost NimbusOS**
```bash
export DF_ZMQ_PUB_ENDPOINT=tcp://127.0.0.1:7771   # SDK publishes commands here
export DF_ZMQ_SUB_ENDPOINT=tcp://127.0.0.1:7772   # SDK subscribes to state here
# or per-call:
nimbusos-subscribe telemetry --sub-endpoint tcp://127.0.0.1:7772 --limit 1 --timeout 5
```
Or in code:
```python
from nimbusos_sdk import NimbusClient
client = NimbusClient(
    pub_endpoint="tcp://127.0.0.1:7771",
    sub_endpoint="tcp://127.0.0.1:7772",
)
```

---

## 5. Tier 1 — Command-side dry run (no physics, fully supported)

Fastest way to start "today." You run your agent, publish real commands, and watch them on a
raw subscriber. No simulator needed.

**Terminal A — watch what your agent commands (raw sink):**
```python
# sink.py — a tiny observer that prints raw command frames.
import zmq

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.SUB)
sock.bind("tcp://127.0.0.1:7771")      # bind where the SDK will connect to publish
sock.setsockopt_string(zmq.SUBSCRIBE, "")
print("listening for agent commands on 7771 ...")
while True:
    parts = sock.recv_multipart()
    topic = parts[0].decode(errors="replace")
    payload = parts[1] if len(parts) > 1 else b""
    print(f"CMD topic={topic} bytes={len(payload)}")
```

**Terminal B — your agent:**
```python
# agent_smoke.py
from nimbusos_sdk import NimbusClient

with NimbusClient() as client:
    client.publish_arm_state(True)
    client.publish_waypoint_speed(0.45)
    client.publish_autonomy_request("takeoff")
    client.publish_relative_waypoint(forward=1.5, right=0.0, down=0.0, mode="override")
    client.publish_autonomy_request("land")
```

This verifies your command sequencing, argument validation, and control flow. You just won't get
feedback (telemetry/waypoint completion) — that's Tier 2/3.

> ZMQ topic framing: NimbusOS uses multipart messages where the first frame is the topic string.
> Confirm exact framing against the SDK source before relying on it; adjust `recv_multipart`
> parsing accordingly.

---

## 6. Tier 2 — Kinematic mock NimbusOS (closed loop, you own both ends)

Build a small Python process that plays the role of NimbusOS: it **subscribes** to your agent's
commands on `7771` and **publishes** simulated state on `7772`, integrating a simple point-mass
model. Because you control both the sim and the agent's decode, use the SDK's **raw**
subscriptions (`client.subscribe_selected_state`, etc.) with a payload format you define — this
sidesteps the FlatBuffer-schema dependency.

```
        publish commands (7771)                 subscribe state (7772)
  ┌───────────┐  ───────────────▶  ┌─────────────────┐  ───────────────▶  ┌───────────┐
  │  Your     │   arm/takeoff/     │  Mock NimbusOS   │  selected_state/   │  Your     │
  │  Agent    │   waypoint/yaw     │  (point-mass +   │  telemetry/        │  Agent    │
  │ (SDK pub) │                    │  waypoint logic) │  waypoint_status   │ (raw sub) │
  └───────────┘                    └─────────────────┘                    └───────────┘
```

**Mock skeleton (`mock_nimbus.py`):**
```python
import time, threading, zmq

ctx = zmq.Context.instance()

# Commands FROM the agent (SDK connects & publishes to 7771).
cmd = ctx.socket(zmq.SUB)
cmd.bind("tcp://127.0.0.1:7771")
cmd.setsockopt_string(zmq.SUBSCRIBE, "")

# State TO the agent (SDK connects & subscribes on 7772).
state = ctx.socket(zmq.PUB)
state.bind("tcp://127.0.0.1:7772")

# Minimal drone state (local frame, meters).
pos = {"x": 0.0, "y": 0.0, "z": 0.0}
target = dict(pos)
armed = False
seq = 0

def handle_commands():
    global armed, target
    while True:
        parts = cmd.recv_multipart()
        topic = parts[0].decode(errors="replace")
        # NOTE: real payloads are FlatBuffers. In a self-owned loop you can define your own
        # command decoding, or parse the SDK's frames once you confirm the schema/framing.
        if topic == "arm_state":
            armed = True
        elif topic == "autonomy_request":
            # e.g. decode forward/right/down and set target += offsets
            target["x"] += 1.5   # placeholder
        print(f"[mock] rx {topic}")

def integrate_and_publish():
    global seq
    dt = 0.05
    while True:
        # Simple first-order approach toward target.
        for a in ("x", "y", "z"):
            pos[a] += (target[a] - pos[a]) * 0.1
        seq += 1
        # Publish YOUR-defined state payload; agent reads it via client.subscribe_selected_state
        state.send_multipart([
            b"selected_state",
            f"{seq},{pos['x']:.3f},{pos['y']:.3f},{pos['z']:.3f}".encode(),
        ])
        time.sleep(dt)

threading.Thread(target=handle_commands, daemon=True).start()
integrate_and_publish()
```

**Agent side (raw subscription so no schema needed):**
```python
from nimbusos_sdk import NimbusClient

with NimbusClient() as client:
    client.publish_arm_state(True)
    client.publish_autonomy_request("takeoff")
    for msg in client.subscribe_selected_state(timeout_sec=10.0):
        seq, x, y, z = msg.payload.decode().split(",")
        print(f"pos=({x},{y},{z})")
```

**What you get:** true closed-loop iteration on guidance logic (waypoint following, yaw control,
hold/threshold behavior), reproducible and fast, on Windows/macOS/Linux with only `pyzmq`.

**What you don't get:** real physics, realistic camera imagery, or byte-compatibility with the
*typed* SDK helpers (unless you obtain the FlatBuffer schemas). Add fake `telemetry` and
`waypoint_status` topics the same way to exercise more of your agent.

---

## 7. Tier 3 — Bridge to a real flight simulator (high fidelity)

> **Built & working:** this repo ships a complete Tier 3 bridge for **Betaflight SITL**
> in [`tier3/`](tier3/) — run it with `./run.sh tier3`. It arms, takes off, holds
> altitude, and tracks horizontal waypoints with the real Betaflight firmware (PIDs +
> QUADX mixer) in the loop. See [`tier3/README.md`](tier3/README.md) for how to run it,
> the required build flag (`ENABLE_GAZEBO_BRIDGE=0`), frame/sign conventions, and the
> arming/lock-step gotchas. The rest of this section is the design rationale behind it.

### 7.1 Run it — step by step (command order)

Everything runs locally on macOS. Do these in order from the repo root.

**One-time: build the Betaflight SITL firmware.** The `OPTIONS` flag is mandatory
(a bare `make TARGET=SITL` turns the Gazebo bridge on, which rotates the attitude
frame 90° and makes the quad diverge):

```bash
cd .betaflight
make TARGET=SITL OPTIONS="ENABLE_GAZEBO_BRIDGE=0"   # ~30 s clean, ~7 s incremental
cd ..
# produces .betaflight/obj/main/betaflight_SITL.elf
```

**Every run: fly the full mission.** One command starts and supervises everything —
it boots Betaflight, one-time-configures it (arm + angle mode over the CLI), waits for
a readiness handshake, then launches the orbit agent:

```bash
source .venv/bin/activate         # if not already active
./run.sh tier3                    # bridge + agents/orbit_agent.py
./run.sh tier3 agents/your.py     # or a different agent
```

**What healthy output looks like** — the quad arms, takes off, flies a 1 m square
(4 legs, 90° yaw turn between each), lands, and disarms:

```
==> Waiting for Betaflight bridge to become ready ...
[bridge] configuration saved to eeprom.bin
[bridge] READY (Betaflight armable; agent may connect).
[orbit] leg 1/4 -> forward=1.0 right=0.0
[orbit]   reached (distance=0.13 m)
 ... legs 2-4 ...
[orbit] done: landed and disarmed.
```

Stop anytime with `Ctrl-C`; the bridge tears Betaflight down on exit.

**Run the bridge and agent in separate terminals** (useful while iterating on an agent):

```bash
# terminal A — the world (bridge + Betaflight). Wait for "[bridge] READY".
.venv/bin/python tier3/bridge.py
# terminal B — any agent, once A is ready
.venv/bin/python agents/orbit_agent.py
```

### 7.2 Watch it live in the Betaflight App (Chrome)

You can open the Betaflight App and watch attitude / receiver channels / motors while
the bridge flies. On current macOS there is **no native desktop Betaflight app** — it's
a browser PWA at [app.betaflight.com](https://app.betaflight.com), and its SITL
connection is a **WebSocket**, while SITL only speaks **raw TCP** on port 5761. Bridge
that gap with the included proxy:

```bash
# with SITL already running (./run.sh tier3, or the .elf directly):
.venv/bin/python tier3/sitl_ws_proxy.py     # ws://localhost:5762  ->  tcp 127.0.0.1:5761
```

Then, in **Chrome or Edge** (not Safari) at app.betaflight.com:

1. Open **Options** (gear icon) and turn on **manual connection mode**. Without this the
   only choices are USB/Bluetooth/DFU and **Connect does nothing** for SITL.
2. In the port dropdown choose **Manual**, type `ws://localhost:5762`, click **Connect**.
3. The **Setup** tab shows live attitude; the **Receiver** tab shows the RC channels
   moving as the agent flies.

The proxy uses the CLI/MSP port (5761) while the bridge flies over UDP (9002–9004), so
you can run `./run.sh tier3` and the App/proxy together. Start the App/proxy **after**
you see `[bridge] READY` — during the one-time config phase Betaflight restarts and
5761 briefly drops (the proxy retries for ~5 s to smooth this over).

### 7.3 Troubleshooting

| Symptom | Cause & fix |
| ------- | ----------- |
| `bind port 5761 failed` / SITL won't start | A stale Betaflight is still running. `pgrep -fl betaflight_SITL`, then kill the PID. |
| Proxy: `cannot reach SITL at 127.0.0.1:5761` | SITL isn't up yet (or mid-restart). Wait for `[bridge] READY`, then Connect again. |
| App only offers USB/Bluetooth/DFU | Manual connection mode isn't enabled (Options → enable it), or you used Safari. |
| Quad diverges / climbs away | Firmware built without `ENABLE_GAZEBO_BRIDGE=0`. Rebuild with the flag, then re-run the bridge so it re-persists its config. |
| No output from bridge/agent | Python buffers to pipes; prefix with `PYTHONUNBUFFERED=1` to see logs live. |

For frame/sign conventions, the lock-step timing, and the arming sequence in depth, see
[`tier3/README.md`](tier3/README.md).

For realistic dynamics, sensors, and camera frames, run an established SITL simulator and write
a **bridge** that maps sim ↔ Nimbus topics. The bridge replaces the "point-mass" core of Tier 2
with a physics engine.

```
 ┌────────────┐  Nimbus ZMQ   ┌───────────────┐  sim API (MAVLink/  ┌──────────────────┐
 │ Your Agent │ ◀───────────▶ │  Nimbus↔Sim   │  UDP/RPC)           │  Flight Simulator │
 │  (SDK)     │  7771 / 7772  │   Bridge      │ ◀─────────────────▶ │  (physics+camera) │
 └────────────┘               └───────────────┘                     └──────────────────┘
```

**Simulator options (pick based on what you want to test):**

| Simulator | Why pick it | Trade-offs |
| --------- | ----------- | ---------- |
| **Betaflight SITL** | Closest to Nimbus's real target (drones use Betaflight FCs; Desktop uses CRSF 172–1811 control values). Great for control-level realism. | Bare-bones visuals; you add environment/camera separately. |
| **PX4 SITL + Gazebo** | Rich physics, sensors, worlds; huge community; MAVLink. | Heavier setup; MAVLink ≠ Nimbus semantics, so the bridge does more translation. Linux-first. |
| **Microsoft AirSim / Colosseum** | Photoreal camera → ideal for testing the **vision** side (feeds `camera`/overlay). Unreal Engine. | Large; camera realism is its strength, flight model less so. |
| **ArduPilot SITL** | Mature, scriptable, MAVLink. | Same MAVLink-translation caveat as PX4. |

**Bridge responsibilities:**
1. **State out:** read sim position/velocity/attitude → publish Nimbus `selected_state` +
   `telemetry`; render/forward camera frames as JPEG → `camera` / `live_camera`.
2. **Commands in:** subscribe to Nimbus `arm_state`, `autonomy_request`, `waypoint_speed`,
   `yaw_turn_command` → translate into the sim's control interface. For high-level
   `autonomy_request` (takeoff/land/waypoint) you'll implement a small guidance loop that turns
   waypoints into attitude/throttle (or use the sim autopilot's offboard/guided mode).
3. **Waypoint feedback:** track distance-to-target and emit `waypoint_status`
   (`active/reached/held/distance_m`) and `autonomy_status`.

**Control mapping reference (from NimbusOS Desktop expressions):** the real control channel uses
**CRSF range 172–1811**, throttle low = 172, roll/pitch/yaw centered at **992** (>992 =
right/forward/CW). If you bridge at the raw-control level (e.g. Betaflight SITL), map your
agent's intent into this range so behavior matches real hardware.

**Recommended starting combo:** **Betaflight SITL** (control realism matching the real FC) for
flight behavior, plus **AirSim** later if/when you need photoreal camera input for vision
agents. Reuse the Tier 2 ZMQ scaffolding; swap the point-mass integrator for the sim connection.

> As with Tier 2, the typed SDK helpers require schema-accurate FlatBuffer output from your
> bridge. If you only have raw subscriptions, keep your agent on `client.subscribe_*`. If you
> obtain the schemas, emit real FlatBuffers and your agent runs unmodified against sim and real
> hardware alike.

---

## 8. Day-one workflow: build & test your first agent

A repeatable loop to run **after everything is installed** (Section 4 done). Assumes Tier 2 for a
real closed loop; if you're on Tier 1, skip the mock and just watch commands on the raw sink.

### Project layout
```
nimbus-lab/
├─ mock_nimbus.py     # Tier 2 simulator (Section 6) — or skip on Tier 1
├─ agents/
│  └─ orbit_agent.py  # your first agent
└─ run.ps1            # convenience launcher (optional)
```

### Step 0 — Sanity check the toolchain (once)
```bash
python -c "from nimbusos_sdk import NimbusClient; print('SDK OK')"
nimbusos-subscribe --help
```

### Step 1 — Start the "world"
Open a dedicated terminal and leave it running for the whole session.

- **Tier 2 (sim):** `python mock_nimbus.py`  → binds `7771` (commands in) and `7772` (state out).
- **Tier 3 (real sim):** `./run.sh tier3` starts the Betaflight SITL bridge (see [`tier3/README.md`](tier3/README.md)); it launches the agent for you once the bridge is ready.
- **Tier 1 (no feedback):** `python sink.py` (Section 5) to observe commands only.

> Point the SDK at it (once per shell):
> ```powershell
> $env:DF_ZMQ_PUB_ENDPOINT = "tcp://127.0.0.1:7771"
> $env:DF_ZMQ_SUB_ENDPOINT = "tcp://127.0.0.1:7772"
> ```

### Step 2 — Verify the link before writing agent logic
In a second terminal, confirm state is actually flowing:
```bash
nimbusos-subscribe selected_state --limit 1 --timeout 5
nimbusos-subscribe telemetry     --limit 1 --timeout 5
```
If nothing arrives: check the endpoints, that the sim bound the sockets, and (for typed helpers)
that your sim emits schema-accurate FlatBuffers — otherwise use `client.subscribe_*` raw
subscriptions (Section 3).

### Step 3 — Write the first agent (a "person orbit"-style loop)
Start from a known-good shape: **arm → takeoff → sense/act loop → land → disarm**.
```python
# agents/orbit_agent.py
import math
from nimbusos_sdk import NimbusClient

def run():
    with NimbusClient() as client:
        # --- launch ---
        client.publish_arm_state(True)
        client.publish_waypoint_speed(0.35)          # 0.05–0.75 m/s
        client.publish_autonomy_request("takeoff")

        # --- act loop: fly a small square as 4 relative legs ---
        legs = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]  # (forward, right) meters
        for forward, right in legs:
            client.publish_relative_waypoint(
                forward=forward, right=right, down=0.0,
                mode="override", threshold_m=0.15, hold_time_s=0.5,
            )
            # wait for this leg to finish (bounded)
            for status in client.waypoint_status(timeout_sec=15.0):
                if status.reached and status.held:
                    break
            client.publish_yaw_turn_command(math.pi / 2)  # turn 90° between legs

        # --- recover ---
        client.publish_autonomy_request("land")
        client.publish_arm_state(False)

if __name__ == "__main__":
    run()
```

### Step 4 — Run and watch
```bash
python agents/orbit_agent.py
```
Watch three things simultaneously (three terminals):
1. **Sim/bridge terminal** — confirms it receives `arm_state`, `autonomy_request`, `yaw_turn_command`.
2. `nimbusos-subscribe selected_state --timeout 30` — confirms the position moves as commanded.
3. Agent stdout — confirms your control flow and waypoint-reached logic.

### Step 5 — Close the loop with perception (optional, when ready)
Add a sense step so the agent reacts instead of flying blind. Example: pull a camera frame,
run *your* detector, draw an overlay, and steer:
```python
for frame in client.latest_camera_frames(timeout_sec=1.0):
    # box = my_detector(frame.jpeg)  -> (x, y, w, h)
    from nimbusos_sdk import box
    client.publish_camera_overlay(
        camera_seq=frame.seq, frame_width=frame.width, frame_height=frame.height,
        source="detector",
        layers=[{"name": "detections", "primitives": [box(120, 80, 180, 240, label="target")]}],
    )
    # steer toward target center, e.g. right = k * (target_x - frame.width/2)
    break
```
(For overlays/vision you need a real camera stream — a Tier 3 sim like AirSim, or real hardware.)

### Step 6 — Iterate
Edit the agent, re-run Step 4. Because the sim is stateful, restart `mock_nimbus.py` between runs
for a clean start. Tighten `threshold_m`, tune speeds, add branches (e.g. abort on low
`telemetry.battery.voltage`), then graduate the same agent to Tier 3 and finally real hardware by
only changing what's behind the ZMQ endpoints.

### Definition of done for "first agent"
- Arms, takes off, completes all legs with `waypoint_status.reached && held`, lands, disarms.
- No `ValueError` from argument validation (speeds in range, valid request/mode).
- Runs identically after a sim restart (deterministic, hardware-free).

---

## 9. Suggested experimentation roadmap

1. **Install & smoke test (Tier 1).** Confirm `nimbusos-sdk` imports, CLI works, and you can see
   your own commands on a raw ZMQ sink. *No drone, no sim.*
2. **Clone the sandbox.** Read `getting_started.py`, `set_waypoint_speed.py`,
   `commanding_yaw.py`, `next_steps.py` in `NimbusOS-sdk-sandbox` to learn the real command
   patterns (arm → takeoff → waypoints → land → disarm).
3. **Confirm the wire format.** Inspect the installed package for `.fbs`/generated schemas and
   ask Droneforge whether an official simulator or schemas exist. This decides Tier 2 vs Tier 3
   fidelity.
4. **Build the Tier 2 kinematic mock.** Get a full closed loop (command → motion → state) and
   iterate on guidance/mission logic.
5. **Graduate to Tier 3** when you need real physics (Betaflight SITL) or photoreal vision
   (AirSim). Keep the same agent code; only the "core" behind the ZMQ endpoints changes.
6. **Design agents in the Desktop editor** in parallel — node/expression agents are a good way
   to learn Nimbus control semantics (CRSF ranges, vision-target variables, PID/`lin`/`mem`
   helpers) and to compare against your SDK agents.
7. **Buy hardware with confidence.** Because the drone is just the actuator/sensor endpoint,
   agents validated against a faithful sim (esp. Betaflight SITL + real FlatBuffer schemas)
   should transfer with minimal changes — swap endpoints back to a live NimbusOS instance.

---

## 10. Safety & gotchas

- **Always test publish commands against a simulator or safe/controlled environment** — never a
  live drone near people. The docs state this explicitly.
- **Waypoint speed is clamped 0.05–0.75 m/s**; out-of-range values raise `ValueError` before
  publishing. Many args are validated (finite numbers, `mode` ∈ {override, queue}, request types,
  etc.) — mirror these in your sim so behavior matches.
- **Units:** body-frame meters for waypoints (forward/right/down), degrees for attitude in typed
  objects, radians for `yaw_turn_command`.
- **NimbusOS is required for the *live* typed workflow.** Your simulator is standing in for it;
  the fidelity of that substitution is bounded by whether you can produce schema-accurate
  messages (Section 3).
- **The product is changing fast.** Topic names, methods (`publish_autonomy_request`,
  `publish_relative_waypoint`, `selected_state`, `autonomy_status`, `camera_overlay`), and
  packaging can change between releases — re-verify against the current docs and SDK source each
  time you start a build.

---

## 11. Quick reference

**Endpoints**
```
Publish (commands):   tcp://127.0.0.1:7771   (DF_ZMQ_PUB_ENDPOINT)
Subscribe (state):    tcp://127.0.0.1:7772   (DF_ZMQ_SUB_ENDPOINT)
```

**CLI smoke tests**
```bash
nimbusos-subscribe telemetry --limit 1 --timeout 5
nimbusos-subscribe selected_state --limit 1 --timeout 5
nimbusos-arm
nimbusos-autonomy-request takeoff
nimbusos-autonomy-request relative_waypoint --mode override --forward 1.5 --right 0.0 --down 0.0
nimbusos-waypoint-speed 0.45
nimbusos-yaw-turn-command 0.52
```

**Minimal agent loop**
```python
from nimbusos_sdk import NimbusClient

with NimbusClient() as client:
    client.publish_arm_state(True)
    client.publish_waypoint_speed(0.45)
    client.publish_autonomy_request("takeoff")
    client.publish_relative_waypoint(forward=1.5, right=0.0, down=0.0, mode="override")
    for status in client.waypoint_status(timeout_sec=10.0):
        if status.reached:
            break
    client.publish_autonomy_request("land")
    client.publish_arm_state(False)
```

**Control mapping (real hardware / Betaflight SITL)**
```
CRSF range: 172–1811   throttle low = 172   roll/pitch/yaw center = 992
>992 = right / forward / clockwise ;  <992 = left / back / counter-clockwise
```

---

## 12. Natural-language mission control (web app)

Type a mission in plain English ("fly forward 20 ft, then go up 100 ft and
hover"), review the compiled plan, then fly it against whatever "world" is
listening on the ZMQ endpoints — the Tier 2 mock, the Tier 3 Betaflight SITL
bridge, or (eventually) a real NimbusOS drone. **The web app *is* the agent;**
switching sim ↔ real drone is just a matter of which world is running.

Pipeline: **English → Mission IR (strict JSON) → validate (units + safety
caps) → executor → ZMQ**. The natural-language layer sits *outside* the safety
boundary — every mission is dead-reckoned against altitude/geofence/speed caps
*before* a single command is published. See
[`docs/mission-control/`](docs/mission-control/) for the design and the IR
schema, and [`webui/README.md`](webui/README.md) for full details.

### 12.1 Run it — step by step

```bash
source .venv/bin/activate

# 1) Start a world (pick ONE), and wait for it to be ready:
.venv/bin/python mock_nimbus.py          # Tier 2 kinematic mock (instant), OR
.venv/bin/python tier3/bridge.py         # Tier 3 Betaflight SITL — wait for "[bridge] READY"

# 2) Start the web app (in another terminal):
.venv/bin/python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000

# 3) Open http://127.0.0.1:8000 in your browser.
```

In the browser: type the mission → **Compile** → review/edit the IR and the
plain-English preview (invalid missions are rejected with a reason) →
**Confirm & Fly** → watch the live per-leg log stream. The same `arm →
takeoff → legs → land → disarm` you saw in the Tier 2/3 agents, now driven by
your sentence.

### 12.2 Run a mission from the CLI (no browser)

The executor is a standalone module — handy for scripting and CI:

```bash
# validate + preview only (does not fly)
.venv/bin/python -m mission mission/examples/forward_up_hover.json --dry-run

# fly it against the running world
.venv/bin/python -m mission mission/examples/forward_up_hover.json --yes
```

### 12.3 Tests

```bash
.venv/bin/python -m mission.selftest      # 12 standalone tests (no pytest)
```
