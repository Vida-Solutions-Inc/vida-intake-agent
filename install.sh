#!/usr/bin/env bash
# Intake Agent - one-step installer for macOS, Linux, and Windows Git Bash.
# Run:  bash install.sh
# (On Windows, install.ps1 is the native option; this also works in Git Bash.)
# Creates a local virtual environment, installs the app, and launches setup.
set -euo pipefail
cd "$(dirname "$0")"

echo "Intake Agent installer"

# Find Python 3.11+.
PY=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)'; then
      PY="$cmd"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11+ not found. Install it (e.g. 'brew install python' or your package manager) and re-run." >&2
  exit 1
fi

echo "Creating virtual environment (.venv)…"
"$PY" -m venv .venv
# venv layout differs: .venv/bin on Unix, .venv/Scripts on Windows (Git Bash).
if [ -f .venv/bin/activate ]; then
  BIN=".venv/bin"
elif [ -f .venv/Scripts/activate ]; then
  BIN=".venv/Scripts"
else
  echo "Could not find the virtual environment's activate script." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$BIN/activate"

python -m pip install --upgrade pip --quiet
echo "Installing Intake Agent and dependencies…"
python -m pip install --quiet ".[all]"

echo ""
echo "Installed. Launching setup…"
echo ""
python -m intake_agent setup

echo ""
echo "Done. To start later:"
echo "  $BIN/intake tray     # system-tray app"
echo "  $BIN/intake start    # terminal"
echo ""
echo "Linux note: the tray needs a system tray. On GNOME, install the"
echo "'AppIndicator' extension; pystray uses libappindicator/GTK there."
