# PyInstaller spec for a standalone Intake Agent tray executable.
#
# Build (from the repo root, inside the project venv):
#     pip install pyinstaller
#     pyinstaller packaging/intake-agent.spec
#
# Output: dist/intake-agent(.exe). Experimental — see packaging/README.md for
# per-OS notes (notably ARM64 Windows, where building natively on the target
# machine is most reliable).

block_cipher = None

hidden = [
    # keyring backends are resolved dynamically.
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    # pystray backends.
    "pystray._win32",
    "pystray._darwin",
    "pystray._appindicator",
    "pystray._gtk",
    "pystray._xorg",
]

a = Analysis(
    ["packaging/entry_tray.py"],
    pathex=["."],
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
    name="intake-agent",
    debug=False,
    strip=False,
    upx=True,
    console=False,   # windowed (tray) app
)
