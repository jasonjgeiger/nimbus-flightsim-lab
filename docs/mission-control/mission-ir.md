# Mission IR — the intermediate representation

Mission IR is the strict JSON contract that sits between "English" and "the
drone". The LLM emits it; the validator checks and converts it; the executor
runs it. It is the **only** thing the executor understands.

- Machine-checkable schema: [`mission-ir.schema.json`](./mission-ir.schema.json)
- Architecture & rationale: [`architecture.md`](./architecture.md)

Two rules make it safe:

1. **Closed vocabulary.** Only the step types below exist. Anything else is
   rejected — the LLM cannot invent a command that reaches the drone.
2. **Deterministic execution.** Given the same IR, the executor does the same
   thing every time. No model runs during flight.

---

## 1. Mission document

```jsonc
{
  "version": 1,
  "name": "climb and hover",
  "units_in": "imperial",          // units the STEP numbers are written in
  "defaults": { "speed_mps": 0.35, "threshold_m": 0.15, "hold_time_s": 0.5 },
  "safety": {
    "max_altitude_m": 40.0,        // hard cap; validator rejects IR that exceeds
    "geofence_radius_m": 50.0,     // horizontal radius from start
    "max_speed_mps": 0.75          // clamped to SDK 0.05–0.75
  },
  "steps": [ /* ordered list of steps, see §2 */ ]
}
```

- `units_in`: `"imperial"` (ft, ft/s, sec, degrees — the human default) or
  `"si"` (m, m/s, s, radians). The **validator converts everything to SI** before
  the executor sees it. Step numbers below are shown in the mission's declared
  units.
- `defaults`: applied to any step that omits `speed_mps`, `threshold_m`, or
  `hold_time_s`.
- `safety`: mission-level caps, enforced independently of the LLM (see §5).

## 2. Step vocabulary (v1 — supported)

Every step is `{ "op": "<name>", ... }`. Distances/angles are in `units_in`.

| `op` | Fields | Meaning | SDK mapping |
|------|--------|---------|-------------|
| `arm` | — | arm motors | `publish_arm_state(True)` |
| `disarm` | — | disarm motors | `publish_arm_state(False)` |
| `set_speed` | `speed` | set cruise speed (ft/s or m/s) | `publish_waypoint_speed(mps)` |
| `takeoff` | — | auto take-off / climb to hover | `publish_autonomy_request("takeoff")` |
| `land` | — | auto land | `publish_autonomy_request("land")` |
| `goto_relative` | `forward`, `right`, `up`, `down`, `speed?`, `threshold?`, `hold?` | move relative to the drone body; blocks until reached & held | `publish_relative_waypoint(...)` + wait on `waypoint_status` |
| `climb` | `up` (or `down`), `speed?`, `hold?` | pure vertical move (sugar for `goto_relative` with only vertical) | `publish_relative_waypoint(...)` |
| `yaw_turn` | `degrees` | turn in place, +CW / −CCW (body) | `publish_yaw_turn_command(rad)` |
| `hover` | `seconds` | hold current position | zero-motion `goto_relative` with `hold_time_s=seconds` |
| `return_to_start` | `speed?` | fly back to launch pose (**v2**) | inverse legs from `selected_state()`, or absolute goto |

**`goto_relative` axis rules:**
- `forward` +ahead / −behind, `right` +right / −left.
- Provide **either** `up` **or** `down` for the vertical axis (not both).
  `up` is the human-friendly one; the validator converts `up → down = -up`.
- Omitted axes default to 0.

## 3. Step vocabulary (reserved — rejected in v1)

Defined so the grammar is stable, but the validator **rejects** them until M3
perception exists:

| `op` | Fields | Meaning |
|------|--------|---------|
| `goto_target` | `target` (name), `speed?` | fly to a perceived object ("the tree") |
| `hover_in_front_of` | `target`, `distance`, `seconds` | hold N ft in front of a perceived object |
| `goto_top_of` | `target`, `speed?` | rise to the top of a perceived object |

## 4. Unit conversion (validator, imperial → SI)

Applied only when `units_in == "imperial"`:

| Quantity | From | To | Rule |
|----------|------|----|------|
| distance | feet | meters | `m = ft * 0.3048` |
| speed | ft/s | m/s | `mps = ftps * 0.3048` |
| time | seconds | seconds | identity |
| angle | degrees | radians | `rad = deg * π/180` |
| **vertical** | `up` (ft) | `down` (m) | `down = -(up_ft * 0.3048)` — **NED: up is negative down** |

After conversion, speeds are **clamped** to `[0.05, 0.75]` m/s (SDK window) and
to `safety.max_speed_mps`.

## 5. Safety enforcement (validator, before any motor spins)

The validator simulates the mission's cumulative pose (dead-reckoning from the
relative legs) and rejects the IR if:

- cumulative altitude would exceed `safety.max_altitude_m`;
- horizontal distance from start would exceed `safety.geofence_radius_m`;
- any resolved speed exceeds `safety.max_speed_mps`;
- any step uses a reserved/unknown `op`;
- a `goto_relative` sets both `up` and `down`, or a required field is missing.

Rejection is **hard** and returns a human-readable reason. This is why a wrong
LLM translation still cannot fly an unsafe mission.

---

## 6. Worked example A

**English:** *"Fly forward 20 ft, then go up 100 ft and hover."*

Note: 100 ft = 30.48 m, so this only validates if `max_altitude_m ≥ ~30.5`.

```json
{
  "version": 1,
  "name": "forward then climb and hover",
  "units_in": "imperial",
  "defaults": { "speed_mps": 0.35, "threshold_m": 0.15, "hold_time_s": 0.5 },
  "safety": { "max_altitude_m": 40.0, "geofence_radius_m": 50.0, "max_speed_mps": 0.75 },
  "steps": [
    { "op": "arm" },
    { "op": "set_speed", "speed": 1.15 },
    { "op": "takeoff" },
    { "op": "goto_relative", "forward": 20, "hold": 0.5 },
    { "op": "climb", "up": 100 },
    { "op": "hover", "seconds": 10 },
    { "op": "land" },
    { "op": "disarm" }
  ]
}
```

After validation (SI): `set_speed → 0.35 m/s` (1.15  ft/s ≈ 0.35), `forward →
6.096 m`, `climb up 100 ft → down = -30.48 m`, `hover 10 s`.

## 7. Worked example B (mixes v1 + reserved)

**English:** *"Fly to the tree, hover 10 ft in front of it for 10 s, then rise
2 ft/s to the top, hover 30 s, then return to start."*

This is the target for **M3** — it uses reserved perception steps that the v1
validator rejects. Shown to demonstrate the vocabulary is future-proof:

```json
{
  "version": 1,
  "name": "inspect the tree",
  "units_in": "imperial",
  "defaults": { "speed_mps": 0.35, "threshold_m": 0.2, "hold_time_s": 0.5 },
  "safety": { "max_altitude_m": 60.0, "geofence_radius_m": 80.0, "max_speed_mps": 0.75 },
  "steps": [
    { "op": "arm" },
    { "op": "takeoff" },
    { "op": "hover_in_front_of", "target": "tree", "distance": 10, "seconds": 10 },
    { "op": "goto_top_of", "target": "tree", "speed": 2 },
    { "op": "hover", "seconds": 30 },
    { "op": "return_to_start" },
    { "op": "land" },
    { "op": "disarm" }
  ]
}
```

A **v1-flyable approximation** (no perception) replaces the reserved steps with
geometry the operator supplies — e.g. treating "the tree" as a known relative
offset:

```json
{
  "version": 1,
  "name": "inspect a point (geometric approximation)",
  "units_in": "imperial",
  "defaults": { "speed_mps": 0.35, "threshold_m": 0.2, "hold_time_s": 0.5 },
  "safety": { "max_altitude_m": 60.0, "geofence_radius_m": 80.0, "max_speed_mps": 0.75 },
  "steps": [
    { "op": "arm" },
    { "op": "takeoff" },
    { "op": "goto_relative", "forward": 30, "hold": 10 },
    { "op": "climb", "up": 40, "speed": 2 },
    { "op": "hover", "seconds": 30 },
    { "op": "return_to_start" },
    { "op": "land" },
    { "op": "disarm" }
  ]
}
```

---

## 8. Why an IR at all (vs. LLM → SDK directly)

- **Safety boundary:** the LLM stays outside it. The validator/executor are the
  only things that touch the drone and they enforce caps deterministically.
- **Backend independence:** IR says *what*, not *which backend* — same IR flies
  Betaflight or hardware.
- **Reviewable & editable:** a human previews/edits JSON before flight.
- **Testable:** the executor can be unit-tested against IR with a mock endpoint,
  no model in the loop.
