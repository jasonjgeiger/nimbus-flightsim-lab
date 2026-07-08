---
title: Build your first agent
layout: default
nav_order: 7
---

# 6. Build & test your first agent
{: .no_toc }

**Goal:** a repeatable day-one loop that arms, takes off, flies a pattern, lands, and
disarms — the shape every Nimbus agent shares.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

Run this **after setup is done**. There are two ways to run your first agent, and two "worlds"
either can fly against:

- **Ways to run:** **A) the natural-language web app** (no code — type a mission in the browser)
  or **B) a Python agent** you write yourself.
- **Worlds:** the **Tier 2 mock** (instant, pure-Python) or **Tier 3 Betaflight SITL** (real
  firmware in the loop). Your agent doesn't change between them — only what's behind the ZMQ
  endpoints does.

Start with **A on Tier 2** — it's the fastest way to see a full flight.

## Project layout

```
nimbus-flightsim-lab/
├─ mock_nimbus.py     # Tier 2 world (kinematic sim) — binds 7771/7772
├─ tier3/bridge.py    # Tier 3 world (Betaflight SITL bridge)
├─ webui/             # the natural-language mission-control web app
├─ mission/           # Mission IR compiler + validator + executor (used by the web app & CLI)
├─ agents/            # example hand-written agents (e.g. orbit_agent.py)
└─ sink.py            # Tier 1 raw command observer (optional)
```

## Step 1 — Start a "world" (pick one)

Open a dedicated terminal and leave it running for the whole session.

**Tier 2 — kinematic mock (simplest, no build):**
```bash
source .venv/bin/activate
python mock_nimbus.py           # binds 7771 (commands in) and 7772 (state out)
```

**Tier 3 — real Betaflight firmware:** see **[Connect Betaflight](#connect-betaflight)** below,
then come back. Everything after Step 1 is identical for both worlds.

## Step 2 — Fly a mission from the browser (no code)

The web app *is* the agent. Start it in a **second terminal**:

```bash
source .venv/bin/activate
python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000
```

Then open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** and:

1. Type a mission, e.g. `Fly forward 20 ft, then go up 100 ft and hover.`
2. Click **Compile** → review the compiled plan (editable JSON + a plain-English preview).
   Invalid or unsafe missions are rejected with a reason *before* anything flies.
3. Click **Confirm & Fly** → watch the live per-leg log: `arm → takeoff → legs → land → disarm`.

That's your first agent flying. More phrasings to try:

- `Take off, fly forward 10 ft, fly right 10 ft, then land`
- `Fly up 50 ft, turn right 90 degrees, then hover for 5 seconds`

{: .note }
> Prefer the command line? Fly the same mission with no browser:
> `python -m mission mission/examples/forward_up_hover.json --yes`
> (add `--dry-run` to validate + preview without flying). See
> [`webui/README.md`](https://github.com/jasonjgeiger/nimbus-flightsim-lab/blob/main/webui/README.md).

<a name="connect-betaflight"></a>

## Connect Betaflight (Tier 3 — real firmware)

Same browser flow as above, but flying against real Betaflight SITL instead of the mock.

**One-time — build the SITL firmware.** The `OPTIONS` flag is **required** (a bare
`make TARGET=SITL` turns on the Gazebo bridge, which rotates the frame 90° and makes the quad
diverge):

```bash
cd .betaflight
make TARGET=SITL OPTIONS="ENABLE_GAZEBO_BRIDGE=0"   # ~30 s clean, ~7 s incremental
cd ..
```

**Each run — start the bridge instead of the mock** (this replaces Step 1):

```bash
source .venv/bin/activate
python tier3/bridge.py
```

Wait for this line before flying:

```
[bridge] READY (Betaflight armable; agent may connect).
```

The bridge boots Betaflight, configures it once (arm + angle mode over the CLI), and serves the
**same** `7771`/`7772` endpoints. Now do **Step 2** (start the web app, open the browser) exactly
as before — nothing else changes.

**Troubleshooting:**

- *Port `5761` already in use / bridge won't start* — a previous Betaflight SITL is still
  running; stop it, then re-run the bridge.
- *Stuck before `READY`* — Betaflight can be slow to become armable on first boot; give it up to
  ~30 s. If it never arrives, stop and restart the bridge.
- *Want to watch it fly in the Betaflight Configurator?* See
  [Tier 3 — Flight simulator](./tier3-flight-simulator.html).

---

## B. Write your own agent (optional, code)

Prefer code to the browser? Build the classic loop yourself. Keep a **world from Step 1**
running (mock or Betaflight bridge), then:

### B1 — Verify the link before writing agent logic

In a second terminal, confirm state is actually flowing:
```bash
nimbusos-subscribe selected_state --limit 1 --timeout 5
nimbusos-subscribe telemetry     --limit 1 --timeout 5
```
If nothing arrives: check the endpoints, that the sim bound the sockets, and — for typed
helpers — that your sim emits schema-accurate FlatBuffers. Otherwise use raw
`client.subscribe_*` subscriptions.

### B2 — Write the agent

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

{: .note }
> For the authoritative, current signatures of each call above, see the DroneForge
> [Examples](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/examples)
> (arming, takeoff, waypoints, landing) and
> [Publishing](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/publishing).

### B3 — Run and watch

```bash
python agents/orbit_agent.py
```

Watch three things at once (three terminals):
1. **Sim/sink terminal** — confirms it receives `arm_state`, `autonomy_request`, `yaw_turn_command`.
2. `nimbusos-subscribe selected_state --timeout 30` — confirms the position moves as commanded.
3. Agent stdout — confirms your control flow and waypoint-reached logic.

### B4 — Close the loop with perception (optional)

Add a sense step so the agent reacts instead of flying blind — pull a camera frame, run
*your* detector, draw an overlay, and steer:

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

(For overlays/vision you need a real camera stream — a Tier 3 sim like AirSim, or hardware.)

### B5 — Iterate

Edit the agent, re-run **B3**. Because the sim is stateful, restart your world
(`mock_nimbus.py` or `tier3/bridge.py`) between runs for a clean start. Tighten `threshold_m`,
tune speeds, add branches (e.g. abort on low `telemetry.battery.voltage`), then graduate the
same agent to Tier 3 and finally real hardware — changing only what's behind the ZMQ endpoints.

## Definition of done

- A mission flies end-to-end: **arm → takeoff → legs → land → disarm**, either from the web app
  (A) or your own agent (B), against the mock **or** Betaflight SITL.
- Legs complete on `waypoint_status.reached && held`; no `ValueError` from argument validation
  (speeds in range, valid request/mode).
- Runs identically after a world restart (deterministic, hardware-free).

---

**Checkpoint:** a mission completes the full arm → fly → land → disarm cycle — typed into the
web app (or flown by your own agent) — against the Tier 2 mock or Betaflight SITL, and you've
watched each leg track as commanded.

Next → [Transition to Nimbus hardware](./to-hardware.html)
