"""Act on a Verdict: move the file, create folders (guard-railed), dedup, and
record everything in the ledger. Also implements `undo`.

This is the only component that writes to the repo. The agent never does. That
split means a crash mid-decision can never leave a half-routed file, and the
agent cannot fabricate a successful move.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from .approvals import Approver
from .config import Config
from .ledger import Ledger
from .models import Outcome, RoutingResult, Verdict

_MAX_NEW_FOLDER_DEPTH = 8


class Mover:
    def __init__(self, config: Config, ledger: Ledger, approver: Approver, logger: logging.Logger):
        self.config = config
        self.ledger = ledger
        self.approver = approver
        self.log = logger

    # ----------------------------------------------------------------- apply
    def apply(self, verdict: Verdict, source: Path) -> RoutingResult:
        name = source.name

        if verdict.outcome in (Outcome.REVIEW, Outcome.UNKNOWN, Outcome.SKIP):
            return self._to_review(source, verdict.reason or verdict.outcome.value, verdict)

        # MOVE - but gate on confidence first.
        if verdict.confidence < self.config.confidence_threshold:
            return self._to_review(
                source,
                f"low confidence {verdict.confidence:.2f} < {self.config.confidence_threshold:.2f}: {verdict.reason}",
                verdict,
            )

        try:
            dest_dir = self._safe_dest_folder(verdict.dest_folder)
        except ValueError as e:
            return self._to_review(source, f"unusable destination: {e}", verdict)

        final_name = self._safe_filename(verdict.new_filename, name)
        creating = not dest_dir.exists()

        if creating:
            try:
                self._check_new_folder(dest_dir)
            except ValueError as e:
                return self._to_review(source, f"rejected new folder: {e}", verdict)
            approved = self.approver.approve_new_folder(
                name, dest_dir.relative_to(self.config.repo_path).as_posix() + "/", verdict.reason
            )
            if approved is None:
                return self._to_review(source, "new folder declined", verdict)
            try:
                dest_dir = self._safe_dest_folder(approved)
                self._check_new_folder(dest_dir) if not dest_dir.exists() else None
            except ValueError as e:
                return self._to_review(source, f"override path invalid: {e}", verdict)
            creating = not dest_dir.exists()

        try:
            final_path = self._safe_move(source, dest_dir, final_name)
        except FileExistsError as e:
            return self._to_review(source, f"duplicate: {e}", verdict)
        except Exception as e:
            self.log.error(f"ERROR    {name}  move failed: {e}")
            return RoutingResult(name, Outcome.UNKNOWN, error=str(e), reason=verdict.reason)

        rel = final_path.relative_to(self.config.repo_path).as_posix()
        ledger_id = self.ledger.record(
            source_name=name, origin_path=str(source), outcome="MOVE",
            dest_path=str(final_path), created_dir=creating,
            confidence=verdict.confidence, reason=verdict.reason,
        )
        tag = "NEW_DIR " if creating else "MOVED   "
        self.log.log(
            logging.WARNING if creating else logging.INFO,
            f"{tag} {name}  ->  {rel}  ({verdict.confidence:.2f})  |  {verdict.reason}",
        )
        return RoutingResult(
            name, Outcome.MOVE, dest_path=final_path, created_folder=creating,
            confidence=verdict.confidence, reason=verdict.reason, ledger_id=ledger_id,
        )

    # ----------------------------------------------------------------- review
    def _to_review(self, source: Path, reason: str, verdict: Verdict) -> RoutingResult:
        try:
            final_path = self._safe_move(source, self.config.review_path, source.name)
        except Exception as e:
            self.log.error(f"ERROR    {source.name}  review move failed: {e}")
            return RoutingResult(source.name, Outcome.UNKNOWN, error=str(e), reason=reason)
        rel = final_path.relative_to(self.config.repo_path).as_posix()
        ledger_id = self.ledger.record(
            source_name=source.name, origin_path=str(source), outcome="REVIEW",
            dest_path=str(final_path), created_dir=False,
            confidence=verdict.confidence, reason=reason,
        )
        self.log.warning(f"REVIEW   {source.name}  ->  {rel}  |  {reason}")
        return RoutingResult(
            source.name, Outcome.REVIEW, dest_path=final_path,
            confidence=verdict.confidence, reason=reason, ledger_id=ledger_id,
        )

    # ------------------------------------------------------------------- undo
    def undo(self, entry_id: int) -> str:
        entry = self.ledger.get(entry_id)
        if entry is None:
            raise ValueError(f"no ledger entry #{entry_id}")
        if entry.undone:
            raise ValueError(f"entry #{entry_id} was already undone")
        if not entry.dest_path:
            raise ValueError(f"entry #{entry_id} has no destination to undo")
        dest = Path(entry.dest_path)
        if not dest.exists():
            raise ValueError(f"file no longer at {dest} (moved or deleted since)")

        back_to = self.config.intake_path
        back_to.mkdir(parents=True, exist_ok=True)
        restored = self._safe_move(dest, back_to, entry.source_name)

        # Clean up a folder we created if it's now empty.
        if entry.created_dir:
            self._prune_empty(dest.parent)
        self.ledger.mark_undone(entry_id)
        return restored.relative_to(self.config.repo_path).as_posix()

    # ---------------------------------------------------------------- helpers
    def _safe_dest_folder(self, raw: str) -> Path:
        cleaned = (raw or "").replace("\\", "/").strip().strip("/")
        if not cleaned:
            raise ValueError("empty destination")
        if ".." in Path(cleaned).parts:
            raise ValueError("path traversal not allowed")
        dest = (self.config.repo_path / cleaned).resolve()
        try:
            dest.relative_to(self.config.repo_path.resolve())
        except ValueError:
            raise ValueError("destination escapes the repository")
        return dest

    def _check_new_folder(self, dest: Path) -> None:
        rel_parts = dest.relative_to(self.config.repo_path.resolve()).parts
        if len(rel_parts) > _MAX_NEW_FOLDER_DEPTH:
            raise ValueError(f"folder nesting too deep ({len(rel_parts)} levels)")
        for part in rel_parts:
            if not part or part in (".", "..") or any(c in part for c in '<>:"|?*'):
                raise ValueError(f"invalid folder name segment: {part!r}")

    def _safe_filename(self, new_filename: str, original: str) -> str:
        candidate = (new_filename or "keep").strip()
        if candidate.lower() == "keep" or not candidate:
            return original
        candidate = Path(candidate.replace("\\", "/")).name  # strip any path parts
        if not candidate or any(c in candidate for c in '<>:"|?*'):
            return original
        # Preserve the original extension if the model dropped it.
        if not Path(candidate).suffix and Path(original).suffix:
            candidate += Path(original).suffix
        return candidate

    def _safe_move(self, source: Path, dest_dir: Path, filename: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / filename
        if target.exists():
            # Same content already filed? Treat as a duplicate (-> review).
            # Note: FileExistsError is an OSError subclass, so the hash check
            # must sit outside the OSError guard or it would swallow the signal.
            try:
                same = _file_hash(target) == _file_hash(source)
            except OSError:
                same = False
            if same:
                raise FileExistsError(f"identical file already at {target}")
            stem, suffix = Path(filename).stem, Path(filename).suffix
            counter = 1
            while target.exists():
                target = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.move(str(source), str(target))
        return target

    def _prune_empty(self, folder: Path) -> None:
        try:
            cur = folder.resolve()
            repo = self.config.repo_path.resolve()
            while cur != repo and cur.is_dir() and not any(cur.iterdir()):
                cur.rmdir()
                cur = cur.parent
        except OSError:
            pass


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
