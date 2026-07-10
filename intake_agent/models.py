"""Shared data structures passed between the router, watcher, and mover."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Outcome(str, Enum):
    """What the agent decided to do with a file."""

    MOVE = "MOVE"
    REVIEW = "REVIEW"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"  # agent produced no usable verdict


@dataclass
class Verdict:
    """The agent's structured decision for one file.

    Produced by the router (via the forced ``submit_verdict`` tool) and consumed
    by the watcher/mover. This is deliberately transport-agnostic: it carries no
    absolute paths so it can be logged and stored verbatim.
    """

    outcome: Outcome
    dest_folder: str = ""          # repo-relative, e.g. "finance/Vendors/Apify/"
    new_filename: str = "keep"     # full filename with extension, or the literal "keep"
    confidence: float = 0.0        # 0.0–1.0 self-reported
    reason: str = ""
    raw_transcript: str = ""       # full model transcript, for debugging

    @classmethod
    def unknown(cls, reason: str, raw: str = "") -> "Verdict":
        return cls(outcome=Outcome.UNKNOWN, reason=reason, raw_transcript=raw)


@dataclass
class RoutingResult:
    """The final result after the watcher acted on a verdict."""

    source_name: str
    outcome: Outcome
    dest_path: Path | None = None       # absolute final location, if moved
    created_folder: bool = False
    confidence: float = 0.0
    reason: str = ""
    error: str | None = None
    ledger_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
