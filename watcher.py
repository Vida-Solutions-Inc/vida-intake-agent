"""Watchdog daemon — detects intake drops, runs them through the agent serially.

Pipeline per item:
  1. Detect drop in 00_intake/ (watchdog event)
  2. Wait until the file is stable on disk (size + mtime unchanged)
  3. Stage a local copy outside OneDrive (avoids native crashes from sync)
  4. Ask the agent (read-only) for a VERDICT
  5. Watcher performs the actual mv (and mkdir for new folders)
  6. Clean up the staged copy

Why staging: the underlying CLI subprocess crashes intermittently with
0xC0000005 when reading PDFs straight out of OneDrive — sync can rehydrate
or touch the file mid-read. Reading a local copy eliminates that race.
"""

import argparse
import asyncio
import hashlib
import logging
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path

# 0xC0000005 access violation in the SDK's Node subprocess
NATIVE_CRASH_FRAGMENTS = (
    "3221225477",
    "exit code: -1073741819",
    "Command failed with exit code",
)

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from agent import decide


def _get_logger() -> logging.Logger:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.LOG_DIR / f"intake_{date.today().isoformat()}.log"
    logger = logging.getLogger("intake")
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.setLevel(logging.INFO)
    return logger


def _is_protected(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.readline().startswith(config.SKIP_MARKER)
    except Exception:
        return False


def _should_skip(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    if path.is_file() and path.suffix.lower() in config.SKIP_EXTENSIONS:
        return True
    if path.is_file() and _is_protected(path):
        return True
    return False


async def _wait_until_stable(path: Path) -> bool:
    deadline = asyncio.get_event_loop().time() + config.STABILITY_TIMEOUT
    last_sig: tuple | None = None
    stable_since: float | None = None

    while asyncio.get_event_loop().time() < deadline:
        if not path.exists():
            return False
        try:
            if path.is_file():
                stat = path.stat()
                sig = (stat.st_size, int(stat.st_mtime))
            else:
                files = sorted(path.rglob("*"))
                sig = tuple((str(f), f.stat().st_size, int(f.stat().st_mtime))
                            for f in files if f.is_file())
        except (FileNotFoundError, PermissionError):
            await asyncio.sleep(config.STABILITY_POLL_INTERVAL)
            continue

        now = asyncio.get_event_loop().time()
        if sig == last_sig:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= config.STABILITY_SECONDS:
                return True
        else:
            last_sig = sig
            stable_since = None

        await asyncio.sleep(config.STABILITY_POLL_INTERVAL)

    return False


def _stage(path: Path) -> Path:
    """Copy file/folder to a fresh temp dir outside OneDrive. Returns staged path."""
    staging_dir = config.TEMP_ROOT / uuid.uuid4().hex
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = staging_dir / path.name
    if path.is_file():
        shutil.copy2(path, staged)
    else:
        shutil.copytree(path, staged)
    return staged


def _cleanup_staging(staged: Path) -> None:
    try:
        shutil.rmtree(staged.parent, ignore_errors=True)
    except Exception:
        pass


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_dest(verdict: dict, original_name: str) -> tuple[Path, str]:
    """Turn a VERDICT into (dest_folder_abs, final_filename)."""
    dest_folder = (verdict.get("dest_folder") or "").strip("/").strip("\\")
    if not dest_folder:
        raise ValueError("verdict has empty dest_folder")
    dest_abs = (config.REPO_ROOT / dest_folder).resolve()

    new_filename = verdict.get("new_filename", "keep").strip()
    if not new_filename or new_filename.lower() == "keep":
        final_name = original_name
    else:
        final_name = new_filename

    return dest_abs, final_name


def _safe_move(source: Path, dest_dir: Path, filename: str) -> Path:
    """Move source -> dest_dir/filename, avoiding overwrite via dedup or counter."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename

    if target.exists():
        # Same content? Treat as duplicate — do not move; caller routes to review.
        try:
            if _file_hash(target) == _file_hash(source):
                raise FileExistsError(
                    f"identical file already exists at {target}"
                )
        except OSError:
            pass
        # Different content — append counter suffix.
        stem, suffix = Path(filename).stem, Path(filename).suffix
        counter = 1
        while target.exists():
            target = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.move(str(source), str(target))
    return target


async def _process_one(path: Path, dry_run: bool) -> None:
    logger = _get_logger()
    if not path.exists():
        return
    if _should_skip(path):
        return

    logger.info(f"QUEUED   {path.name}")
    stable = await _wait_until_stable(path)
    if not stable:
        logger.warning(f"UNSTABLE {path.name}  (file kept changing or vanished)")
        return

    if dry_run:
        logger.info(f"DRY-RUN  would route {path.name}")
        return

    # Stage to local temp so the agent reads off OneDrive's hot path
    try:
        staged = _stage(path)
    except Exception as e:
        logger.error(f"ERROR    {path.name}  staging failed: {e}")
        return

    try:
        try:
            verdict = await decide(staged, original_filename=path.name)
        except Exception as e:
            msg = str(e)
            if any(frag in msg for frag in NATIVE_CRASH_FRAGMENTS):
                _route_to_review(
                    path,
                    f"native crash on every retry: {type(e).__name__}",
                    logger,
                )
            else:
                logger.error(f"ERROR    {path.name}  agent failed: {e}")
            return

        outcome = verdict["outcome"]
        reason = verdict["reason"]

        if outcome == "MOVE":
            try:
                dest_dir, final_name = _resolve_dest(verdict, path.name)
            except Exception as e:
                _dump_transcript(path, verdict, logger, label="bad-verdict")
                _route_to_review(path, f"bad verdict: {e}", logger)
                return

            # Approval prompt for new folder creation
            if not dest_dir.exists():
                approved_dir = _approve_new_folder(path, dest_dir, reason, logger)
                if approved_dir is None:
                    _route_to_review(path, "user declined new folder", logger)
                    return
                dest_dir = approved_dir

            new_folder_created = not dest_dir.exists()
            try:
                final_path = _safe_move(path, dest_dir, final_name)
            except FileExistsError as e:
                _route_to_review(path, f"duplicate: {e}", logger)
                return
            except Exception as e:
                logger.error(f"ERROR    {path.name}  move failed: {e}")
                return

            rel = final_path.relative_to(config.REPO_ROOT).as_posix()
            tag = "NEW_DIR " if new_folder_created else "MOVED   "
            level = logging.WARNING if new_folder_created else logging.INFO
            logger.log(level, f"{tag} {path.name}  ->  {rel}  |  {reason}")

        elif outcome == "REVIEW":
            _route_to_review(path, reason, logger)

        else:
            debug_file = _dump_transcript(path, verdict, logger, label="unknown")
            logger.error(
                f"UNKNOWN  {path.name}  agent did not emit a usable VERDICT  "
                f"|  transcript: {debug_file}"
            )

    finally:
        _cleanup_staging(staged)


def _dump_transcript(path: Path, verdict: dict, logger: logging.Logger, *, label: str) -> Path:
    debug_dir = config.LOG_DIR / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_file = debug_dir / f"{label}_{path.stem}_{int(asyncio.get_event_loop().time())}.txt"
    debug_file.write_text(verdict.get("raw", ""), encoding="utf-8")
    return debug_file


def _approve_new_folder(
    path: Path, proposed_dir: Path, reason: str, logger: logging.Logger
) -> Path | None:
    """Prompt the user before creating a new destination folder.

    Returns the approved destination Path, or None if the user declined.
    If stdin isn't a TTY (e.g. running as a service), declines automatically
    so the file goes to review/ instead of silently creating a folder.
    """
    rel = proposed_dir.relative_to(config.REPO_ROOT).as_posix()

    if not sys.stdin.isatty():
        logger.warning(
            f"NEW_DIR? {path.name}  proposed: {rel}/  but no TTY — sending to review"
        )
        return None

    print()
    print(f"❓ New folder needed for: {path.name}")
    print(f"   Proposed: {rel}/")
    print(f"   Reason:   {reason}")
    print(f"   [Enter] approve  |  paste a different path to override  |  r = review")
    try:
        response = input("   > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if response.lower() in ("r", "review"):
        return None
    if response == "":
        return proposed_dir

    # User overrode with a different path — normalize and return
    override = response.strip("/").strip("\\").replace("\\", "/")
    return (config.REPO_ROOT / override).resolve()


def _route_to_review(path: Path, reason: str, logger: logging.Logger) -> None:
    try:
        final_path = _safe_move(path, config.REVIEW_DIR, path.name)
        rel = final_path.relative_to(config.REPO_ROOT).as_posix()
        logger.warning(f"REVIEW   {path.name}  ->  {rel}  |  {reason}")
    except Exception as e:
        logger.error(f"ERROR    {path.name}  review move failed: {e}")


class IntakeHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.queue = queue
        self.loop = loop
        self.seen: set[str] = set()

    def on_created(self, event):
        path = Path(event.src_path)
        try:
            path.relative_to(config.REVIEW_DIR)
            return
        except ValueError:
            pass
        try:
            rel = path.relative_to(config.INTAKE_DIR)
        except ValueError:
            return
        if len(rel.parts) != 1:
            return
        key = str(path)
        if key in self.seen:
            return
        self.seen.add(key)
        asyncio.run_coroutine_threadsafe(self.queue.put(path), self.loop)


async def _consumer(queue: asyncio.Queue, dry_run: bool) -> None:
    while True:
        path = await queue.get()
        try:
            await _process_one(path, dry_run=dry_run)
        finally:
            queue.task_done()


async def _scan_existing(queue: asyncio.Queue) -> None:
    if not config.INTAKE_DIR.exists():
        return
    for p in sorted(config.INTAKE_DIR.iterdir()):
        if p.name == "review" or p.name.startswith("."):
            continue
        await queue.put(p)


async def run(dry_run: bool, once: bool) -> None:
    logger = _get_logger()
    mode = "DRY-RUN" if dry_run else "LIVE"
    logger.info(f"Starting intake agent ({mode})")
    logger.info(f"Repo:    {config.REPO_ROOT}")
    logger.info(f"Watch:   {config.INTAKE_DIR}")
    logger.info(f"Staging: {config.TEMP_ROOT}")

    config.TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    await _scan_existing(queue)

    if once:
        consumer = asyncio.create_task(_consumer(queue, dry_run))
        await queue.join()
        consumer.cancel()
        return

    handler = IntakeHandler(queue, loop)
    observer = Observer()
    observer.schedule(handler, str(config.INTAKE_DIR), recursive=False)
    observer.start()
    logger.info("Watcher active. Drop files into 00_intake/ to route them.")

    consumer = asyncio.create_task(_consumer(queue, dry_run))
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        observer.stop()
        observer.join()
        consumer.cancel()
        logger.info("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Intake routing daemon")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect drops but don't invoke the agent")
    parser.add_argument("--once", action="store_true",
                        help="Drain existing intake items and exit")
    args = parser.parse_args()

    if not config.ANTHROPIC_API_KEY:
        print("[intake] ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(dry_run=args.dry_run, once=args.once))


if __name__ == "__main__":
    main()
