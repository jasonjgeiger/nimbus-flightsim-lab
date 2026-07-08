# Droneforge Nimbus (NimbusOS) SDK — Flight-Sim Lab

Prototype autonomy agents on the **NimbusOS SDK** against a flight simulator — *before*
buying a Nimbus module or drone.

NimbusOS runs the whole autonomy stack **on your laptop** (perception, mapping, planning,
guidance, control); the drone is just a "dumb" actuator + sensor endpoint that talks over
ZeroMQ. The key insight: **if you can feed the SDK simulated state and absorb its commands,
you never need the physical aircraft to develop and test agent logic.**

## 📖 Read the tutorial

This repo's guide is published as a hands-on, step-by-step **tutorial site**. It's the intended
starting point — it takes you from understanding the SDK, through simulating in software, to
running on real hardware:

### ➡️ https://jasonjgeiger.github.io/nimbus-flightsim-lab/

| # | Chapter | What you get |
|---|---------|--------------|
| 1 | [Understand Nimbus & the SDK](https://jasonjgeiger.github.io/nimbus-flightsim-lab/understand-nimbus.html) | The mental model and the ZeroMQ pub/sub contract that makes sim substitution possible. |
| 2 | [Set up your system](https://jasonjgeiger.github.io/nimbus-flightsim-lab/setup.html) | The SDK installed and verified on macOS or Windows. |
| 3 | [Tier 1 — Command dry run](https://jasonjgeiger.github.io/nimbus-flightsim-lab/tier1-command-dry-run.html) | Run an agent and watch its real commands. No sim, no physics. |
| 4 | [Tier 2 — Kinematic mock](https://jasonjgeiger.github.io/nimbus-flightsim-lab/tier2-kinematic-mock.html) | A full closed loop: command → motion → state, all in Python. |
| 5 | [Tier 3 — Flight simulator](https://jasonjgeiger.github.io/nimbus-flightsim-lab/tier3-flight-simulator.html) | High-fidelity physics (Betaflight SITL, PX4, AirSim) via a bridge. |
| 6 | [Build your first agent](https://jasonjgeiger.github.io/nimbus-flightsim-lab/first-agent.html) | The repeatable arm → takeoff → act → land → disarm loop. |
| 7 | [Transition to Nimbus hardware](https://jasonjgeiger.github.io/nimbus-flightsim-lab/to-hardware.html) | Swap the sim for a live NimbusOS instance with minimal changes. |
| 8 | [Safety & quick reference](https://jasonjgeiger.github.io/nimbus-flightsim-lab/reference.html) | Endpoints, CLI, control mapping, and the gotchas. |

The tutorial deliberately **links out** to the official
[DroneForge Docs](https://droneforge.gitbook.io/droneforge-docs) for API reference (methods,
arguments, typed objects, CLI) rather than duplicating it — that content changes with every
SDK release, so the docs stay the single source of truth.

> **Status note:** NimbusOS is actively evolving and its docs "are expected to change to
> always represent the newest release." Re-check the official sources before each build:
> - Product: https://thedroneforge.com/ and https://thedroneforge.com/specifications
> - SDK docs: https://droneforge.gitbook.io/droneforge-docs
> - SDK source/examples: https://github.com/Droneforge-Inc/NimbusOS-sdk-sandbox
> - Desktop app notes: https://github.com/droneforge/NimbusOS-Desktop
> - PyPI: `nimbusos-sdk`

## Quick start

Clone the repo and run the setup script for your platform. Each script installs Python + Git
(if missing), creates a `.venv`, and installs `nimbusos-sdk` + `pyzmq`. Both are idempotent.

**macOS (Apple Silicon or Intel):**
```bash
git clone https://github.com/jasonjgeiger/nimbus-flightsim-lab.git
cd nimbus-flightsim-lab
chmod +x scripts/setup-macos.sh
./scripts/setup-macos.sh
source .venv/bin/activate
```

**Windows on ARM (ARM64):**
```powershell
git clone https://github.com/jasonjgeiger/nimbus-flightsim-lab.git
cd nimbus-flightsim-lab
pwsh -ExecutionPolicy Bypass -File .\scripts\setup-windows-arm.ps1
.\.venv\Scripts\Activate.ps1
```

Then follow the tutorial from
**[Set up your system](https://jasonjgeiger.github.io/nimbus-flightsim-lab/setup.html)**
onward.

## Natural-language mission control (web app)

Type a mission in plain English — *"fly forward 20 ft, then go up 100 ft and hover"* — review
the compiled plan, then fly it against whatever "world" is running (the Tier 2 mock, the Tier 3
Betaflight SITL bridge, or, eventually, a real NimbusOS drone).

```
English  ──▶  Mission IR (strict JSON)  ──▶  validate (units + safety caps)  ──▶  executor  ──▶  ZMQ world
```

**The web app *is* the agent** — switching sim ↔ real drone is just an endpoint swap. The
natural-language layer sits *outside* the safety boundary: every mission is dead-reckoned
against altitude / geofence / speed caps *before* a single command is published.

```bash
source .venv/bin/activate
python mock_nimbus.py        # start a world (Tier 2 mock), OR: python tier3/bridge.py
python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000   # in another terminal
# open http://127.0.0.1:8000
```

See **[`webui/README.md`](webui/README.md)** for the full flow, HTTP/WebSocket API, and NL
backends (offline rule-based default, or an OpenAI-compatible LLM), and
**[`docs/mission-control/`](docs/mission-control/)** for the design and IR schema.

## What's in this repo

- **`docs/`** — the tutorial site (Jekyll + [Just the Docs](https://just-the-docs.com/)); the
  source for the Pages URL above. See [`docs/README.md`](docs/README.md) to preview or publish
  it locally.
- **`mission/`** — the Mission IR compiler, validator, and deterministic executor, plus a CLI
  (`python -m mission …`) and standalone tests (`python -m mission.selftest`). See
  [`mission/README.md`](mission/README.md).
- **`webui/`** — the FastAPI natural-language mission-control web app. See
  [`webui/README.md`](webui/README.md).
- **`tier3/`** — the Betaflight SITL bridge (real firmware in the loop). See
  [`tier3/README.md`](tier3/README.md).
- **`agents/`**, **`mock_nimbus.py`**, **`sink.py`**, **`run.sh`** — Tier 1/2 worlds, example
  agents, and the launcher used throughout the tutorial.
- **`scripts/`** — idempotent setup scripts for macOS and Windows on ARM.
- **`requirements.txt`** — Python dependencies (`nimbusos-sdk`, `pyzmq`, `jsonschema`,
  `fastapi`, `uvicorn`).

## License / attribution

Community tutorial. NimbusOS, Nimbus, and DroneForge are products of
[DroneForge](https://thedroneforge.com/). Always defer to the
[official docs](https://droneforge.gitbook.io/droneforge-docs) for authoritative,
version-current API details.
