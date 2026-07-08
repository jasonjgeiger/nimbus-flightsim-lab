---
title: Tier 3 — Flight simulator
layout: default
nav_order: 6
---

# 5. Tier 3 — Bridge to a real flight simulator
{: .no_toc }

**Goal:** get real dynamics, sensors, and camera frames by bridging an established physics
simulator to Nimbus topics — reusing the same agent code from Tier 2.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## The idea

A **bridge** replaces the point-mass core of Tier 2 with a physics engine. It maps sim ↔
Nimbus topics in both directions, so your agent keeps talking plain Nimbus ZMQ while a real
flight model does the flying.

```
 ┌────────────┐  Nimbus ZMQ   ┌───────────────┐  sim API (MAVLink/  ┌──────────────────┐
 │ Your Agent │ ◀───────────▶ │  Nimbus↔Sim   │  UDP/RPC)           │  Flight Simulator │
 │  (SDK)     │  7771 / 7772  │   Bridge      │ ◀─────────────────▶ │  (physics+camera) │
 └────────────┘               └───────────────┘                     └──────────────────┘
```

## Choose a simulator

| Simulator | Why pick it | Trade-offs |
|-----------|-------------|-----------|
| **Betaflight SITL** | Closest to Nimbus's real target (drones use Betaflight FCs; Desktop uses CRSF 172–1811 control values). Great for control-level realism. | Bare-bones visuals; add environment/camera separately. |
| **PX4 SITL + Gazebo** | Rich physics, sensors, worlds; huge community; MAVLink. | Heavier setup; MAVLink ≠ Nimbus semantics, so the bridge translates more. Linux-first. |
| **Microsoft AirSim / Colosseum** | Photoreal camera → ideal for testing the **vision** side (feeds `camera`/overlay). Unreal Engine. | Large; camera realism is its strength, flight model less so. |
| **ArduPilot SITL** | Mature, scriptable, MAVLink. | Same MAVLink-translation caveat as PX4. |

{: .highlight }
**Recommended starting combo:** **Betaflight SITL** for flight behavior (control realism
matching the real FC), plus **AirSim** later if/when you need photoreal camera input for
vision agents. Reuse the Tier 2 ZMQ scaffolding; swap the point-mass integrator for the sim
connection.

## What the bridge must do

1. **State out:** read sim position/velocity/attitude → publish Nimbus `selected_state` +
   `telemetry`; render/forward camera frames as JPEG → `camera` / `live_camera`.
2. **Commands in:** subscribe to `arm_state`, `autonomy_request`, `waypoint_speed`,
   `yaw_turn_command` → translate into the sim's control interface. For high-level
   `autonomy_request` (takeoff/land/waypoint) implement a small guidance loop that turns
   waypoints into attitude/throttle (or use the sim autopilot's offboard/guided mode).
3. **Waypoint feedback:** track distance-to-target and emit `waypoint_status`
   (`active`/`reached`/`held`/`distance_m`) and `autonomy_status`.

## Control mapping reference

If you bridge at the raw-control level (e.g. Betaflight SITL), map your agent's intent into
the real control range so behavior matches hardware:

```
CRSF range: 172–1811   throttle low = 172   roll/pitch/yaw center = 992
>992 = right / forward / clockwise ;  <992 = left / back / counter-clockwise
```

(These values come from the NimbusOS Desktop expressions — the same channel semantics the
real drone uses.)

{: .note }
> **Typed helpers still need schemas.** As with Tier 2, the *typed* SDK helpers require
> schema-accurate FlatBuffer output from your bridge. If you only have raw subscriptions,
> keep your agent on `client.subscribe_*`. If you obtain the schemas, emit real FlatBuffers
> and your agent runs unmodified against sim and real hardware alike.

---

**Checkpoint:** you can name which simulator fits your test goal (control realism vs.
photoreal vision) and list the three bridge responsibilities (state out, commands in,
waypoint feedback).

Next → [Build your first agent](./first-agent.html)
