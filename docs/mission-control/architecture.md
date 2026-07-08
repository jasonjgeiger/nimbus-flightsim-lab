# Nimbus Mission Control — Architecture

Natural-language → drone flight, for Betaflight SITL today and a real NimbusOS
drone tomorrow.

> **Status:** design doc (M0 in progress). No LLM and no web UI are built yet —
> this document is the contract the rest of the work is built against.

---

## 1. Goal

Let a human type plain English —

> *"Fly forward 20 ft, then go up 100 ft and hover."*
> *"Fly to the tree, hover 10 ft in front of it for 10 s, then rise 2 ft/s to the
> top, hover 30 s, then return to start."*

— and have the system fly that mission, first in **Betaflight SITL** for testing
and eventually on the **real drone**, with a human confirmation step in between.

## 2. The one insight that shapes everything

Every flight backend we care about speaks the **same NimbusOS ZeroMQ contract**
(command topics on `tcp://…:7771`, state/telemetry on `7772`, FlatBuffers
payloads) through one client: `nimbusos_sdk.NimbusClient`.

- **Tier 3 (Betaflight SITL):** `tier3/bridge.py` subscribes to those command
  topics, drives real Betaflight firmware, and republishes state/telemetry.
- **Real NimbusOS drone:** the same topics, served by the actual flight stack.

So **the executor only ever talks to `NimbusClient`.** Switching from "test in
sim" to "fly the real drone" is an **endpoint swap** (which process is listening
on 7771/7772), *not* a rewrite. This is the central design constraint: nothing
above the SDK is allowed to know whether it is flying Betaflight or hardware.

```
                         ┌──────────────────────────────────────┐
   English text  ──────► │  NL → Mission IR   (LLM, constrained) │
                         └──────────────────────────────────────┘
                                        │  Mission IR (strict JSON)
                                        ▼
                         ┌──────────────────────────────────────┐
   human confirm ◄─────► │  Validator  (schema + safety caps +   │
   (preview/edit)        │             unit conversion ft→m)     │
                         └──────────────────────────────────────┘
                                        │  validated, SI-unit IR
                                        ▼
                         ┌──────────────────────────────────────┐
                         │  Executor  (deterministic runner)     │
                         │  IR step  ->  NimbusClient call        │
                         └──────────────────────────────────────┘
                                        │  ZMQ 7771 / 7772 (FlatBuffers)
                    ┌───────────────────┴───────────────────┐
                    ▼                                        ▼
        tier3/bridge.py → Betaflight SITL        real NimbusOS flight stack
              (testing today)                        (endpoint swap)
```

## 3. Components

| Component | Package | Responsibility | Backend-aware? |
|-----------|---------|----------------|----------------|
| **NL compiler** | `mission/nl/` (M1) | English → Mission IR via a constrained LLM. Never touches the SDK. | no |
| **Mission IR** | `docs/mission-control/mission-ir*` | The strict JSON intermediate representation. The linchpin — see `mission-ir.md`. | no |
| **Validator** | `mission/validate.py` (M0) | JSON-Schema check, unit conversion (imperial→SI), safety-cap enforcement. Rejects unsafe/unknown IR *before* any motor spins. | no |
| **Executor** | `mission/executor.py` (M0) | Deterministic IR → `NimbusClient` runner. Generalizes `agents/orbit_agent.py`. | no |
| **Web app** | `webui/` (M1) | FastAPI backend + light frontend: type English, preview IR, confirm, watch. | no |
| **Backend** | `tier3/bridge.py` / real drone | Serves the ZMQ contract. | **yes** |

**Design rule:** only the bottom row of the table is backend-aware. Everything
else is written once and reused across sim and hardware.

## 4. NL → IR flow

1. **User** types a mission in English (imperial units, casual phrasing).
2. **LLM** is prompted with the IR grammar (`mission-ir.md`) and the JSON Schema,
   and is required to emit **only** valid Mission IR — no prose, no code. It is a
   *translator*, not a pilot: it never invents commands outside the vocabulary.
3. **Validator** parses the IR, converts units to SI, applies safety caps, and
   produces a human-readable preview ("Leg 1: climb to 30.5 m, hold 0 s …").
4. **Human confirms** (or edits the IR / re-prompts). Nothing flies until this.
5. **Executor** runs the validated IR step-by-step against `NimbusClient`.

The LLM is deliberately *outside* the safety boundary: even a wrong translation
cannot fly an unsafe mission, because the deterministic validator + executor are
the only things that touch the drone, and they enforce caps independently.

## 5. Executor → SDK mapping

The executor is a small interpreter. Each IR step maps to one or more
`NimbusClient` calls. Signatures below are the **real** SDK surface (verified):

| IR step | NimbusClient call(s) |
|---------|----------------------|
| `arm` | `publish_arm_state(True)` |
| `disarm` | `publish_arm_state(False)` |
| `set_speed {mps}` | `publish_waypoint_speed(mps)`  *(0.05–0.75 m/s)* |
| `takeoff` | `publish_autonomy_request("takeoff")` |
| `land` | `publish_autonomy_request("land")` |
| `goto_relative {forward,right,down}` | `publish_relative_waypoint(forward=…, right=…, down=…, mode="override", threshold_m=…, hold_time_s=…)` then block on `waypoint_status(...)` until `reached and held` |
| `yaw_turn {delta_rad}` | `publish_yaw_turn_command(delta_rad)` |
| `hover {seconds}` | issue a zero-motion `goto_relative` with `hold_time_s=seconds`, or sleep while holding position |
| `return_to_start` (v2) | read `selected_state()` start pose → compute inverse relative legs, or issue an absolute goto if the pipeline gains one |

**Frames (critical, easy to get wrong):**
- **Body FRD** — forward / right / **down** positive. `goto_relative` is
  body-relative.
- **World NED** — down positive, so **"up" = negative `down`**. "climb 100 ft" →
  `down = -30.48`.
- **Yaw** in **radians**, body-relative (`publish_yaw_turn_command`).
- NL is **imperial** (ft, ft/s, sec, degrees); the validator converts to SI
  (m, m/s, s, radians). See `mission-ir.md` §Unit conversion.

**Blocking model:** legs that move must wait for `waypoint_status().reached &&
.held` (bounded timeout), exactly like `orbit_agent.py`. Fire-and-forget is only
for instantaneous commands (arm, set_speed).

## 6. Backends: sim today, hardware tomorrow

| | Betaflight SITL (test) | Real NimbusOS drone |
|-|------------------------|---------------------|
| Serves ZMQ 7771/7772 | `tier3/bridge.py` (+ Betaflight SITL firmware) | real flight stack |
| Launch | `./run.sh tier3` | connect to drone's endpoint |
| Executor changes | **none** | **none** |
| Extra safety | sim can't hurt anyone | geofence + altitude caps enforced *before* takeoff; kill path required |

The executor takes the ZMQ endpoint as config. "Test then fly for real" is a
config change, not a code change.

## 7. Perception ("fly to the tree") — phased

Missions that reference the world by *meaning* ("the tree", "10 ft in front of
it", "to the top") need vision/perception that the v1 pipeline does not have.

- **v1 (now):** geometric missions only — relative/absolute moves, climbs,
  hovers, yaw, return-to-start. `goto_target` / `hover_in_front_of` steps are
  defined in the IR grammar but the validator **rejects** them as unsupported.
- **v3 (later):** wire `camera_frames()` + a detector/depth estimator to resolve
  a named target to a body-relative offset, then reduce it to `goto_relative`.
  The IR grammar already reserves the vocabulary so nothing else changes.

## 8. Safety

- **Mission-level caps** (validated before flight, enforced independently of the
  LLM): `max_altitude_m`, `geofence_radius_m`, `max_speed_mps`. Any IR that would
  exceed a cap is rejected with a clear reason.
- **Speed clamp:** `set_speed` is clamped to the SDK's 0.05–0.75 m/s window.
- **Human confirm** is mandatory before execute (preview shows SI values + a
  running altitude/offset estimate).
- **Bounded waits:** every blocking leg has a timeout; a leg that never reaches
  aborts the mission into `land` + `disarm` rather than hanging.
- **Clean teardown:** on abort/error/SIGTERM the executor commands `land` then
  `disarm` (mirrors the Tier 3 bridge's SIGTERM discipline).
- **Real-drone gate:** hardware backend additionally requires geofence + max-alt
  set and a reachable kill path before it will arm.

## 9. Stack

- **Backend:** FastAPI (Python) — reuses `NimbusClient`, the validator, and the
  executor directly. WebSocket to stream live status/telemetry to the browser.
- **Frontend:** lightweight (HTMX/Alpine or a small React/Vite app) — a prompt
  box, an IR preview/editor, a Confirm button, and a live telemetry panel.
- **LLM:** pluggable. Cloud model for convenience; a local/offline model is a
  goal for field use (no connectivity). The IR + Schema make the provider
  swappable — any model that can emit valid JSON works.
- **New code lives under** `mission/` (IR, validator, executor) and `webui/`
  (FastAPI + frontend). The executor generalizes `agents/orbit_agent.py`.

## 10. Milestones

| Milestone | Scope | Done when |
|-----------|-------|-----------|
| **M0** (now) | IR schema + loader + validator + deterministic executor. No UI, no LLM. | A hand-written JSON version of "forward 20 ft, up 100 ft, hover" flies in Betaflight SITL via the executor. |
| **M1** | NL→IR (constrained LLM) + FastAPI + minimal web UI with preview/confirm. | Typing the English mission produces IR, and confirming flies it in SITL. |
| **M2** | Real-drone backend + full safety gates (geofence, max-alt, kill path) + `return_to_start`. | Same mission flies on hardware behind safety gates. |
| **M3** | Perception: `goto_target` / `hover_in_front_of` via `camera_frames()`. | "Fly to the tree…" resolves a real target and flies it. |

See `mission-ir.md` for the IR vocabulary and both example missions compiled to
IR, and `mission-ir.schema.json` for the machine-checkable schema the validator
uses.
