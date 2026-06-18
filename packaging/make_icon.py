"""Render app icons for the installers from the same glyph as the tray icon.

Writes to packaging/build/:  icon.png (256), icon.ico (Windows).
Run as part of each platform build. macOS .icns is optional; PyInstaller accepts
a .png too.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intake_agent.trayicon import make_icon  # noqa: E402

OUT = Path(__file__).resolve().parent / "build"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    big = make_icon("watching", 256)
    big.save(OUT / "icon.png")
    # Windows .ico with a range of sizes.
    big.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT/'icon.png'} and {OUT/'icon.ico'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
