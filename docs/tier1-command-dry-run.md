---
title: Tier 1 — Command dry run
layout: default
nav_order: 4
---

# 3. Tier 1 — Command-side dry run
{: .no_toc }

**Goal:** run a real agent, publish real commands, and watch them — with zero simulator
and zero physics. This is the fastest way to start *today* and it's fully supported.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## The idea

You run your agent, it publishes commands to `7771`, and a tiny raw subscriber that *you*
control prints them. Because you decode the frames yourself, there's no FlatBuffer-schema
dependency. You verify command sequencing, argument validation, and control flow — you just
won't get feedback (that's Tier 2/3).

## Terminal A — watch what your agent commands

Create `sink.py`, a tiny observer that binds the command port and prints each frame:

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

Run it and leave it open:
```bash
python sink.py
```

## Terminal B — your agent

Create `agent_smoke.py` with a minimal command sequence:

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

Run it:
```bash
python agent_smoke.py
```

In Terminal A you should see one `CMD topic=...` line per published command
(`arm_state`, `waypoint_speed`, `autonomy_request`, …).

{: .note }
> **ZMQ topic framing.** NimbusOS uses multipart messages where the first frame is the
> topic string. Confirm the exact framing against the SDK source before relying on it, and
> adjust the `recv_multipart` parsing accordingly.

## What this proves — and what it doesn't

- ✅ Your command *ordering* and argument *validation* are correct (bad values raise
  `ValueError` before anything is published).
- ✅ Your control flow runs end to end.
- ❌ No telemetry, no waypoint completion, no motion — there's nothing feeding state back.

For real feedback, you need a closed loop. That's next.

---

**Checkpoint:** running your agent prints one command frame per publish in the sink. You
can see, in order, exactly what your agent is asking the drone to do.

Next → [Tier 2 — Kinematic mock](./tier2-kinematic-mock.html)
