---
title: Set up your system
layout: default
nav_order: 3
---

# 2. Set up your system
{: .no_toc }

**Goal:** get `nimbusos-sdk` installed and verified so you can point it at a simulator.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Requirements

- Python **>=3.10, <4.0**
- A ZMQ endpoint to talk to (NimbusOS, or your simulator from Tier 2/3)
- `pip` or `uv`

## Option A — Automated setup (recommended)

Clone the repo and run the script for your platform. Each script installs Python + Git (if
missing), creates a `.venv`, and installs `nimbusos-sdk` + `pyzmq`. Both are idempotent.

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

## Option B — Manual install

```bash
# with pip
pip install nimbusos-sdk pyzmq

# or with uv
uv add nimbusos-sdk pyzmq
```

{: .note }
> The official [Setup page](https://droneforge.gitbook.io/droneforge-docs/nimbusos-sdk/python-api/setup)
> is the canonical install reference and lists the current CLI tools. Check it if a command
> below has changed name or arguments.

## Verify the install

```bash
python -c "from nimbusos_sdk import NimbusClient; print(NimbusClient)"
nimbusos-subscribe --help
nimbusos-arm --help
nimbusos-autonomy-request --help
nimbusos-waypoint-speed --help
nimbusos-yaw-turn-command --help
```

If those print help text, the SDK and its CLI tools are installed correctly.

## Point the SDK at a simulator

By default the SDK talks to a NimbusOS instance on localhost. To aim it at your simulator
instead, set the endpoints once per shell:

```bash
export DF_ZMQ_PUB_ENDPOINT=tcp://127.0.0.1:7771   # SDK publishes commands here
export DF_ZMQ_SUB_ENDPOINT=tcp://127.0.0.1:7772   # SDK subscribes to state here
```

Per-call override:
```bash
nimbusos-subscribe telemetry --sub-endpoint tcp://127.0.0.1:7772 --limit 1 --timeout 5
```

Or in code:
```python
from nimbusos_sdk import NimbusClient

client = NimbusClient(
    pub_endpoint="tcp://127.0.0.1:7771",
    sub_endpoint="tcp://127.0.0.1:7772",
)
```

---

**Checkpoint:** `from nimbusos_sdk import NimbusClient` imports without error and the
`nimbusos-*` CLI tools respond to `--help`.

Next → [Tier 1 — Command dry run](./tier1-command-dry-run.html)
