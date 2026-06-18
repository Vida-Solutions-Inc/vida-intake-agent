"""Build a compact snapshot of the target repo's folder structure.

This snapshot is injected into the system prompt so the agent knows, up front,
which folders actually exist in *this user's* repo — without it having to glob
the whole tree on every file. The agent can still drill in with live tools; the
snapshot is just a fast, accurate prior that makes routing work on any repo with
zero hand-written rules.
"""

from __future__ import annotations

from pathlib import Path

# Folders that are never useful routing targets and only add noise.
_NOISE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", ".idea", ".vscode", "node_modules",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".cache", ".DS_Store", ".terraform",
}


def build_repo_profile(
    repo_root: Path,
    intake_dir: Path,
    *,
    max_depth: int = 4,
    max_entries: int = 400,
    samples_per_leaf: int = 2,
) -> str:
    """Return an indented, depth-limited directory tree as text.

    Leaf folders get up to ``samples_per_leaf`` example filenames so the agent
    can learn each folder's naming convention. The intake folder itself is
    excluded so the agent never proposes routing back into the inbox.
    """
    repo_root = repo_root.resolve()
    try:
        intake_dir = intake_dir.resolve()
    except OSError:
        pass

    lines: list[str] = [f"{repo_root.name}/"]
    count = 0
    truncated = False

    def walk(folder: Path, depth: int) -> None:
        nonlocal count, truncated
        if depth > max_depth or truncated:
            return
        try:
            children = sorted(
                [c for c in folder.iterdir() if c.is_dir()],
                key=lambda p: p.name.lower(),
            )
        except (PermissionError, OSError):
            return
        for child in children:
            if truncated:
                return
            if child.name in _NOISE_DIRS or child.name.startswith("."):
                continue
            if child.resolve() == intake_dir:
                continue
            if count >= max_entries:
                truncated = True
                return
            indent = "  " * depth
            lines.append(f"{indent}{child.name}/")
            count += 1

            subdirs = _has_subdirs(child)
            if not subdirs:
                for sample in _sample_files(child, samples_per_leaf):
                    lines.append(f"{indent}  - {sample}")
            else:
                walk(child, depth + 1)

    walk(repo_root, 1)
    if truncated:
        lines.append(f"  ... (tree truncated at {max_entries} folders)")
    return "\n".join(lines)


def _has_subdirs(folder: Path) -> bool:
    try:
        return any(
            c.is_dir() and c.name not in _NOISE_DIRS and not c.name.startswith(".")
            for c in folder.iterdir()
        )
    except (PermissionError, OSError):
        return False


def _sample_files(folder: Path, limit: int) -> list[str]:
    try:
        files = sorted(
            [c.name for c in folder.iterdir() if c.is_file() and not c.name.startswith(".")],
            key=str.lower,
        )
    except (PermissionError, OSError):
        return []
    return files[:limit]
