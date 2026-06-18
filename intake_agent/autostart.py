"""Run-at-login integration, per OS:

- Windows: a launcher script in the Startup folder (uses pythonw to stay hidden).
- macOS:   a LaunchAgent plist in ~/Library/LaunchAgents.
- Linux:   an XDG .desktop file in ~/.config/autostart.

All install the same command: launch the tray app. No admin rights required.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_DISPLAY_NAME
from .platform_utils import IS_LINUX, IS_MACOS, IS_WINDOWS

_LABEL = "com.vidasolutions.intake-agent"


def _launch_cmd() -> list[str]:
    # Frozen app (PyInstaller): the exe IS the launcher; start it in tray mode.
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tray"]
    # Source/pip install: run the module. Prefer the windowless interpreter on
    # Windows so no console flashes at login.
    exe = sys.executable
    if IS_WINDOWS:
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.exists():
            exe = str(pyw)
    return [exe, "-m", "intake_agent", "tray"]


# ------------------------------------------------------------------- Windows
def _win_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"


def _win_script() -> Path:
    return _win_startup_dir() / "intake-agent.cmd"


def _win_enable() -> str:
    cmd = _launch_cmd()
    script = _win_script()
    script.parent.mkdir(parents=True, exist_ok=True)
    # `start "" ...` so the launcher returns immediately.
    script.write_text(f'@echo off\r\nstart "" {" ".join(_q(c) for c in cmd)}\r\n', encoding="utf-8")
    return str(script)


def _win_disable() -> None:
    _win_script().unlink(missing_ok=True)


# --------------------------------------------------------------------- macOS
def _mac_plist() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{_LABEL}.plist"


def _mac_enable() -> str:
    cmd = _launch_cmd()
    args = "".join(f"        <string>{c}</string>\n" for c in cmd)
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'    <key>Label</key>\n    <string>{_LABEL}</string>\n'
        f'    <key>ProgramArguments</key>\n    <array>\n{args}    </array>\n'
        '    <key>RunAtLoad</key>\n    <true/>\n'
        '</dict>\n</plist>\n'
    )
    path = _mac_plist()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    subprocess.run(["launchctl", "load", str(path)], capture_output=True)
    return str(path)


def _mac_disable() -> None:
    path = _mac_plist()
    if path.exists():
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------- Linux
def _linux_desktop() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "autostart" / "intake-agent.desktop"


def _linux_enable() -> str:
    cmd = " ".join(_q(c) for c in _launch_cmd())
    desktop = (
        "[Desktop Entry]\nType=Application\n"
        f"Name={APP_DISPLAY_NAME}\nExec={cmd}\n"
        "X-GNOME-Autostart-enabled=true\nTerminal=false\n"
    )
    path = _linux_desktop()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop, encoding="utf-8")
    return str(path)


def _linux_disable() -> None:
    _linux_desktop().unlink(missing_ok=True)


# ------------------------------------------------------------------- dispatch
def enable() -> str:
    if IS_WINDOWS:
        return _win_enable()
    if IS_MACOS:
        return _mac_enable()
    if IS_LINUX:
        return _linux_enable()
    raise RuntimeError(f"autostart not supported on {sys.platform}")


def disable() -> None:
    if IS_WINDOWS:
        _win_disable()
    elif IS_MACOS:
        _mac_disable()
    elif IS_LINUX:
        _linux_disable()


def status_path() -> Path | None:
    path = _win_script() if IS_WINDOWS else _mac_plist() if IS_MACOS else _linux_desktop()
    return path if path.exists() else None


def _q(s: str) -> str:
    return f'"{s}"' if " " in s else s
