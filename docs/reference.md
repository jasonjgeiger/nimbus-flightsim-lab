---
title: Safety & quick reference
layout: default
nav_order: 9
---

# 8. Safety & quick reference
{: .no_toc }

A one-page cheat sheet. For anything authoritative or version-specific, defer to the
[DroneForge Docs](https://droneforge.gitbook.io/droneforge-docs).
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Safety & gotchas

{: .warning }
> **Always test publish commands against a simulator or a safe/controlled environment —
> never a live drone near people.** The docs state this explicitly.

- **Waypoint speed is clamped 0.05–0.75 m/s.** Out-of-range values raise `ValueError` before
  publishing. Many args are validated (finite numbers, `mode` ∈ {override, queue}, request
  types) — mirror these in your sim so behavior matches.
- **Units:** body-frame meters for waypoints (forward/right/down); degrees for attitude in
  typed objects; radians for `yaw_turn_command`.
- **NimbusOS is required for the *live* typed workflow.** Your simulator stands in for it; the
  fidelity of that substitution is bounded by whether you can produce schema-accurate messages.
- **The product changes fast.** Topic names, methods, and packaging can change between
  releases — re-verify against the current docs and SDK source each time you start a build.

## Endpoints

```
Publish (commands):   tcp://127.0.0.1:7771   (DF_ZMQ_PUB_ENDPOINT)
Subscribe (state):    tcp://127.0.0.1:7772   (DF_ZMQ_SUB_ENDPOINT)
```

## Topics

| Direction | Topics |
|-----------|--------|
| Subscribe (state in) | `telemetry`, `selected_state`, `camera`, `live_camera`, `waypoint_status`, `autonomy_status`, `camera_overlay` |
| Publish (commands out) | `arm_state`, `autonomy_request`, `waypoint_speed`, `yaw_turn_command`, `camera_overlay` |

## CLI smoke tests

```bash
nimbusos-subscribe telemetry --limit 1 --timeout 5
nimbusos-subscribe selected_state --limit 1 --timeout 5
nimbusos-arm
nimbusos-autonomy-request takeoff
nimbusos-autonomy-request relative_waypoint --mode override --forward 1.5 --right 0.0 --down 0.0
nimbusos-waypoint-speed 0.45
nimbusos-yaw-turn-command 0.52
```

## Minimal agent loop

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

## Control mapping (real hardware / Betaflight SITL)

```
CRSF range: 172–1811   throttle low = 172   roll/pitch/yaw center = 992
>992 = right / forward / clockwise ;  <992 = left / back / counter-clockwise
```

## Official references

- **Product:** [thedroneforge.com](https://thedroneforge.com/) ·
  [specifications](https://thedroneforge.com/specifications)
- **SDK docs:** [droneforge.gitbook.io/droneforge-docs](https://droneforge.gitbook.io/droneforge-docs)
  — [Setup](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/setup),
  [Quick Start](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/quick-start),
  [Publishing](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/publishing),
  [Subscriptions](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/subscriptions),
  [API](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/api),
  [CLI](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/cli),
  [Examples](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/examples)
- **SDK source & examples:**
  [NimbusOS-sdk-sandbox](https://github.com/Droneforge-Inc/NimbusOS-sdk-sandbox)
- **PyPI:** `nimbusos-sdk`
