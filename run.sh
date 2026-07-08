#!/usr/bin/env bash
#
# Convenience launcher for the NimbusOS flight-sim lab (macOS/Linux).
#
# Starts the "world" (Tier 1 sink, Tier 2 mock or Tier 3 Betaflight bridge) in
# the background, points the SDK at the local endpoints, runs an agent, then
# tears the world down.
#
# Usage (from the repo root):
#   ./run.sh                       # Tier 2 mock + agents/orbit_agent.py (default)
#   ./run.sh tier1                 # Tier 1 sink  + agent_smoke.py
#   ./run.sh tier2 agents/orbit_agent.py
#   ./run.sh tier3                 # Betaflight SITL bridge + agents/orbit_agent.py
#   ./run.sh tier3 agents/fly_mission.py   # fly a Mission IR file (see mission/)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TIER="${1:-tier2}"
export DF_ZMQ_PUB_ENDPOINT="${DF_ZMQ_PUB_ENDPOINT:-tcp://127.0.0.1:7771}"
export DF_ZMQ_SUB_ENDPOINT="${DF_ZMQ_SUB_ENDPOINT:-tcp://127.0.0.1:7772}"

# Put the repo root on PYTHONPATH so agents can import local packages
# (e.g. `mission`) regardless of the script's own directory.
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Pick the venv python if present, else fall back to python3.
PY="python3"
[[ -x ".venv/bin/python" ]] && PY=".venv/bin/python"

# Seconds to wait for the world to be ready before starting the agent. Tier 3
# needs longer because the bridge boots + one-time-configures Betaflight SITL.
SETTLE=1

case "$TIER" in
  tier1)
    WORLD="sink.py"
    AGENT="${2:-agent_smoke.py}"
    ;;
  tier2)
    WORLD="mock_nimbus.py"
    AGENT="${2:-agents/orbit_agent.py}"
    ;;
  tier3)
    WORLD="tier3/bridge.py"
    AGENT="${2:-agents/orbit_agent.py}"
    # tier3 uses a readiness handshake (below) instead of a fixed SETTLE.
    ;;
  *)
    echo "Unknown tier '$TIER' (expected tier1, tier2 or tier3)." >&2
    exit 1
    ;;
esac

echo "==> Starting world: $WORLD"
READY_FILE=""
if [[ "$TIER" == "tier3" ]]; then
  READY_FILE="$(mktemp -t nimbus_tier3_ready.XXXXXX)"
  rm -f "$READY_FILE"
  export NIMBUS_TIER3_READY="$READY_FILE"
fi
"$PY" "$WORLD" &
WORLD_PID=$!
cleanup() { kill "$WORLD_PID" 2>/dev/null || true; [[ -n "$READY_FILE" ]] && rm -f "$READY_FILE"; }
trap cleanup EXIT

if [[ -n "$READY_FILE" ]]; then
  # Wait (bounded) for the bridge to report it is armable before the agent runs.
  echo "==> Waiting for Betaflight bridge to become ready ..."
  for _ in $(seq 1 60); do
    [[ -f "$READY_FILE" ]] && break
    kill -0 "$WORLD_PID" 2>/dev/null || { echo "World exited during startup." >&2; exit 1; }
    sleep 1
  done
  [[ -f "$READY_FILE" ]] || echo "==> Warning: bridge not ready after 60s; starting agent anyway."
else
  sleep "$SETTLE"  # let the sockets bind
fi

echo "==> Running agent: $AGENT"
"$PY" "$AGENT"

echo "==> Agent finished. Stopping world (pid $WORLD_PID)."
