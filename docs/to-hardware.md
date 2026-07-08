---
title: Transition to Nimbus hardware
layout: default
nav_order: 8
---

# 7. Transition to Nimbus hardware
{: .no_toc }

**Goal:** understand the path from a sim-validated agent to a real flight — and why it's
mostly an endpoint swap, not a rewrite.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Why the transition is small

Your agent only ever spoke plain Nimbus ZMQ. The drone is a "dumb" actuator/sensor endpoint,
and NimbusOS is the thing behind the `7771`/`7772` endpoints. So graduating to hardware means
pointing the SDK back at a live NimbusOS instance instead of your simulator — the agent code
doesn't change.

```
        Development                                 Production
  Agent → [ your simulator ]                  Agent → [ live NimbusOS ] → drone
          7771 / 7772                                 7771 / 7772
```

The higher the fidelity you validated at (especially Betaflight SITL with *real* FlatBuffer
schemas), the more faithfully your agent transfers.

## Suggested experimentation roadmap

1. **Install & smoke test (Tier 1).** Confirm the SDK imports, the CLI works, and you can see
   your own commands on a raw ZMQ sink. *No drone, no sim.*
2. **Clone the sandbox.** Read the examples in
   [NimbusOS-sdk-sandbox](https://github.com/Droneforge-Inc/NimbusOS-sdk-sandbox) to learn the
   real command patterns (arm → takeoff → waypoints → land → disarm).
3. **Confirm the wire format.** Inspect the installed package for `.fbs`/generated schemas and
   ask DroneForge whether an official simulator or schemas exist. This decides Tier 2 vs. Tier 3
   fidelity.
4. **Build the Tier 2 kinematic mock.** Get a full closed loop and iterate on guidance/mission
   logic.
5. **Graduate to Tier 3** when you need real physics (Betaflight SITL) or photoreal vision
   (AirSim). Keep the same agent code; only the "core" behind the ZMQ endpoints changes.
6. **Design agents in the Desktop editor** in parallel — node/expression agents are a good way
   to learn Nimbus control semantics (CRSF ranges, vision-target variables, PID/`lin`/`mem`
   helpers) and to compare against your SDK agents.
7. **Buy hardware with confidence.** Because the drone is just the actuator/sensor endpoint,
   agents validated against a faithful sim should transfer with minimal changes — swap the
   endpoints back to a live NimbusOS instance.

## Before your first real flight

{: .warning }
> **Always test publish commands against a simulator or a safe/controlled environment first —
> never a live drone near people.** The official docs state this explicitly. Fly your
> sim-validated agent in an open, controlled area, ready to take manual control.

- Re-verify every method, topic, and argument against the current
  [DroneForge Docs](https://droneforge.gitbook.io/droneforge-docs) — the product changes fast.
- Keep `waypoint_speed` conservative (clamped **0.05–0.75 m/s**) and confirm your abort logic
  (e.g. on low `telemetry.battery.voltage`) actually triggers.
- Confirm units end to end: body-frame **meters** for waypoints, **degrees** for attitude in
  typed objects, **radians** for `yaw_turn_command`.

## Where to buy / learn more

- Product & specs: [thedroneforge.com](https://thedroneforge.com/) ·
  [specifications](https://thedroneforge.com/specifications)
- SDK docs: [droneforge.gitbook.io/droneforge-docs](https://droneforge.gitbook.io/droneforge-docs)
- SDK source & examples:
  [NimbusOS-sdk-sandbox](https://github.com/Droneforge-Inc/NimbusOS-sdk-sandbox)

---

**Checkpoint:** you can explain the transition to hardware as an endpoint swap, and you know
the safety preconditions for a first real flight.

Next → [Safety & quick reference](./reference.html)
