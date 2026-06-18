#!/usr/bin/env bash
# Intake Agent — one-step installer for macOS and Linux.
# Run:  bash install.sh
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
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip --quiet
echo "Installing Intake Agent and dependencies…"
python -m pip install --quiet ".[all]"

echo ""
echo "Installed. Launching setup…"
echo ""
python -m intake_agent setup

echo ""
echo "Done. To start later:"
echo "  ./.venv/bin/intake tray     # system-tray app"
echo "  ./.venv/bin/intake start    # terminal"
echo ""
echo "Linux note: the tray needs a system tray. On GNOME, install the"
echo "'AppIndicator' extension; pystray uses libappindicator/GTK there."
