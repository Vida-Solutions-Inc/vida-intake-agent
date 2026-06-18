"""System-tray desktop app: `intake tray`.

A pystray icon backed by the IntakeService. The icon colour reflects state
(idle/working/attention/paused). New-folder approvals (policy = prompt) are
handled in-tray: the worker thread parks on an ApprovalBroker, the menu shows
pending requests, and the user approves/declines from the tray - no
platform-specific modal dialog required, so it works on Windows, macOS, and
Linux alike.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .approvals import CallbackApprover
from .config import Config
from .logging_setup import get_logger
from .models import Outcome, RoutingResult
from .platform_utils import open_path
from .watcher import IntakeService


# --------------------------------------------------------------- approvals
@dataclass
class _PendingApproval:
    id: int
    file_name: str
    proposed_rel: str
    reason: str
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[str] = None  # approved path, or None for declined


class ApprovalBroker:
    """Bridges the worker thread (which blocks) and the tray menu (which resolves)."""

    def __init__(self, timeout: float = 300.0):
        self._pending: dict[int, _PendingApproval] = {}
        self._lock = threading.Lock()
        self._next = 1
        self.timeout = timeout
        self.on_change = lambda: None  # set by tray to refresh menu/notify

    def request(self, file_name: str, proposed_rel: str, reason: str) -> Optional[str]:
        with self._lock:
            pid = self._next
            self._next += 1
            req = _PendingApproval(pid, file_name, proposed_rel, reason)
            self._pending[pid] = req
        self.on_change()
        approved = req.event.wait(self.timeout)
        with self._lock:
            self._pending.pop(pid, None)
        self.on_change()
        if not approved:
            return None  # timed out -> decline -> review
        return req.result

    def list_pending(self) -> list[_PendingApproval]:
        with self._lock:
            return list(self._pending.values())

    def resolve(self, pid: int, approved: bool) -> None:
        with self._lock:
            req = self._pending.get(pid)
        if req:
            req.result = req.proposed_rel if approved else None
            req.event.set()


# ------------------------------------------------------------------- tray app
class TrayApp:
    def __init__(self, config: Config, api_key: str):
        import pystray  # imported here so non-tray installs don't need it
        from .trayicon import make_icon

        self._pystray = pystray
        self._make_icon = make_icon
        self.config = config
        self.log = get_logger(console=False)
        self.broker = ApprovalBroker()
        self.broker.on_change = self._on_broker_change

        self._state = "idle"
        self._attention = False  # something needs the user's eye (review/approval)

        self.service = IntakeService(
            config, api_key,
            approver=CallbackApprover(self.broker.request),
            logger=self.log,
            on_event=self._on_event,
        )
        self.icon = pystray.Icon(
            "intake-agent",
            icon=make_icon("idle"),
            title="Intake Agent",
            menu=self._build_menu(),
        )

    # ----------------------------------------------------------------- run
    def run(self) -> int:
        self.service.start()
        threading.Thread(target=self._ticker, daemon=True).start()
        self.icon.run(setup=lambda icon: icon.notify("Watching your inbox.", "Intake Agent"))
        return 0

    # --------------------------------------------------------------- menu
    def _build_menu(self):
        p = self._pystray
        Item, Menu = p.MenuItem, p.Menu
        return Menu(
            Item(lambda i: self._status_line(), None, enabled=False),
            Item(lambda i: f"Today: {self._today_line()}", None, enabled=False),
            Menu.SEPARATOR,
            Item(
                lambda i: "Resume watching" if self.service.paused else "Pause watching",
                self._toggle_pause,
            ),
            Menu.SEPARATOR,
            Item("Pending approvals", self._approvals_submenu(),
                 visible=lambda i: bool(self.broker.list_pending())),
            Menu.SEPARATOR,
            Item("Open inbox", lambda i: open_path(self.config.intake_path)),
            Item("Open review folder", lambda i: open_path(self.config.review_path)),
            Item("Open repository", lambda i: open_path(self.config.repo_path)),
            Item("Open logs", lambda i: open_path(self._log_dir())),
            Menu.SEPARATOR,
            Item("Quit", self._quit),
        )

    def _approvals_submenu(self):
        p = self._pystray
        Item, Menu = p.MenuItem, p.Menu

        def generate():
            items = []
            for req in self.broker.list_pending():
                label = f"{req.file_name} -> {req.proposed_rel}"
                items.append(Item(
                    f"Approve: {label}",
                    (lambda pid: lambda i: self.broker.resolve(pid, True))(req.id),
                ))
                items.append(Item(
                    f"Decline (review): {req.file_name}",
                    (lambda pid: lambda i: self.broker.resolve(pid, False))(req.id),
                ))
                items.append(Menu.SEPARATOR)
            if not items:
                items = [Item("(none)", None, enabled=False)]
            return Menu(*items)

        return generate()

    # -------------------------------------------------------------- actions
    def _toggle_pause(self, icon, item) -> None:
        if self.service.paused:
            self.service.resume()
        else:
            self.service.pause()
        self._refresh()

    def _quit(self, icon, item) -> None:
        self.service.stop()
        icon.stop()

    # --------------------------------------------------------------- events
    def _on_event(self, result: RoutingResult) -> None:
        if result.outcome == Outcome.REVIEW:
            self._attention = True
            self._notify("Needs review", f"{result.source_name}: {result.reason[:80]}")
        elif result.outcome == Outcome.MOVE and result.dest_path:
            rel = result.dest_path.parent.name
            self._notify("Filed", f"{result.source_name} -> {rel}/")
        self._refresh()

    def _on_broker_change(self) -> None:
        if self.broker.list_pending():
            self._attention = True
            pend = self.broker.list_pending()[0]
            self._notify("Approve new folder?", f"{pend.file_name} -> {pend.proposed_rel}")
        self._refresh()

    # ---------------------------------------------------------------- state
    def _ticker(self) -> None:
        while self.service.running:
            self._refresh()
            time.sleep(2.0)

    def _refresh(self) -> None:
        stats = self.service.stats()
        if self.broker.list_pending() or self._attention:
            state = "attention"
        elif stats["paused"]:
            state = "paused"
        elif stats["queued"] > 0:
            state = "working"
        else:
            state = "idle"
        if state != self._state:
            self._state = state
            try:
                self.icon.icon = self._make_icon(state)
            except Exception:
                pass
        try:
            self.icon.title = "Intake Agent - " + self._status_line()
            self.icon.update_menu()
        except Exception:
            pass

    def _status_line(self) -> str:
        s = self.service.stats()
        if s["paused"]:
            return "paused"
        if self.broker.list_pending():
            return f"{len(self.broker.list_pending())} awaiting approval"
        if s["queued"]:
            return f"working ({s['queued']} queued)"
        return "watching"

    def _today_line(self) -> str:
        t = self.service.stats()["today"]
        return "  ".join(f"{k}={v}" for k, v in t.items()) if t else "nothing yet"

    def _notify(self, title: str, message: str) -> None:
        if not self.config.notifications:
            return
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    @staticmethod
    def _log_dir():
        from .platform_utils import log_dir
        return log_dir()


def run_tray(config: Config, api_key: str) -> int:
    return TrayApp(config, api_key).run()


def main() -> int:
    """Entry point for the `intake-tray` GUI script."""
    from .config import ConfigError, load_config, resolve_api_key
    from .singleton import SingleInstance
    guard = SingleInstance()
    if not guard.acquire():
        # Another instance (GUI or tray) is already watching; nothing to do.
        return 0
    try:
        try:
            cfg = load_config()
        except ConfigError:
            print("Not configured. Run `intake setup` first.")
            return 1
        key = resolve_api_key(cfg)
        if not key:
            print("No API key. Run `intake setup` first.")
            return 1
        return run_tray(cfg, key)
    finally:
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
