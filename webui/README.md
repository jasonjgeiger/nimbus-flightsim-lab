# Nimbus Mission Control — web app (M1)

Type a mission in plain English, review the compiled plan, then fly it against
whatever "world" is listening on the ZMQ endpoints (Tier 2 mock, Tier 3
Betaflight SITL, or a real NimbusOS drone).

```
English  ──▶  Mission IR (strict JSON)  ──▶  validate  ──▶  executor  ──▶  ZMQ
 (NL layer)      (mission/ir.py)         (units + safety)  (mission/executor)   world
```

**The web app *is* the agent.** It connects a `NimbusClient` to the ZMQ
endpoints; it does not care whether a mock, Betaflight SITL, or a real drone is
on the other end. Switching sim ↔ real drone is an endpoint swap — nothing in
this app changes.

The natural-language layer sits **outside** the safety boundary: every mission
is validated and dead-reckoned against the altitude / geofence / speed caps
*before* any command is published (see [`mission/validate.py`](../mission/validate.py)).

## Run

```bash
source .venv/bin/activate

# 1) Start a world (pick ONE) and wait until it is ready:
python mock_nimbus.py        # Tier 2 kinematic mock (ready immediately), OR
python tier3/bridge.py       # Tier 3 Betaflight SITL — wait for "[bridge] READY"

# 2) Start the web app (separate terminal):
python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000
#   add --reload while developing

# 3) Open http://127.0.0.1:8000
```

In the browser: type a mission → **Compile** → review/edit the IR and the
plain-English preview → **Confirm & Fly** → watch the live per-leg log stream.

## HTTP / WebSocket API

| Method | Path           | Purpose                                                        |
| ------ | -------------- | -------------------------------------------------------------- |
| GET    | `/`            | The single-page UI.                                            |
| GET    | `/api/health`  | `{ ok, nl_backend, pub, sub }` — backend + endpoint config.    |
| POST   | `/api/compile` | `{ text, backend? }` → `{ ir, valid, error, preview }`.        |
| POST   | `/api/preview` | `{ ir }` → `{ valid, error, preview }` (validate an edited IR).|
| WS     | `/ws/fly`      | Send `{ ir }`; receive a stream of `{type:"log"/"done"/"error"}`. |

The compiler always returns the parsed IR (even on validation failure) so you
can see and hand-edit it.

## Configuration (environment variables)

| Variable                | Default                     | Meaning                                  |
| ----------------------- | --------------------------- | ---------------------------------------- |
| `DF_ZMQ_PUB_ENDPOINT`   | `tcp://127.0.0.1:7771`      | Commands out (to the world).             |
| `DF_ZMQ_SUB_ENDPOINT`   | `tcp://127.0.0.1:7772`      | State in (from the world).               |
| `NIMBUS_NL_BACKEND`     | `rules`                     | NL backend: `rules` (offline) or `llm`.  |
| `NIMBUS_LLM_BASE_URL`   | `https://api.openai.com/v1` | OpenAI-compatible endpoint (for `llm`).  |
| `NIMBUS_LLM_API_KEY`    | *(empty)*                   | API key for the `llm` backend.           |
| `NIMBUS_LLM_MODEL`      | `gpt-4o-mini`               | Model name for the `llm` backend.        |
| `NIMBUS_LLM_TIMEOUT_S`  | `30`                        | LLM request timeout.                     |

### NL backends

- **`rules`** (default) — a fully offline, deterministic English parser
  ([`mission/nl/rules.py`](../mission/nl/rules.py)). No network, no key. Handles
  the documented mission phrasings and emits reserved ops for perception
  clauses (which the validator then rejects with a clear message until those
  milestones land).
- **`llm`** — an OpenAI-compatible adapter ([`mission/nl/llm.py`](../mission/nl/llm.py))
  that produces schema-grounded IR. Point `NIMBUS_LLM_BASE_URL` at any
  compatible server (OpenAI, a local Ollama/vLLM gateway, etc.). The output is
  still validated against the same safety caps, so the LLM never bypasses them.

## Supported mission vocabulary (IR v1)

`arm`, `disarm`, `set_speed`, `takeoff`, `land`, `goto_relative`, `climb`,
`yaw_turn`, `hover`. Perception / absolute-goto ops (`goto_target`,
`hover_in_front_of`, `goto_top_of`, `return_to_start`) are reserved for later
milestones and are rejected by the validator. See
[`docs/mission-control/mission-ir.md`](../docs/mission-control/mission-ir.md).

## Related

- CLI runner + tests: [`mission/README.md`](../mission/README.md)
- Design + IR schema: [`docs/mission-control/`](../docs/mission-control/)
- Main project README, §12: natural-language mission control.
