# PyInstaller spec for the standalone Intake Agent desktop app (GUI control panel).
#
# Build (from the repo root, inside the project venv):
#     pip install pyinstaller
#     pyinstaller packaging/intake-agent.spec
#
# Output:
#   Windows/Linux -> dist/IntakeAgent(.exe)
#   macOS         -> dist/IntakeAgent.app  (BUNDLE below)
#
# This is driven by the CI workflow (.github/workflows/build-installers.yml),
# which wraps the result in a per-OS installer. See packaging/README.md.

import os
import sys

block_cipher = None

# SPECPATH is the directory containing this spec; build absolute paths from it so
# the build works no matter where `pyinstaller` is invoked from.
HERE = SPECPATH
REPO = os.path.abspath(os.path.join(HERE, ".."))
ICON = os.path.join(HERE, "build", "icon.ico") if sys.platform == "win32" else \
       (os.path.join(HERE, "build", "icon.png") if sys.platform.startswith("linux") else None)

hidden = [
    # keyring backends are resolved dynamically per OS.
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.chainer",
    # pystray backends.
    "pystray._win32",
    "pystray._darwin",
    "pystray._appindicator",
    "pystray._gtk",
    "pystray._xorg",
]

a = Analysis(
    [os.path.join(HERE, "entry_app.py")],
    pathex=[REPO],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="IntakeAgent",
    debug=False,
    strip=False,
    upx=False,         # UPX often trips antivirus; off for cleaner downloads
    console=False,     # windowed app (no terminal)
    icon=ICON,
)

# macOS: wrap the executable in a .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="IntakeAgent.app",
        icon=None,
        bundle_identifier="com.vidasolutions.intake-agent",
        info_plist={
            "CFBundleName": "Intake Agent",
            "CFBundleDisplayName": "Intake Agent",
            "LSUIElement": False,
            "NSHighResolutionCapable": True,
        },
    )
