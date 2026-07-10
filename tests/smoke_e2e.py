"""Live end-to-end smoke test: builds a throwaway repo, drops sample files into
the inbox, runs the real agent once, and prints where each landed.

Usage:  python tests/smoke_e2e.py
Requires ANTHROPIC_API_KEY in the environment (or .env loaded by the caller).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intake_agent.config import Config
from intake_agent.logging_setup import get_logger
from intake_agent.watcher import IntakeService


def build_repo(root: Path) -> None:
    for d in [
        "finance/Expenses/Vendors/Anthropic",
        "finance/Banking/Chase Checking",
        "legal/Contracts",
        "clients/acme",
        "marketing",
        "00_intake/review",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    # a few siblings so the agent can learn a naming convention
    vend = root / "finance/Expenses/Vendors/Anthropic"
    (vend / "2026-01-15_anthropic_invoice.pdf").write_text("x")
    (vend / "2026-02-15_anthropic_invoice.pdf").write_text("x")
    (vend / "2026-03-15_anthropic_invoice.pdf").write_text("x")


SAMPLES = {
    "anthropic_receipt.txt": (
        "Anthropic, PBC\nInvoice #INV-2026-0042\nDate: 2026-04-15\n"
        "Claude API usage — April 2026\nAmount due: $284.10\nBilled to: Acme Corp\n"
    ),
    "chase_statement.txt": (
        "CHASE\nChase Total Checking\nStatement period: 04/01/2026 - 04/30/2026\n"
        "Beginning balance $5,000  Ending balance $4,210\n"
    ),
    "mystery.txt": "lorem ipsum dolor sit amet, nothing identifying here at all\n",
}


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY first.")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="intake_e2e_"))
    repo = tmp / "repo"
    repo.mkdir()
    build_repo(repo)
    for name, body in SAMPLES.items():
        (repo / "00_intake" / name).write_text(body, encoding="utf-8")

    cfg = Config(repo_root=str(repo), new_folder_policy="auto", model="claude-sonnet-4-6")
    service = IntakeService(cfg, os.environ["ANTHROPIC_API_KEY"], logger=get_logger())
    service.drain_and_stop()

    print("\n=== RESULT TREE ===")
    for p in sorted(repo.rglob("*")):
        if p.is_file():
            print("  ", p.relative_to(repo).as_posix())
    print(f"\n(temp repo: {repo})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
