# Intake Agent

A small desktop app that watches an **inbox folder** and files whatever you drop
into it to the right place in **your repository** - using Claude to read each
document and decide where it belongs.

Drop an invoice, a bank statement, a signed contract, a meeting note, a receipt
photo. The agent reads it, finds the best-matching folder in your repo, renames
it to match the folder's existing convention, and moves it there. Anything it
isn't sure about goes to a `review/` folder, untouched.

It works on **any repository** with no hand-written rules: it learns your folder
structure by looking at it. Power users can add an optional `intake.rules.md` for
domain specifics. Runs on **Windows, macOS, and Linux**.

> Pure Python. No Node.js, no external CLI - just `pip install` and go.

---

## Quick start

### Easiest (no Python needed) - download the installer

Grab the installer for your OS from the project's
[Releases](https://github.com/Vida-Solutions-Inc/vida-intake-agent/releases) page:

- **Windows** - `IntakeAgentSetup.exe` (per-user, no admin prompt)
- **macOS** - `IntakeAgent.dmg` (drag to Applications)
- **Linux** - `IntakeAgent-x86_64.AppImage` (`chmod +x`, then run)

Double-click to launch the app, click **Settings** to pick your repository
folder and paste your Anthropic API key, then press **Start**. No terminal, no
Python install required. Configure run-at-login and the system tray from the
window. (Installers are produced by the [build workflow](.github/workflows/build-installers.yml).)

### One script (from a clone)

Clone or download this repo, then:

- **Windows** - right-click `install.ps1` → *Run with PowerShell*
  (or `powershell -ExecutionPolicy Bypass -File install.ps1`)
- **macOS / Linux** - `bash install.sh`

The script creates a local virtual environment, installs everything, and walks
you through setup (repo path, inbox folder, API key).

### Manual (for developers)

```bash
pip install ".[all]"     # or: pipx install ".[all]"
intake setup             # interactive first-run config
intake tray              # run as a system-tray app
#   or
intake start             # run in the terminal
```

You'll need an Anthropic API key: <https://console.anthropic.com/>. It's stored
in your OS keychain, not in the repo.

---

## How it works

```
            drop a file
                │
        ┌───────▼────────┐   watch + wait until the file is fully written
        │  inbox folder  │   (handles cloud-sync settling)
        └───────┬────────┘
                │ stage a local copy (safe to read off OneDrive/Dropbox/iCloud)
        ┌───────▼────────┐   READ-ONLY agent: reads the document, explores your
        │   the agent    │   repo with sandboxed tools, returns a structured
        │  (Claude API)  │   verdict: where + what filename + confidence
        └───────┬────────┘
                │ verdict
        ┌───────▼────────┐   the mover (the ONLY writer) places the file, creates
        │   the mover    │   folders per your policy, dedups by content hash, and
        │                │   records every action in an undo-able ledger
        └───────┬────────┘
        ┌───────▼────────┐
        │  your  repo    │   filed, renamed to match siblings - or sent to review/
        └────────────────┘
```

**The brains are repo-agnostic.** The system prompt is built from three layers:

1. a built-in routing philosophy (pick the deepest specific folder, match naming
   conventions, review when unsure),
2. a live snapshot of *your* repo's folder tree, and
3. your optional `intake.rules.md`.

That's why it works on a brand-new repo it has never seen, and gets sharper as
you add rules.

**The agent never writes.** It can only read - and only inside your repo and the
staged copy of the file under review (a hard path sandbox). A separate mover
performs the actual move, so a crash mid-decision can never leave a half-filed
file, and the agent can't fabricate a move that didn't happen.

---

## Commands

| Command | What it does |
|---|---|
| `intake gui` | Open the desktop control-panel window (Start/Stop, settings, activity). |
| `intake setup` | Interactive first-run configuration (terminal). |
| `intake tray` | Run as a system-tray app (start/stop, status, open folders, approvals). |
| `intake start` | Watch the inbox in the terminal. `--dry-run` to detect without acting. |
| `intake once` | Process whatever is in the inbox now, then exit. |
| `intake status` | Show config and recent activity. |
| `intake doctor` | Diagnose config, API key, and connectivity. |
| `intake history` | List recent routing actions. |
| `intake undo <id>` | Reverse a routing action (moves the file back to the inbox). |
| `intake autostart enable` | Launch the tray app at login (per-OS, no admin needed). |
| `intake config` | Print the active config file. |

---

## The desktop window

`intake gui` (or the installed app) opens a control panel: a **Start/Stop**
button (the manual run style), live status and a recent-activity feed, buttons
to open the inbox / review / repo / logs, a **Settings** screen (pick your repo
folder, paste your API key, choose the new-folder policy), a **Run at login**
toggle, and **Hide to tray**. Only one copy runs at a time (a single-instance
guard prevents the tray, the window, and the login launcher from double-watching
the same inbox).

## The tray app

`intake tray` puts an icon in your menu bar / system tray:

- **blue** = watching · **amber** = working · **red** = something needs you ·
  **grey** = paused
- Pause/resume, open the inbox / review / repo / logs
- When a file needs a **new folder** and your policy is `prompt`, the request
  shows up under *Pending approvals* - approve or send to review from the menu.

---

## Configuration

Written by `intake setup` to your OS config dir
(`%LOCALAPPDATA%\intake-agent\config.toml` on Windows,
`~/Library/Application Support/intake-agent/` on macOS,
`~/.config/intake-agent/` on Linux). Key settings:

| Setting | Meaning | Default |
|---|---|---|
| `repo.root` | The repository files get filed into. | - |
| `repo.intake_dir` | Inbox folder (relative to the repo, or an absolute path - e.g. your Downloads). | `00_intake` |
| `model.name` | Claude model. | `claude-sonnet-4-6` |
| `model.confidence_threshold` | Below this, a placement is downgraded to review. | `0.55` |
| `routing.new_folder_policy` | `auto` (create automatically), `prompt` (ask), or `review` (never create). | `prompt` |
| `routing.rules_file` | Optional domain rules file in your repo. | `intake.rules.md` |

### Routing rules (optional)

Drop an `intake.rules.md` at your repo root to teach domain specifics - vendor
aliases, "tax docs go here", naming patterns. See
[`examples/example.rules.md`](examples/example.rules.md) for a full example.

### Protecting a file from being moved

Make the file's first line:

```
#INTAKE-AGENT SHOULD NEVER MOVE THIS FILE
```

Source code, scripts, and config files are skipped automatically.

---

## Safety & privacy

- The agent is **read-only** and **path-sandboxed** to your repo + the staged file.
- Document contents are sent to the Anthropic API to make the routing decision.
  Nothing else leaves your machine. Your API key lives in the OS keychain.
- Every move is logged to a local SQLite ledger and is reversible with `undo`.

---

## Requirements

- Python 3.11+
- An Anthropic API key
- Linux tray only: a system tray / AppIndicator (GNOME needs the AppIndicator
  extension). The CLI (`intake start`) needs none.

## License

MIT - see [LICENSE](LICENSE).
