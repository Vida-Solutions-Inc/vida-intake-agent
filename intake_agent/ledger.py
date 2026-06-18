"""SQLite audit ledger of every routing action - powers `history` and `undo`.

Every move is recorded with where the file came from and went, so a misroute can
be reversed and the user has a durable trail of what the agent did.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .platform_utils import data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    origin_path  TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    dest_path    TEXT,
    created_dir  INTEGER NOT NULL DEFAULT 0,
    confidence   REAL,
    reason       TEXT,
    undone       INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class LedgerEntry:
    id: int
    ts: str
    source_name: str
    origin_path: str
    outcome: str
    dest_path: str | None
    created_dir: bool
    confidence: float | None
    reason: str | None
    undone: bool


class Ledger:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (data_dir() / "history.db")
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def record(
        self,
        *,
        source_name: str,
        origin_path: str,
        outcome: str,
        dest_path: str | None,
        created_dir: bool,
        confidence: float | None,
        reason: str | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO routes (ts, source_name, origin_path, outcome, dest_path, "
            "created_dir, confidence, reason) VALUES (?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                source_name, origin_path, outcome, dest_path,
                int(created_dir), confidence, reason,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[LedgerEntry]:
        rows = self._conn.execute(
            "SELECT * FROM routes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, entry_id: int) -> LedgerEntry | None:
        row = self._conn.execute("SELECT * FROM routes WHERE id=?", (entry_id,)).fetchone()
        return self._row(row) if row else None

    def mark_undone(self, entry_id: int) -> None:
        self._conn.execute("UPDATE routes SET undone=1 WHERE id=?", (entry_id,))
        self._conn.commit()

    def counts_today(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        rows = self._conn.execute(
            "SELECT outcome, COUNT(*) c FROM routes WHERE substr(ts,1,10)=? GROUP BY outcome",
            (today,),
        ).fetchall()
        return {r["outcome"]: r["c"] for r in rows}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    @staticmethod
    def _row(r: sqlite3.Row) -> LedgerEntry:
        return LedgerEntry(
            id=r["id"], ts=r["ts"], source_name=r["source_name"],
            origin_path=r["origin_path"], outcome=r["outcome"], dest_path=r["dest_path"],
            created_dir=bool(r["created_dir"]), confidence=r["confidence"],
            reason=r["reason"], undone=bool(r["undone"]),
        )
