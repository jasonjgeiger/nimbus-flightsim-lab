#!/usr/bin/env bash
#
# One-shot setup for the NimbusOS flight-sim lab on macOS (Apple Silicon or Intel).
#
# Installs everything needed to run the NimbusOS SDK experiments:
#   - Homebrew (if missing)
#   - Python (>=3.10,<4.0) and Git via Homebrew
#   - A local virtual environment (.venv)
#   - nimbusos-sdk + pyzmq (from requirements.txt)
# Then verifies the SDK imports and the CLI tools are available.
#
# The script is idempotent: re-running it is safe and skips anything already installed.
#
# Usage (from the repo root):
#   chmod +x scripts/setup-macos.sh
#   ./scripts/setup-macos.sh
#
set -euo pipefail

PYTHON_FORMULA="${PYTHON_FORMULA:-python@3.12}"
VENV_PATH="${VENV_PATH:-.venv}"

# --- Pretty output -----------------------------------------------------------
cyan() { printf "\n\033[36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[32m[ok]\033[0m %s\n" "$1"; }
warn() { printf "    \033[33m[!!]\033[0m %s\n" "$1"; }

# --- Resolve repo root (parent of this scripts/ dir) -------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
cyan "Repo root: $REPO_ROOT"

# --- Platform sanity check ---------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "This script targets macOS (Darwin). Detected '$(uname -s)'. Aborting."
    exit 1
fi
ARCH="$(uname -m)"
ok "Detected macOS on ${ARCH}."

# --- Ensure Command Line Tools (needed for Homebrew/builds) ------------------
if ! xcode-select -p >/dev/null 2>&1; then
    cyan "Installing Xcode Command Line Tools (a GUI prompt may appear)"
    xcode-select --install || true
    warn "If a dialog appeared, finish it, then re-run this script."
fi

# --- Ensure Homebrew ---------------------------------------------------------
cyan "Checking for Homebrew"
if ! command -v brew >/dev/null 2>&1; then
    cyan "Installing Homebrew"
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
# Load brew into this shell (Apple Silicon uses /opt/homebrew, Intel uses /usr/local).
if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi
command -v brew >/dev/null 2>&1 || { warn "Homebrew still not on PATH. Open a new terminal and re-run."; exit 1; }
ok "Homebrew ready: $(brew --version | head -n1)"

# --- Install Git + Python via Homebrew --------------------------------------
brew_install() {
    local formula="$1"
    if brew list --formula "$formula" >/dev/null 2>&1; then
        ok "$formula already installed."
    else
        cyan "Installing $formula"
        brew install "$formula"
    fi
}
brew_install git
brew_install "$PYTHON_FORMULA"

# --- Locate the Homebrew python ---------------------------------------------
PY_BIN="$(brew --prefix "$PYTHON_FORMULA")/bin/python3"
if [[ ! -x "$PY_BIN" ]]; then
    PY_BIN="$(command -v python3 || true)"
fi
[[ -x "$PY_BIN" ]] || { warn "No usable python3 found."; exit 1; }
ok "Using Python: $PY_BIN ($("$PY_BIN" --version 2>&1))"

# --- Create the virtual environment -----------------------------------------
cyan "Creating virtual environment at $VENV_PATH"
if [[ ! -d "$VENV_PATH" ]]; then
    "$PY_BIN" -m venv "$VENV_PATH"
    ok "Virtual environment created."
else
    ok "Virtual environment already exists; reusing it."
fi
VENV_PY="$REPO_ROOT/$VENV_PATH/bin/python"

# --- Install dependencies ----------------------------------------------------
cyan "Upgrading pip and installing dependencies"
"$VENV_PY" -m pip install --upgrade pip
if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
    "$VENV_PY" -m pip install -r "$REPO_ROOT/requirements.txt"
else
    "$VENV_PY" -m pip install nimbusos-sdk pyzmq
fi
ok "Dependencies installed."

# --- Verify ------------------------------------------------------------------
cyan "Verifying the install"
"$VENV_PY" -c "from nimbusos_sdk import NimbusClient; print('nimbusos-sdk import OK ->', NimbusClient)"
for tool in nimbusos-subscribe nimbusos-arm nimbusos-autonomy-request \
            nimbusos-waypoint-speed nimbusos-yaw-turn-command; do
    if [[ -x "$REPO_ROOT/$VENV_PATH/bin/$tool" ]]; then
        ok "CLI present: $tool"
    else
        warn "CLI not found: $tool (check the package version)."
    fi
done

printf "\n\033[32mSetup complete.\033[0m\n"
printf "Activate the environment with:\n"
printf "    source %s/bin/activate\n" "$VENV_PATH"
printf "Then start experimenting (see README.md, Section 8).\n"
