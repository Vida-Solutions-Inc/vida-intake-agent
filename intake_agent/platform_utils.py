"""Cross-platform helpers: standard directories and OS file-manager actions.

Centralises every place the app touches OS-specific behaviour so the rest of
the code stays platform-agnostic.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from platformdirs import user_config_path, user_data_path, user_log_path

from . import APP_NAME

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def config_dir() -> Path:
    p = user_config_path(APP_NAME, appauthor=False, ensure_exists=True)
    return Path(p)


def data_dir() -> Path:
    p = user_data_path(APP_NAME, appauthor=False, ensure_exists=True)
    return Path(p)


def log_dir() -> Path:
    p = user_log_path(APP_NAME, appauthor=False, ensure_exists=True)
    return Path(p)


def config_file() -> Path:
    return config_dir() / "config.toml"


def default_staging_root() -> Path:
    """A scratch dir on local disk, outside any cloud-sync folder.

    Reading documents off a live OneDrive/Dropbox/iCloud path can race with the
    sync engine; staging a local copy first sidesteps that entirely.
    """
    return Path(tempfile.gettempdir()) / "intake-agent-staging"


def open_path(path: Path) -> None:
    """Open a file or folder in the OS default handler (file manager / app)."""
    path = Path(path)
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MACOS:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        # Opening a folder is a convenience, never fatal.
        pass


def reveal_in_file_manager(path: Path) -> None:
    """Open the file manager with *path* selected (falls back to its folder)."""
    path = Path(path)
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif IS_MACOS:
            subprocess.Popen(["open", "-R", str(path)])
        else:
            open_path(path.parent if path.is_file() else path)
    except Exception:
        open_path(path.parent if path.is_file() else path)
