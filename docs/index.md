---
title: Home
layout: home
nav_order: 1
---

# Nimbus Flight-Sim Lab
{: .no_toc }

A hands-on tutorial for prototyping **NimbusOS** autonomy agents against a flight
simulator — *before* you buy a Nimbus module or drone.
{: .fs-6 .fw-300 }

[Start the tutorial](./understand-nimbus.html){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View on GitHub](https://github.com/jasonjgeiger/nimbus-flightsim-lab){: .btn .fs-5 .mb-4 .mb-md-0 }

---

## Why this exists

NimbusOS runs the autonomy stack **on your laptop** — perception, mapping, planning,
guidance, and control. The drone is effectively a *dumb actuator + sensor endpoint*.
That single fact is what makes simulation possible: **if you can feed the SDK simulated
state and absorb its commands, you never need the physical aircraft to develop and test
agent logic.**

This site walks you from zero to a working, hardware-free closed loop, then shows how the
same agent code graduates to real Nimbus hardware.

{: .note }
> This is a **community tutorial** and a companion to the official
> [DroneForge Docs](https://droneforge.gitbook.io/droneforge-docs). For authoritative
> API reference (methods, arguments, typed objects, CLI), this site links out rather
> than duplicating — DroneForge's docs "are expected to change to always represent the
> newest release," so re-check them before every build.

## The learning path

Work through these in order. Each page has a clear goal and a checkpoint so you know
you're ready to move on.

| # | Page | What you'll get |
|---|------|-----------------|
| 1 | [Understand Nimbus & the SDK](./understand-nimbus.html) | The mental model and the ZeroMQ pub/sub contract that makes sim substitution possible. |
| 2 | [Set up your system](./setup.html) | The SDK installed and verified on macOS or Windows. |
| 3 | [Tier 1 — Command dry run](./tier1-command-dry-run.html) | Run an agent and watch its real commands. No sim, no physics. |
| 4 | [Tier 2 — Kinematic mock](./tier2-kinematic-mock.html) | A full closed loop: command → motion → state, all in Python. |
| 5 | [Tier 3 — Flight simulator](./tier3-flight-simulator.html) | High-fidelity physics (Betaflight SITL, PX4, AirSim) via a bridge. |
| 6 | [Build your first agent](./first-agent.html) | The repeatable arm → takeoff → act → land → disarm loop. |
| 7 | [Transition to Nimbus hardware](./to-hardware.html) | Swap the sim for a live NimbusOS instance with minimal changes. |
| 8 | [Safety & quick reference](./reference.html) | Endpoints, CLI, control mapping, and the gotchas. |

## The three tiers of realism

You don't need a physics engine to start. Climb this ladder as your needs grow:

- **Tier 1 — Command-side dry run.** Fully supported today. Validate command sequencing
  and control flow by observing raw command frames. *No feedback loop.*
- **Tier 2 — Kinematic mock.** You own both ends: a tiny Python "NimbusOS" that integrates
  a point-mass model and streams state back. *Real closed loop, no schema dependency.*
- **Tier 3 — Real flight simulator.** A bridge maps a physics sim (Betaflight SITL, PX4,
  AirSim) to Nimbus topics. *Real dynamics and camera imagery.*

Start at Tier 1 and only move up when you hit its limits.
