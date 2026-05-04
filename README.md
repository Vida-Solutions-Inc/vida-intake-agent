# Intake Agent

A daemon that watches `00_intake/` and routes dropped files to the correct location in the repo. Built on the Claude Agent SDK — Claude does the routing using its standard tools (Read, Glob, Bash); this repo is just the watcher and the system prompt.

## Architecture

```
watcher.py   watchdog -> stability check -> async queue (serial)
agent.py     spawns Claude Agent SDK per item, parses RESULT line
AGENT.md     system prompt: repo map + routing rules
config.py    paths, model, skip lists, stability tuning
```

**Split of responsibility:**
- **Agent (read-only)** — Read, Glob, Grep, Skill. Decides destination + filename, emits a VERDICT line. Cannot move or write anything.
- **Watcher** — performs the actual `shutil.move`, creates new folders, dedupes by hash, routes uncertain items to `review/`, cleans up the staged copy.

This split means the agent can't lie about a move succeeding, and a crash mid-loop never leaves files in a half-routed state.

**Staging:** files are copied to `C:\Temp\intake_agent\<uuid>\` before the agent reads them. Reading straight out of OneDrive caused intermittent 0xC0000005 native crashes (sync touching the file mid-read). The staged copy isolates the read path. Override the staging root with `INTAKE_TEMP_ROOT` in `.env`.

## Setup

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY (and optional INTAKE_REPO_ROOT)
pip install -r requirements.txt
python watcher.py
```

Place this folder anywhere. By default it walks up from `watcher.py` until it finds a directory containing `00_intake/`. To force a specific repo, set `INTAKE_REPO_ROOT` in `.env`.

## Run modes

```bash
python watcher.py              # daemon: watch + process forever
python watcher.py --once       # process whatever's in 00_intake/ now, then exit
python watcher.py --dry-run    # log what would be done; don't call the agent
```

## How the agent decides

See [AGENT.md](AGENT.md) — that's the full system prompt the SDK sends. Routing rules, hard rules, and the RESULT-line contract live there. Edit `AGENT.md` to change behavior; no Python changes needed for routing tweaks.

## Outcomes

Each item ends with one log line:

| Outcome | Meaning |
|---|---|
| `MOVED` | File placed at destination. |
| `NEW_FOLDER` | Agent created a folder (you approved the prompt) and moved the file in. |
| `REVIEW` | Agent wasn't confident; file is in `00_intake/review/` with a reason. |
| `UNSTABLE` | File kept changing during stability poll — re-drop it. |
| `ERROR` | Agent loop failed. Check the log for the traceback. |

## Why a serial queue

If two files drop at once and both want a new vendor folder, processing them in parallel races on `mkdir`. Serial is slightly slower but avoids duplicate folders and double-prompts.

## Approving new folders

When the agent calls `mkdir`, the Agent SDK prompts you in the daemon's terminal:
```
Allow Bash(mkdir -p "admin/Finance/02_Expenses/Vendors/Apify")? [y/n]
```
Approve once per new folder. Future files going to the same folder won't prompt.

If you want auto-approval for known-safe patterns later (e.g. any new vendor under `Vendors/`), add a permission hook in `agent.py` — the SDK exposes `can_use_tool` for that.

## Logs

`logs/intake_YYYY-MM-DD.log` — one file per day. Captures every queued item, stability outcome, and final RESULT line.
