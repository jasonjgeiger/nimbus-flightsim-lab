# `mission/` — Mission Control executor core (M0)

Deterministic pipeline that turns **Mission IR** (strict JSON) into drone flight
via `nimbusos_sdk.NimbusClient`. No LLM and no web UI yet — that's M1. Because the
executor only talks to the SDK, the same mission flies the **Tier 2 mock**, real
**Betaflight SITL** (Tier 3), and later a **real drone** — the backend is an
endpoint swap.

Design + IR spec: [`../docs/mission-control/`](../docs/mission-control/).

## Layout

| File | Role |
|------|------|
| `ir.py` | Vocabulary, unit constants, JSON-Schema structure validation, normalized (SI) data model. |
| `validate.py` | `compile_mission(doc)` → structure + imperial→SI conversion + safety-cap enforcement + reserved-op rejection. `preview()` for the confirm screen. |
| `executor.py` | `MissionExecutor` — runs a validated mission step-by-step, blocking on `waypoint_status` for moving legs; lands+disarms on any failure. `DryRunClient` for tests/previews. |
| `__main__.py` | CLI: preview + confirm + fly. |
| `selftest.py` | Standalone test suite (no pytest). |
| `examples/` | Hand-written IR missions. |

## Use

```bash
# Preview + confirm + fly (point at a running backend first):
./run.sh tier3                                  # start Betaflight SITL in one shell
python -m mission mission/examples/forward_up_hover.json          # fly in another

# Preview only, no drone:
python -m mission mission/examples/forward_up_hover.json --dry-run

# Fly a mission through run.sh (non-interactive):
NIMBUS_MISSION=mission/examples/forward_up_hover.json ./run.sh tier3 agents/fly_mission.py

# Tests:
.venv/bin/python -m mission.selftest
```

## Safety

The LLM (M1) sits *outside* the safety boundary. `compile_mission` deterministically
rejects any IR that would exceed `max_altitude_m` / `geofence_radius_m` /
`max_speed_mps`, uses an unknown or reserved op, or is structurally malformed —
*before* any motor spins. Speeds are clamped to the SDK's 0.05–0.75 m/s window.
On any in-flight error the executor commands `land` then `disarm`.
