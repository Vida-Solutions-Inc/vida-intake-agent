# Packaging notes (maintainers)

Three ways people get the app, easiest first:

1. **Download an installer** (non-technical users) - `IntakeAgentSetup.exe`,
   `IntakeAgent.dmg`, or `IntakeAgent-x86_64.AppImage` from Releases. Bundles
   Python; nothing to preinstall.
2. **`install.ps1` / `install.sh`** (from a clone) - venv + pip + setup wizard.
3. **`pip install ".[all]"`** (developers).

## Producing the installers - CI (recommended)

`.github/workflows/build-installers.yml` builds all three on GitHub-hosted
runners. To cut a release:

```bash
git tag v0.2.0
git push --tags
```

The workflow runs PyInstaller on each OS, wraps the result (Inno Setup / dmg /
AppImage), and attaches the three installers to a GitHub Release. Download them
there to host on your website. You can also trigger it manually ("Run workflow")
to get artifacts without a release.

This is the recommended path because each native installer must be built on its
own OS, and CI owns all three.

## Producing the installers - locally

From the repo root, inside the project venv with `pip install pyinstaller`:

```bash
python packaging/make_icon.py
pyinstaller packaging/intake-agent.spec --noconfirm
```

That yields:
- Windows/Linux -> `dist/IntakeAgent(.exe)`
- macOS -> `dist/IntakeAgent.app`

Then wrap it:
- **Windows**: install Inno Setup, then
  `iscc /DMyAppVersion=0.2.0 packaging\windows\intake-agent.iss` -> `Output\IntakeAgentSetup.exe`
- **macOS**: `hdiutil create -volname "Intake Agent" -srcfolder dist/IntakeAgent.app -ov -format UDZO IntakeAgent.dmg`
- **Linux**: build an AppImage from `dist/IntakeAgent` (see the Linux step in the workflow).

## Per-OS notes

- **CPU arch**: an x86_64 build runs everywhere, including Windows on ARM64
  (Snapdragon) and Apple Silicon, via emulation. Build native arm64 separately
  only if you need maximum performance.
- **Code signing**: unsigned downloads trigger SmartScreen (Windows) and
  Gatekeeper (macOS) warnings. For public distribution, sign with an
  Authenticode cert (Windows) and an Apple Developer ID + notarization (macOS).
  Not required for internal use; recipients can click through ("More info ->
  Run anyway" / right-click -> Open).
- **Linux tray**: the GUI (Tk) always works; the system tray needs
  libappindicator/GTK present on the user's machine. The AppImage does not
  bundle GTK.
