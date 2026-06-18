"""Command-line interface: `intake <command>`.

Commands:
  setup     Interactive first-run configuration.
  start     Watch the inbox and route files (Ctrl-C to stop).
  once      Process whatever is in the inbox now, then exit.
  tray      Launch the system-tray desktop app.
  status    Show current config and recent activity.
  doctor    Diagnose configuration and connectivity problems.
  history   List recent routing actions.
  undo      Reverse a routing action by its id.
  config    Print the active config file path and contents.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_DISPLAY_NAME, __version__

try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()
except Exception:  # rich is a core dep, but degrade gracefully just in case
    _console = None


def _print(msg: str = "") -> None:
    if _console:
        _console.print(msg)
    else:
        print(_strip_markup(msg))


def _strip_markup(s: str) -> str:
    import re
    return re.sub(r"\[/?[a-z0-9 _#]+\]", "", s)


# --------------------------------------------------------------------- commands
def cmd_setup(args) -> int:
    from .setup_wizard import run_setup
    return run_setup(reconfigure=args.reconfigure)


def cmd_start(args) -> int:
    cfg, key = _load_or_die()
    from .watcher import IntakeService
    _print(f"[bold]{APP_DISPLAY_NAME}[/bold] starting…  (Ctrl-C to stop)")
    service = IntakeService(cfg, key, dry_run=args.dry_run)
    service.run_forever()
    return 0


def cmd_once(args) -> int:
    cfg, key = _load_or_die()
    from .watcher import IntakeService
    service = IntakeService(cfg, key, dry_run=args.dry_run)
    service.drain_and_stop()
    _print("[green]Done.[/green]")
    return 0


def cmd_tray(args) -> int:
    try:
        from .tray import run_tray
    except Exception as e:
        _print(f"[red]Tray app unavailable:[/red] {e}")
        _print("Install the tray extra:  [cyan]pip install 'intake-agent[tray]'[/cyan]")
        return 1
    cfg, key = _load_or_die()
    return run_tray(cfg, key)


def cmd_status(args) -> int:
    from .config import load_config, resolve_api_key, config_exists
    from .ledger import Ledger
    from .platform_utils import config_file
    if not config_exists():
        _print("[yellow]Not configured.[/yellow]  Run [cyan]intake setup[/cyan].")
        return 1
    cfg = load_config()
    key = resolve_api_key(cfg)
    _print(f"[bold]{APP_DISPLAY_NAME} {__version__}[/bold]")
    _print(f"Config:   {config_file()}")
    _print(f"Repo:     {cfg.repo_path}")
    _print(f"Inbox:    {cfg.intake_path}")
    _print(f"Review:   {cfg.review_path}")
    _print(f"Model:    {cfg.model}")
    _print(f"Policy:   new folders = {cfg.new_folder_policy}")
    _print(f"API key:  {'set' if key else '[red]missing[/red]'}")
    ledger = Ledger()
    today = ledger.counts_today()
    if today:
        summary = "  ".join(f"{k}={v}" for k, v in today.items())
        _print(f"Today:    {summary}")
    _recent_table(ledger, 10)
    ledger.close()
    return 0


def cmd_doctor(args) -> int:
    from .config import load_config, resolve_api_key, config_exists
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        mark = "[green]OK[/green]" if passed else "[red]FAIL[/red]"
        _print(f"  {mark}  {label}" + (f"  — {detail}" if detail else ""))

    _print("[bold]Diagnostics[/bold]")
    check("config file present", config_exists(), "" if config_exists() else "run `intake setup`")
    if not config_exists():
        return 1
    cfg = load_config()
    for problem in cfg.validate():
        check("config valid", False, problem)
    if not cfg.validate():
        check("config valid", True)
    check("repo exists", cfg.repo_path.is_dir(), str(cfg.repo_path))
    check("inbox exists", cfg.intake_path.exists(), str(cfg.intake_path))

    key = resolve_api_key(cfg)
    check("API key resolves", bool(key))
    if key:
        check("API reachable", *_ping(cfg, key))

    _print("\n[bold]Optional features[/bold]")
    _print(f"  PDF/Office extraction: {_have('pypdf')}")
    _print(f"  Images (Pillow):       {_have('PIL')}")
    _print(f"  Tray app (pystray):    {_have('pystray')}")
    _print(f"  Keychain (keyring):    {_have('keyring')}")
    return 0 if ok else 1


def cmd_history(args) -> int:
    from .ledger import Ledger
    ledger = Ledger()
    _recent_table(ledger, args.n)
    ledger.close()
    return 0


def cmd_undo(args) -> int:
    cfg, _ = _load_or_die(require_key=False)
    from .approvals import ReviewApprover
    from .ledger import Ledger
    from .logging_setup import get_logger
    from .mover import Mover
    ledger = Ledger()
    mover = Mover(cfg, ledger, ReviewApprover(), get_logger())
    try:
        restored = mover.undo(args.id)
        _print(f"[green]Undone.[/green] Restored to inbox: {restored}")
        return 0
    except ValueError as e:
        _print(f"[red]Cannot undo:[/red] {e}")
        return 1
    finally:
        ledger.close()


def cmd_config(args) -> int:
    from .platform_utils import config_file
    cf = config_file()
    _print(f"Config file: {cf}")
    if cf.exists():
        _print("")
        _print(cf.read_text(encoding="utf-8"))
    else:
        _print("[yellow](does not exist — run `intake setup`)[/yellow]")
    return 0


# --------------------------------------------------------------------- helpers
def _load_or_die(require_key: bool = True):
    from .config import ConfigError, load_config, resolve_api_key
    try:
        cfg = load_config()
    except ConfigError as e:
        _print(f"[red]{e}[/red]")
        sys.exit(1)
    problems = cfg.validate()
    if problems:
        _print("[red]Config problems:[/red]")
        for p in problems:
            _print(f"  - {p}")
        sys.exit(1)
    key = resolve_api_key(cfg)
    if require_key and not key:
        _print("[red]No API key found.[/red] Run [cyan]intake setup[/cyan] or set ANTHROPIC_API_KEY.")
        sys.exit(1)
    return cfg, key


def _recent_table(ledger, n: int) -> None:
    rows = ledger.recent(n)
    if not rows:
        _print("[dim]No routing history yet.[/dim]")
        return
    if _console:
        table = Table(title=f"Last {len(rows)} actions", show_lines=False)
        table.add_column("#", justify="right")
        table.add_column("when")
        table.add_column("file")
        table.add_column("outcome")
        table.add_column("destination")
        for r in reversed(rows):
            dest = Path(r.dest_path).name if r.dest_path else ""
            tag = ("[strike]" + r.outcome + "[/strike]") if r.undone else r.outcome
            table.add_row(str(r.id), r.ts[5:16].replace("T", " "), r.source_name, tag, dest)
        _console.print(table)
    else:
        for r in reversed(rows):
            print(f"  #{r.id}  {r.ts}  {r.source_name} -> {r.outcome} {r.dest_path or ''}")


def _ping(cfg, key) -> tuple[bool, str]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=20, max_retries=0)
        client.messages.create(model=cfg.model, max_tokens=1, messages=[{"role": "user", "content": "hi"}])
        return True, cfg.model
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _have(mod: str) -> str:
    import importlib.util
    return "[green]installed[/green]" if importlib.util.find_spec(mod) else "[dim]not installed[/dim]"


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="intake", description=f"{APP_DISPLAY_NAME} — route inbox files into your repo with Claude.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("setup", help="Interactive first-run configuration.")
    s.add_argument("--reconfigure", action="store_true", help="Edit an existing config.")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("start", help="Watch the inbox and route files.")
    s.add_argument("--dry-run", action="store_true", help="Detect files but don't call the agent or move anything.")
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("once", help="Process the current inbox, then exit.")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_once)

    s = sub.add_parser("tray", help="Launch the system-tray desktop app.")
    s.set_defaults(func=cmd_tray)

    s = sub.add_parser("status", help="Show config and recent activity.")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("doctor", help="Diagnose configuration and connectivity.")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("history", help="List recent routing actions.")
    s.add_argument("-n", type=int, default=20, help="How many entries.")
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("undo", help="Reverse a routing action by id.")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_undo)

    s = sub.add_parser("config", help="Print the active config file.")
    s.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _print("\n[dim]Interrupted.[/dim]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
