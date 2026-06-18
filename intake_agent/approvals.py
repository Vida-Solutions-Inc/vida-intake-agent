"""Approval strategies for creating a new destination folder.

The watcher asks an Approver before creating a folder that doesn't exist yet.
Different front-ends supply different strategies: the CLI prompts on the
terminal, the tray app pops a dialog, headless/service runs auto-approve or
defer to review. Each returns the approved repo-relative folder (possibly
overridden by the user) or None to decline.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional, Protocol


class Approver(Protocol):
    def approve_new_folder(self, file_name: str, proposed_rel: str, reason: str) -> Optional[str]:
        ...


class AutoApprover:
    """Create new folders automatically (guard-rails enforced by the mover)."""

    def approve_new_folder(self, file_name, proposed_rel, reason):
        return proposed_rel


class ReviewApprover:
    """Never create folders; the file is routed to review/ instead."""

    def approve_new_folder(self, file_name, proposed_rel, reason):
        return None


class CliApprover:
    """Prompt on the terminal. Falls back to declining when there is no TTY."""

    def approve_new_folder(self, file_name, proposed_rel, reason):
        if not (sys.stdin and sys.stdin.isatty()):
            return None
        print()
        print(f"  New folder needed for: {file_name}")
        print(f"  Proposed: {proposed_rel}")
        print(f"  Reason:   {reason}")
        print("  [Enter] approve | type a different path | 'r' review")
        try:
            resp = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if resp.lower() in ("r", "review", "n", "no"):
            return None
        if resp == "":
            return proposed_rel
        return resp.replace("\\", "/").strip("/") + "/"


class CallbackApprover:
    """Delegates to a callable - used by the tray app to show a dialog.

    The callback receives (file_name, proposed_rel, reason) and returns the
    approved path, or None to decline.
    """

    def __init__(self, callback: Callable[[str, str, str], Optional[str]]):
        self._cb = callback

    def approve_new_folder(self, file_name, proposed_rel, reason):
        try:
            return self._cb(file_name, proposed_rel, reason)
        except Exception:
            return None


def approver_for_policy(policy: str) -> Approver:
    if policy == "auto":
        return AutoApprover()
    if policy == "prompt":
        return CliApprover()
    return ReviewApprover()
