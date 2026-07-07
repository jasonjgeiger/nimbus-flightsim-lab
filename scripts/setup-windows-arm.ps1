<#
.SYNOPSIS
    One-shot setup for the NimbusOS flight-sim lab on Windows on ARM (ARM64).

.DESCRIPTION
    Installs everything needed to run the NimbusOS SDK experiments:
      - Python (native ARM64 build) via winget, if missing
      - Git via winget, if missing
      - A local virtual environment (.venv)
      - nimbusos-sdk + pyzmq (from requirements.txt)
    Then verifies the SDK imports and the CLI tools are on PATH.

    The script is idempotent: re-running it is safe and will skip anything
    already installed.

.NOTES
    Target:   Windows 11 on ARM (Snapdragon / ARM64 devices).
    Run from an ordinary PowerShell prompt in the repo root:
        pwsh -ExecutionPolicy Bypass -File .\scripts\setup-windows-arm.ps1
#>

[CmdletBinding()]
param(
    # Python version to install if none is present (native ARM64 build exists 3.11+).
    [string]$PythonVersion = "3.12",
    # Virtual environment directory, relative to the repo root.
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step   { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "    [ok] $m" -ForegroundColor Green }
function Write-Warn2  { param([string]$m) Write-Host "    [!!] $m" -ForegroundColor Yellow }

# --- Resolve repo root (parent of this scripts/ folder) ---------------------
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
Write-Step "Repo root: $RepoRoot"

# --- Architecture sanity check ----------------------------------------------
$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -notmatch "ARM64") {
    Write-Warn2 "PROCESSOR_ARCHITECTURE is '$arch', not ARM64. This script is tuned for Windows on ARM but will still run."
} else {
    Write-Ok "Detected ARM64 architecture."
}

# --- Ensure winget is available ---------------------------------------------
Write-Step "Checking for winget (App Installer)"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget not found. Install 'App Installer' from the Microsoft Store, then re-run this script."
}
Write-Ok "winget present."

function Install-IfMissing {
    param(
        [string]$Command,       # command to probe on PATH
        [string]$WingetId,      # winget package id
        [string]$Friendly       # display name
    )
    if (Get-Command $Command -ErrorAction SilentlyContinue) {
        Write-Ok "$Friendly already installed ($((Get-Command $Command).Source))."
        return
    }
    Write-Step "Installing $Friendly ($WingetId)"
    winget install --id $WingetId --exact --silent `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    Write-Ok "$Friendly installed. You may need to reopen the terminal for PATH updates."
}

# --- Git ---------------------------------------------------------------------
Install-IfMissing -Command "git" -WingetId "Git.Git" -Friendly "Git"

# --- Python (native ARM64) ---------------------------------------------------
# winget automatically selects the ARM64 installer on ARM64 hosts.
$pyId = "Python.Python.$PythonVersion"
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyv = (python --version) 2>&1
    Write-Ok "Python already installed: $pyv"
} else {
    Install-IfMissing -Command "python" -WingetId $pyId -Friendly "Python $PythonVersion"
}

# Refresh PATH for the current session so a freshly installed python is found.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

# --- Locate a usable Python launcher ----------------------------------------
function Get-Python {
    foreach ($cand in @("py -3", "python", "python3")) {
        $exe, $arg = $cand.Split(" ", 2)
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            return @{ Exe = $exe; Arg = $arg }
        }
    }
    throw "No Python found on PATH after install. Reopen your terminal and re-run this script."
}
$py = Get-Python
$pyInvoke = if ($py.Arg) { "$($py.Exe) $($py.Arg)" } else { $py.Exe }
Write-Ok "Using Python launcher: $pyInvoke"

# --- Create the virtual environment -----------------------------------------
Write-Step "Creating virtual environment at $VenvPath"
if (-not (Test-Path $VenvPath)) {
    & $py.Exe $py.Arg -m venv $VenvPath
    Write-Ok "Virtual environment created."
} else {
    Write-Ok "Virtual environment already exists; reusing it."
}

$venvPython = Join-Path $RepoRoot "$VenvPath\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "venv python not found at $venvPython" }

# --- Install dependencies ----------------------------------------------------
Write-Step "Upgrading pip and installing dependencies"
& $venvPython -m pip install --upgrade pip
if (Test-Path (Join-Path $RepoRoot "requirements.txt")) {
    & $venvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
} else {
    & $venvPython -m pip install nimbusos-sdk pyzmq
}
Write-Ok "Dependencies installed."

# --- Verify ------------------------------------------------------------------
Write-Step "Verifying the install"
& $venvPython -c "from nimbusos_sdk import NimbusClient; print('nimbusos-sdk import OK ->', NimbusClient)"
$scripts = Join-Path $RepoRoot "$VenvPath\Scripts"
foreach ($tool in @("nimbusos-subscribe", "nimbusos-arm", "nimbusos-autonomy-request",
                    "nimbusos-waypoint-speed", "nimbusos-yaw-turn-command")) {
    $exe = Join-Path $scripts "$tool.exe"
    if (Test-Path $exe) { Write-Ok "CLI present: $tool" }
    else { Write-Warn2 "CLI not found: $tool (check the package version)." }
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Activate the environment with:" -ForegroundColor Green
Write-Host "    .\$VenvPath\Scripts\Activate.ps1"
Write-Host "Then start experimenting (see README.md, Section 8)." -ForegroundColor Green
