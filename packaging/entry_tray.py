"""Frozen-build entry point: launch the tray app, or run setup first if needed.

Used by PyInstaller (see intake-agent.spec). A double-clicked executable should
not dump a stack trace, so config/key problems fall back to launching setup.
"""

from __future__ import annotations

import sys

from intake_agent.config import config_exists, load_config, resolve_api_key


def main() -> int:
    if not config_exists():
        from intake_agent.setup_wizard import run_setup
        run_setup()
        if not config_exists():
            return 1
    cfg = load_config()
    if not resolve_api_key(cfg):
        from intake_agent.setup_wizard import run_setup
        run_setup(reconfigure=True)
        cfg = load_config()
    from intake_agent.tray import run_tray
    return run_tray(cfg, resolve_api_key(cfg))


if __name__ == "__main__":
    sys.exit(main())
