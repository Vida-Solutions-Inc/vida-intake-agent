"""IntakeService: watch the inbox, run each file through the agent, act on it.

Threaded (not asyncio) so it composes cleanly with a system-tray UI:
- a watchdog Observer feeds new paths into a queue,
- a single worker thread processes them serially (serial avoids two files
  racing to create the same new folder),
- pause/resume/stop are thread-safe events.

Pipeline per file: stability wait -> stage a local copy -> agent decides ->
mover acts -> clean up the staged copy.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .approvals import Approver, approver_for_policy
from .config import Config
from .ledger import Ledger
from .logging_setup import get_logger
from .models import Outcome, RoutingResult
from .mover import Mover
from .router import Router

# First-line sentinel: a file starting with this is never moved.
SKIP_MARKER = "#INTAKE-AGENT SHOULD NEVER MOVE THIS FILE"

EventCallback = Callable[[RoutingResult], None]


class IntakeService:
    def __init__(
        self,
        config: Config,
        api_key: str,
        *,
        approver: Optional[Approver] = None,
        logger: Optional[logging.Logger] = None,
        on_event: Optional[EventCallback] = None,
        dry_run: bool = False,
    ):
        self.config = config
        self.dry_run = dry_run
        self.log = logger or get_logger()
        self.on_event = on_event

        self.ledger = Ledger()
        self.router = Router(config, api_key)
        self.mover = Mover(config, self.ledger, approver or approver_for_policy(config.new_folder_policy), self.log)

        self._queue: "queue.Queue[Path]" = queue.Queue()
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._observer: Optional[Observer] = None
        self._worker: Optional[threading.Thread] = None
        self._processed = 0

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._ensure_dirs()
        self.config.staging_path.mkdir(parents=True, exist_ok=True)
        self.process_existing()

        handler = _IntakeHandler(self._enqueue, self.config.intake_path, self.config.review_path)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.config.intake_path), recursive=False)
        self._observer.start()

        self._worker = threading.Thread(target=self._run_worker, name="intake-worker", daemon=True)
        self._worker.start()
        self.log.info(f"Watching {self.config.intake_path}  ->  {self.config.repo_path}"
                      f"  [{'DRY-RUN' if self.dry_run else 'LIVE'}]")

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def drain_and_stop(self) -> None:
        """For `--once`: process whatever's queued, then stop."""
        self._ensure_dirs()
        self.config.staging_path.mkdir(parents=True, exist_ok=True)
        self.process_existing()
        self._worker = threading.Thread(target=self._run_worker, name="intake-worker", daemon=True)
        self._worker.start()
        self._queue.join()
        self.stop()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self.ledger.close()

    def pause(self) -> None:
        self._resume.clear()
        self.log.info("Paused.")

    def resume(self) -> None:
        self._resume.set()
        self.log.info("Resumed.")

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def running(self) -> bool:
        return self._observer is not None and not self._stop.is_set()

    def stats(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "queued": self._queue.qsize(),
            "processed_session": self._processed,
            "today": self.ledger.counts_today(),
        }

    # ---------------------------------------------------------------- queueing
    def process_existing(self) -> None:
        if not self.config.intake_path.exists():
            return
        for p in sorted(self.config.intake_path.iterdir()):
            if p.name == self.config.review_subdir or p.name.startswith("."):
                continue
            self._enqueue(p)

    def _enqueue(self, path: Path) -> None:
        key = str(path)
        with self._seen_lock:
            if key in self._seen:
                return
            self._seen.add(key)
        self._queue.put(path)

    # ------------------------------------------------------------------ worker
    def _run_worker(self) -> None:
        while not self._stop.is_set():
            self._resume.wait()
            if self._stop.is_set():
                break
            try:
                path = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_one(path)
            except Exception as e:
                self.log.error(f"ERROR    {path.name}  unhandled: {type(e).__name__}: {e}")
            finally:
                self._queue.task_done()
                with self._seen_lock:
                    self._seen.discard(str(path))

    def _process_one(self, path: Path) -> None:
        if not path.exists() or self._should_skip(path):
            return
        self.log.info(f"QUEUED   {path.name}")

        if not self._wait_until_stable(path):
            self.log.warning(f"UNSTABLE {path.name}  (kept changing or vanished) - re-drop it")
            return

        if self.dry_run:
            self.log.info(f"DRY-RUN  would route {path.name}")
            return

        try:
            staged = self._stage(path)
        except Exception as e:
            self.log.error(f"ERROR    {path.name}  staging failed: {e}")
            return

        try:
            try:
                verdict = self.router.decide(staged, original_filename=path.name)
            except Exception as e:
                self.log.error(f"ERROR    {path.name}  agent failed: {type(e).__name__}: {e}")
                result = self.mover._to_review(path, f"agent error: {type(e).__name__}", _empty_verdict())
                self._emit(result)
                return
            result = self.mover.apply(verdict, path)
            self._processed += 1
            self._emit(result)
        finally:
            self._cleanup_staging(staged)

    def _emit(self, result: RoutingResult) -> None:
        if self.on_event:
            try:
                self.on_event(result)
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def _ensure_dirs(self) -> None:
        self.config.intake_path.mkdir(parents=True, exist_ok=True)
        self.config.review_path.mkdir(parents=True, exist_ok=True)

    def _should_skip(self, path: Path) -> bool:
        if path.name.startswith("."):
            return True
        if path.is_dir():
            return True  # folders are not routed in this version
        if path.suffix.lower() in set(self.config.skip_extensions):
            return True
        return self._is_protected(path)

    @staticmethod
    def _is_protected(path: Path) -> bool:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return f.readline().startswith(SKIP_MARKER)
        except Exception:
            return False

    def _wait_until_stable(self, path: Path) -> bool:
        deadline = time.monotonic() + self.config.stability_timeout
        last_sig = None
        stable_since = None
        while time.monotonic() < deadline:
            if not path.exists():
                return False
            try:
                stat = path.stat()
                sig = (stat.st_size, int(stat.st_mtime))
            except (FileNotFoundError, PermissionError):
                time.sleep(self.config.poll_interval)
                continue
            now = time.monotonic()
            if sig == last_sig:
                if stable_since is None:
                    stable_since = now
                elif now - stable_since >= self.config.stability_seconds:
                    return True
            else:
                last_sig = sig
                stable_since = None
            time.sleep(self.config.poll_interval)
        return False

    def _stage(self, path: Path) -> Path:
        staging_dir = self.config.staging_path / uuid.uuid4().hex
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged = staging_dir / path.name
        shutil.copy2(path, staged)
        return staged

    @staticmethod
    def _cleanup_staging(staged: Path) -> None:
        try:
            shutil.rmtree(staged.parent, ignore_errors=True)
        except Exception:
            pass


class _IntakeHandler(FileSystemEventHandler):
    def __init__(self, enqueue: Callable[[Path], None], intake_dir: Path, review_dir: Path):
        self._enqueue = enqueue
        self._intake = intake_dir.resolve()
        self._review = review_dir.resolve()

    def on_created(self, event):
        self._maybe(event.src_path)

    def on_moved(self, event):
        self._maybe(getattr(event, "dest_path", None))

    def _maybe(self, raw: Optional[str]) -> None:
        if not raw:
            return
        path = Path(raw)
        try:
            resolved = path.resolve()
        except OSError:
            return
        # Only direct children of the inbox, never the review subtree.
        if resolved.parent != self._intake:
            return
        if resolved == self._review:
            return
        self._enqueue(path)


def _empty_verdict():
    from .models import Verdict
    return Verdict(outcome=Outcome.REVIEW, reason="agent error")
