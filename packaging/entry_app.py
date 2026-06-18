"""Frozen-build entry point.

Default: launch the desktop GUI control panel (which handles first-run config).
With `--tray`: launch straight into the system tray (used by "run at login").
Each target acquires the single-instance guard internally, so a second launch
just no-ops.
"""

from __future__ import annotations

import sys


def main() -> int:
    if "--tray" in sys.argv[1:]:
        from intake_agent.tray import main as tray_main
        return tray_main()
    from intake_agent.gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
