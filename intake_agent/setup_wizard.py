"""Interactive first-run setup: `intake setup`.

Gathers the repo path, inbox location, model, new-folder policy, and API key,
validates them, stores the key in the OS keychain when possible, writes the
config, and optionally scaffolds a starter rules file. Designed so a
non-technical recipient can get running by answering a handful of prompts.
"""

from __future__ import annotations

import getpass
from pathlib import Path

from . import APP_DISPLAY_NAME
from .config import (
    Config,
    DEFAULT_MODEL,
    config_exists,
    load_config,
    resolve_api_key,
    save_config,
    store_api_key,
)
from .platform_utils import config_file

try:
    from rich.console import Console
    _c = Console()
    def out(m=""): _c.print(m)
except Exception:
    def out(m=""):
        import re
        print(re.sub(r"\[/?[a-z0-9 _#]+\]", "", str(m)))

RULES_TEMPLATE = """\
# Intake routing rules for this repository

These rules guide the agent on top of its general judgement and the live folder
structure. Keep them short and concrete. Delete the examples and add your own.

## Where things go
- Vendor receipts and invoices -> `admin/Finance/Expenses/Vendors/<Vendor>/`
- Bank / credit-card statements -> `admin/Finance/Banking/<Account>/`
- Signed contracts -> `admin/Legal/Contracts/`
- Client deliverables -> `clients/<client>/`

## Aliases
- "acme", "acme corp" -> clients/acme/

## Naming conventions
- Invoices: `YYYY-MM-DD_<vendor>_invoice.pdf`

## Hard rules
- Never route source code or scripts.
"""


def run_setup(reconfigure: bool = False) -> int:
    out(f"[bold]{APP_DISPLAY_NAME} setup[/bold]\n")

    existing = load_config() if config_exists() else None
    if existing and not reconfigure:
        out(f"A config already exists at [cyan]{config_file()}[/cyan].")
        if not _yes("Reconfigure it?", default=False):
            out("Leaving it unchanged.")
            return 0
    cfg = existing or Config()

    # --- repo root ---------------------------------------------------------
    out("\n[bold]1. Repository[/bold] - the folder your files get filed into.")
    repo = _ask_path("Path to your repository", cfg.repo_root or str(Path.cwd()))
    while not repo.is_dir():
        out(f"[red]Not a folder:[/red] {repo}")
        repo = _ask_path("Path to your repository", str(Path.cwd()))
    cfg.repo_root = str(repo)

    # --- inbox -------------------------------------------------------------
    out("\n[bold]2. Inbox[/bold] - drop files here to have them filed.")
    intake_default = cfg.intake_dir or "00_intake"
    intake = _ask("Inbox folder (relative to the repo, or an absolute path)", intake_default)
    cfg.intake_dir = intake
    cfg.intake_path.mkdir(parents=True, exist_ok=True)
    cfg.review_path.mkdir(parents=True, exist_ok=True)
    out(f"   Inbox:  [cyan]{cfg.intake_path}[/cyan]")

    # --- model + policy ----------------------------------------------------
    out("\n[bold]3. Behaviour[/bold]")
    cfg.model = _ask("Model", cfg.model or DEFAULT_MODEL)
    out("   New-folder policy: [cyan]auto[/cyan]=create automatically, "
        "[cyan]prompt[/cyan]=ask first, [cyan]review[/cyan]=never (send to review).")
    policy = _ask("Policy [auto/prompt/review]", cfg.new_folder_policy or "prompt").lower()
    cfg.new_folder_policy = policy if policy in ("auto", "prompt", "review") else "prompt"

    # --- rules file --------------------------------------------------------
    out("\n[bold]4. Routing rules (optional)[/bold]")
    rules_path = cfg.rules_path
    if rules_path and not rules_path.exists():
        if _yes(f"Create a starter rules file at {rules_path.name}?", default=True):
            rules_path.write_text(RULES_TEMPLATE, encoding="utf-8")
            out(f"   Wrote [cyan]{rules_path}[/cyan] - edit it to teach domain rules.")

    # --- API key -----------------------------------------------------------
    out("\n[bold]5. Anthropic API key[/bold]")
    current = resolve_api_key(cfg)
    if current and not _yes("An API key is already configured. Replace it?", default=False):
        pass
    else:
        key = _ask_secret("Paste your Anthropic API key (input hidden)")
        if key:
            backend = store_api_key(key)
            if backend == "keychain":
                out("   Stored in your OS keychain.")
                cfg.api_key_inline = ""
            else:
                out("   [yellow]keyring not available[/yellow] - storing in the config file. "
                    "Install the keyring extra for secure storage.")
                cfg.api_key_inline = key

    # --- save --------------------------------------------------------------
    path = save_config(cfg)
    out(f"\n[green]Saved[/green] config to [cyan]{path}[/cyan]")

    # --- verify ------------------------------------------------------------
    key = resolve_api_key(cfg)
    if key:
        ok, detail = _ping(cfg, key)
        out(f"API check: {'[green]OK[/green]' if ok else '[red]failed[/red]'}  {detail}")

    out("\n[bold]Next:[/bold]")
    out("  [cyan]intake start[/cyan]   watch the inbox in this terminal")
    out("  [cyan]intake tray[/cyan]    run as a tray app")
    out("  [cyan]intake doctor[/cyan]  re-check everything")
    return 0


# --------------------------------------------------------------------- prompts
def _ask(label: str, default: str = "") -> str:
    suffix = f" [[dim]{default}[/dim]]" if default else ""
    out(f"{label}{suffix}:")
    try:
        resp = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return resp or default


def _ask_path(label: str, default: str) -> Path:
    return Path(_ask(label, default)).expanduser()


def _ask_secret(label: str) -> str:
    out(label + ":")
    try:
        return getpass.getpass("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _yes(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    out(f"{label} [{hint}]")
    try:
        resp = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not resp:
        return default
    return resp in ("y", "yes")


def _ping(cfg: Config, key: str) -> tuple[bool, str]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=20, max_retries=0)
        client.messages.create(model=cfg.model, max_tokens=1, messages=[{"role": "user", "content": "hi"}])
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"
