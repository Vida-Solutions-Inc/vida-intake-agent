"""Intake agent configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Model
MODEL = "claude-sonnet-4-6"

# Paths — repo root is the directory containing 00_intake/
def _find_repo_root(start: Path) -> Path:
    explicit = os.environ.get("INTAKE_REPO_ROOT")
    if explicit:
        p = Path(explicit).resolve()
        if (p / "00_intake").is_dir():
            return p
        raise RuntimeError(f"INTAKE_REPO_ROOT={p} does not contain 00_intake/")
    for candidate in [start, *start.parents]:
        if (candidate / "00_intake").is_dir():
            return candidate
    raise RuntimeError(
        f"No 00_intake/ found walking up from {start}. "
        f"Set INTAKE_REPO_ROOT in .env to point at the repo root."
    )

AGENT_DIR = Path(__file__).parent
REPO_ROOT = _find_repo_root(AGENT_DIR)
INTAKE_DIR = REPO_ROOT / "00_intake"
REVIEW_DIR = INTAKE_DIR / "review"
LOG_DIR = AGENT_DIR / "logs"
SYSTEM_PROMPT_FILE = AGENT_DIR / "AGENT.md"

# Local staging dir — files are copied here from OneDrive before the agent
# reads them, to avoid native crashes from OneDrive sync touching the file
# mid-read. Cleaned up after each item.
TEMP_ROOT = Path(os.environ.get("INTAKE_TEMP_ROOT", r"C:\Temp\intake_agent"))

# Auth
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Files we never route — scripts, code, dotfiles
SKIP_EXTENSIONS = {
    ".bat", ".ps1", ".sh", ".exe", ".cmd",
    ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}

# Filename Claude must never move (sentinel marker file)
SKIP_MARKER = "#INTAKE-AGENT SHOULD NEVER MOVE THIS FILE"

# Stability poll: wait until file size + mtime are unchanged for this long
STABILITY_SECONDS = 2.0
STABILITY_POLL_INTERVAL = 0.5
STABILITY_TIMEOUT = 60.0

# Cap per-file tool calls to bound cost
MAX_TURNS = 25
