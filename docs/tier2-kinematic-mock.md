---
title: Tier 2 — Kinematic mock
layout: default
nav_order: 5
---

# 4. Tier 2 — Kinematic mock NimbusOS
{: .no_toc }

**Goal:** close the loop. Build a small Python process that plays the role of NimbusOS —
it subscribes to your agent's commands and streams simulated state back — so your guidance
logic actually reacts to motion.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## The idea

Your mock **subscribes** to commands on `7771` and **publishes** simulated state on `7772`,
integrating a simple point-mass model. Because you control both the sim *and* the agent's
decode, use the SDK's **raw** subscriptions (`client.subscribe_selected_state`, …) with a
payload format *you* define. That sidesteps the FlatBuffer-schema dependency entirely — you
own both ends.

```
        publish commands (7771)                 subscribe state (7772)
  ┌───────────┐  ───────────────▶  ┌─────────────────┐  ───────────────▶  ┌───────────┐
  │  Your     │   arm/takeoff/     │  Mock NimbusOS   │  selected_state/   │  Your     │
  │  Agent    │   waypoint/yaw     │  (point-mass +   │  telemetry/        │  Agent    │
  │ (SDK pub) │                    │  waypoint logic) │  waypoint_status   │ (raw sub) │
  └───────────┘                    └─────────────────┘                    └───────────┘
```

## The mock (`mock_nimbus.py`)

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

## The agent (raw subscription — no schema needed)

```python
from nimbusos_sdk import NimbusClient

with NimbusClient() as client:
    client.publish_arm_state(True)
    client.publish_autonomy_request("takeoff")
    for msg in client.subscribe_selected_state(timeout_sec=10.0):
        seq, x, y, z = msg.payload.decode().split(",")
        print(f"pos=({x},{y},{z})")
```

Run the mock in one terminal, the agent in another. You should watch the position converge
toward the target as commands arrive.

## What you get — and what you don't

- ✅ **A true closed loop:** command → motion → state. Iterate on guidance logic (waypoint
  following, yaw control, hold/threshold behavior), reproducibly and fast, with only `pyzmq`.
- ❌ **No real physics, no realistic camera imagery, no byte-compatibility with the *typed*
  SDK helpers** (unless you obtain the FlatBuffer schemas).

Extend the mock by adding fake `telemetry` and `waypoint_status` topics the same way, so
your agent exercises more of its logic (e.g. aborting on low battery, or waiting for
`reached && held`).

{: .highlight }
Tier 2 is where most agent development happens. It's deterministic, hardware-free, and runs
on any OS. Graduate to Tier 3 only when you need real dynamics or camera input.

---

**Checkpoint:** your agent commands a waypoint and *observes* the simulated position move
toward it — a real sense/act loop with no hardware and no schema dependency.

Next → [Tier 3 — Flight simulator](./tier3-flight-simulator.html)
