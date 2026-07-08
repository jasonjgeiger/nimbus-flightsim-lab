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

Run this **after setup is done**. It assumes Tier 2 for a real closed loop; on Tier 1, skip
the mock and just watch commands on the raw sink.

## Project layout

```
nimbus-lab/
├─ mock_nimbus.py     # Tier 2 simulator — or skip on Tier 1
├─ agents/
│  └─ orbit_agent.py  # your first agent
└─ sink.py            # Tier 1 raw command observer (optional)
```

## Step 0 — Sanity check the toolchain (once)

```bash
python -c "from nimbusos_sdk import NimbusClient; print('SDK OK')"
nimbusos-subscribe --help
```

## Step 1 — Start the "world"

Open a dedicated terminal and leave it running for the whole session.

- **Tier 2 (sim):** `python mock_nimbus.py` → binds `7771` (commands in) and `7772` (state out).
- **Tier 1 (no feedback):** `python sink.py` to observe commands only.

Point the SDK at it (once per shell):
```bash
export DF_ZMQ_PUB_ENDPOINT=tcp://127.0.0.1:7771
export DF_ZMQ_SUB_ENDPOINT=tcp://127.0.0.1:7772
```

## Step 2 — Verify the link before writing agent logic

In a second terminal, confirm state is actually flowing:
```bash
nimbusos-subscribe selected_state --limit 1 --timeout 5
nimbusos-subscribe telemetry     --limit 1 --timeout 5
```
If nothing arrives: check the endpoints, that the sim bound the sockets, and — for typed
helpers — that your sim emits schema-accurate FlatBuffers. Otherwise use raw
`client.subscribe_*` subscriptions.

## Step 3 — Write the first agent

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

## Step 4 — Run and watch

```bash
python agents/orbit_agent.py
```

Watch three things at once (three terminals):
1. **Sim/sink terminal** — confirms it receives `arm_state`, `autonomy_request`, `yaw_turn_command`.
2. `nimbusos-subscribe selected_state --timeout 30` — confirms the position moves as commanded.
3. Agent stdout — confirms your control flow and waypoint-reached logic.

## Step 5 — Close the loop with perception (optional)

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

## Step 6 — Iterate

Edit the agent, re-run Step 4. Because the sim is stateful, restart `mock_nimbus.py` between
runs for a clean start. Tighten `threshold_m`, tune speeds, add branches (e.g. abort on low
`telemetry.battery.voltage`), then graduate the same agent to Tier 3 and finally real
hardware — changing only what's behind the ZMQ endpoints.

## Definition of done

- Arms, takes off, completes all legs with `waypoint_status.reached && held`, lands, disarms.
- No `ValueError` from argument validation (speeds in range, valid request/mode).
- Runs identically after a sim restart (deterministic, hardware-free).

---

**Checkpoint:** your agent completes the full arm → fly → land → disarm cycle against the
Tier 2 mock, and you've watched the position track each commanded leg.

Next → [Transition to Nimbus hardware](./to-hardware.html)
