---
title: Understand Nimbus & the SDK
layout: default
nav_order: 2
---

# 1. Understand Nimbus & the SDK
{: .no_toc }

**Goal:** build the mental model that makes simulation possible, and learn the one
integration contract everything else depends on.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## How Nimbus actually works

- **Nimbus** is a ~10 g **ground-side** module. It does *not* fly on the drone. It plugs
  into your computer and talks to an **ExpressLRS**-based drone wirelessly (control +
  analog video + telemetry, ~15 ms latency, up to ~1 km).
- **NimbusOS** (internally **DF1**) is the desktop software that runs the autonomy stack
  on your PC: perception/AI, mapping, route planning, guidance, and control. The drone
  just executes commands and reports flight state.
- Because *all the intelligence runs on your laptop*, the drone is a "dumb" actuator +
  sensor endpoint.

{: .highlight }
**The key insight:** if you can feed the SDK simulated state and absorb its commands, you
never need the physical aircraft to develop and test agent logic. That is the entire
premise of this lab.

**Target hardware (so your sim mirrors reality):** ExpressLRS multicopters with a
**Betaflight**-compatible flight controller, an optical-flow/rangefinder sensor
(e.g. MTF-02), and analog or HDMI-out video.

## Two places you can build an agent

1. **NimbusOS Desktop (node/expression editor)** — a visual, node-based builder driven by
   spreadsheet-like expressions. Great for quick behaviors; runs inside the app.
2. **Python SDK (`nimbusos-sdk`)** — a code-first wrapper around NimbusOS's ZeroMQ pub/sub
   topics. **This is the focus of this tutorial.**

## The integration contract: ZeroMQ pub/sub

The SDK does **not** talk to the drone directly. It talks to a running **NimbusOS
instance** over **ZeroMQ (ZMQ)** using **FlatBuffers**-encoded messages. This decoupling
is exactly what lets you substitute a simulator for NimbusOS.

| Direction | What flows | Default endpoint | Override |
|-----------|-----------|------------------|----------|
| **Publish** (SDK → NimbusOS) | commands | `tcp://127.0.0.1:7771` | `DF_ZMQ_PUB_ENDPOINT` or `NimbusClient(pub_endpoint=...)` |
| **Subscribe** (NimbusOS → SDK) | state / telemetry / video | `tcp://127.0.0.1:7772` | `DF_ZMQ_SUB_ENDPOINT` or `NimbusClient(sub_endpoint=...)` |

At a glance, the topics your agent uses:

- **Subscribe (state in):** `telemetry`, `selected_state`, `camera`, `live_camera`,
  `waypoint_status`, `autonomy_status`, `camera_overlay`.
- **Publish (commands out):** `arm_state`, `autonomy_request`, `waypoint_speed`,
  `yaw_turn_command`, `camera_overlay`.

{: .note }
> **Reference, not reproduced.** The exact method signatures, arguments, typed data
> objects, and CLI tools live in the official docs and change between releases. Bookmark
> these and treat them as the source of truth:
> - [Python API overview](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api)
> - [Publishing methods](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/publishing)
> - [Subscriptions](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/subscriptions)
> - [Full API & typed objects](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/api)

### Conventions to mirror in your sim

- Body-frame commands use `forward` (+ = forward), `right` (+ = right), `down` (+ = down),
  in **meters**.
- Attitude is exposed in **degrees** in the typed SDK objects (converted from radians on
  the wire).
- Waypoint speed is clamped to **0.05–0.75 m/s**; out-of-range values raise `ValueError`
  *before* publishing.

## The one real gotcha: the wire format is FlatBuffers

The SDK **decodes** state messages as FlatBuffers into typed dataclasses. For the *typed*
helpers (`client.telemetry()`, `client.selected_state()`, …) to return data, your
simulator must publish bytes in the **exact FlatBuffer schema** NimbusOS uses — and those
schemas are not part of the public docs today. You have three ways around it, matching the
three tiers:

- **Easiest / fully supported (Tier 1):** don't fake the state stream at all. Validate your
  agent's *command* logic and observe it on a raw ZMQ subscriber you control.
- **Medium (Tier 2):** build a **raw-topic** simulator. Your agent uses `client.subscribe_*`
  (raw `.payload` bytes) and your sim publishes a format *you* define — you own both ends,
  so there's no schema dependency. You lose the typed helpers but gain a full closed loop.
- **Best fidelity (Tier 3):** obtain the FlatBuffer schemas (ask DroneForge, or read them
  from the installed package / app) and emit schema-accurate messages so the *typed*
  helpers work unchanged — the only path that runs your production agent byte-for-byte.

{: .note-title }
> Check before you invest
>
> Before building Tier 2/3, inspect the installed package for `.fbs` schemas or generated
> modules, and ask DroneForge whether an official simulator exists:
> ```bash
> pip show -f nimbusos-sdk
> python -c "import nimbusos_sdk, os; print(os.path.dirname(nimbusos_sdk.__file__))"
> ```

---

**Checkpoint:** you can explain, in one sentence, why a simulator can stand in for a real
drone (the ZMQ decoupling), and you know which topics carry commands vs. state.

Next → [Set up your system](./setup.html)
