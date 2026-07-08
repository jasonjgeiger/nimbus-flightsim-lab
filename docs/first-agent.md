---
title: Build your first agent
layout: default
nav_order: 7
---

# 6. Build & test your first agent
{: .no_toc }

**Goal:** type a mission in plain English and watch it fly against real Betaflight firmware —
no code.
{: .fs-5 .fw-300 }

<details open markdown="block">
  <summary>On this page</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

You type a prompt in the browser, the web app turns it into a flight plan, and a
Betaflight-in-the-loop simulator flies it. **The web app *is* the agent.**

Do these steps in order, from the repo root, with your `.venv` activated.

## 1. Build Betaflight (one time)

```bash
cd .betaflight
make TARGET=SITL OPTIONS="ENABLE_GAZEBO_BRIDGE=0"
cd ..
```

Only needed the first time (and after updating the firmware). The `OPTIONS` flag is required —
without it the simulated quad diverges.

## 2. Start the simulator

In a terminal, leave it running for the whole session:

```bash
source .venv/bin/activate
python tier3/bridge.py
```

Wait for this line before moving on:

```
[bridge] READY (Betaflight armable; agent may connect).
```

## 3. Start the web app

In a **second terminal**:

```bash
source .venv/bin/activate
python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000
```

## 4. Fly a prompt

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** and:

1. Type a mission, e.g. `Fly forward 20 ft, then go up 100 ft and hover.`
2. Click **Compile** to see the flight plan.
3. Click **Confirm & Fly** and watch the live log: **arm → takeoff → legs → land → disarm**.

That's your first agent flying. Try more prompts:

- `Take off, fly forward 10 ft, fly right 10 ft, then land`
- `Fly up 50 ft, turn right 90 degrees, then hover for 5 seconds`

## 5. Watch it in the Betaflight app (optional)

To see live attitude, RC channels, and motors while it flies, open the Betaflight web app and
point it at the simulator through a WebSocket proxy.

In a **third terminal** (after `[bridge] READY`):

```bash
source .venv/bin/activate
python tier3/sitl_ws_proxy.py
```

Then in **Chrome or Edge** at **[app.betaflight.com](https://app.betaflight.com)**:

1. Open **Options** (gear icon) and enable **manual connection mode**.
2. In the port dropdown pick **Manual**, enter `ws://localhost:5762`, and click **Connect**.

---

**Checkpoint:** a prompt you typed in the browser flew a full **arm → takeoff → land → disarm**
mission against Betaflight SITL.

Next → [Transition to Nimbus hardware](./to-hardware.html)
