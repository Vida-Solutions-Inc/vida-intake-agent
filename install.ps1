# Intake Agent — one-step installer for Windows.
# Right-click > "Run with PowerShell", or run:  powershell -ExecutionPolicy Bypass -File install.ps1
# Creates a local virtual environment, installs the app, and launches setup.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

Write-Host "Intake Agent installer" -ForegroundColor Cyan

# Find a Python 3.11+ interpreter.
$py = $null
foreach ($cmd in @("py -3", "python", "python3")) {
    try {
        $parts = $cmd.Split(" ")
        $ver = & $parts[0] $parts[1..($parts.Length-1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]"3.11") { $py = $cmd; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.11+ not found. Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
    exit 1
}

Write-Host "Creating virtual environment (.venv)…"
$pyParts = $py.Split(" ")
& $pyParts[0] $pyParts[1..($pyParts.Length-1)] -m venv .venv

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet
Write-Host "Installing Intake Agent and dependencies…"
& $venvPy -m pip install --quiet ".[all]"

Write-Host ""
Write-Host "Installed. Launching setup…" -ForegroundColor Green
Write-Host ""
& $venvPy -m intake_agent setup

Write-Host ""
Write-Host "Done. To start later:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\intake.exe tray     (system-tray app)"
Write-Host "  .\.venv\Scripts\intake.exe start    (terminal)"
