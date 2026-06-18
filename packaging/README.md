# Packaging notes (maintainers)

Most users should install via `install.ps1` / `install.sh` or
`pip install ".[all]"`. A frozen single-file executable is optional and
experimental.

## Standalone executable (PyInstaller)

```bash
pip install pyinstaller
pyinstaller packaging/intake-agent.spec
# -> dist/intake-agent(.exe)
```

Per-OS notes:

- **Windows (x86_64)** builds cleanly. **Windows on ARM64 (Snapdragon)**: build
  on the ARM64 machine itself with an ARM64 Python; cross-building is unreliable.
- **macOS**: codesign/notarize for distribution, or recipients must clear
  Gatekeeper (right-click → Open). The tray needs no extra entitlements.
- **Linux**: the tray needs libappindicator/GTK at runtime; a PyInstaller bundle
  does not include the system tray host. Document the dependency, or ship the
  `pip` install for Linux instead.

## Why the install-script path is preferred

The app depends only on pure-Python / wheel packages, so a venv + `pip install`
is fast and works identically on all three OSes and CPU architectures, with no
codesigning or hidden-import wrangling. The frozen exe exists for recipients who
won't touch a terminal at all.
