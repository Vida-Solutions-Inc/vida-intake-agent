"""Python implementations of the tools Claude uses to inspect the repo.

Every path the model passes is sandboxed: it must resolve inside the repo root
or be the staged copy of the file under review. This is a hard security boundary
- the agent cannot read arbitrary disk, only the repository it routes into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .extract import extract
from .models import Outcome, Verdict

_MAX_GLOB_RESULTS = 200
_MAX_GREP_MATCHES = 80
_MAX_GREP_FILES = 400
_MAX_LISTING = 300


class SandboxError(PermissionError):
    """Raised when a tool path escapes the allowed roots."""


@dataclass
class ToolContext:
    repo_root: Path
    staged_file: Path
    max_file_bytes: int = 4_000_000

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self.staged_file = self.staged_file.resolve()
        self.staging_dir = self.staged_file.parent

    def resolve(self, raw: str) -> Path:
        candidate = Path(raw)
        target = candidate.resolve() if candidate.is_absolute() else (self.repo_root / candidate).resolve()
        if _within(target, self.repo_root) or target == self.staged_file or _within(target, self.staging_dir):
            return target
        raise SandboxError(
            f"Path {raw!r} is outside the repository sandbox and cannot be accessed."
        )


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rel(ctx: ToolContext, path: Path) -> str:
    try:
        return path.relative_to(ctx.repo_root).as_posix() or "."
    except ValueError:
        return path.name


# --------------------------------------------------------------- tool schemas
TOOL_DEFS: list[dict] = [
    {
        "name": "list_dir",
        "description": "List the immediate contents (subfolders and files) of a "
        "folder, relative to the repository root. Use '.' for the root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative folder path, e.g. 'admin/Finance'."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob",
        "description": "Find files/folders matching a glob pattern, relative to the "
        "repo root. Supports ** for recursion, e.g. 'admin/**/Vendors' or "
        "'clients/*/'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern relative to repo root."}
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents for a regular expression. Optionally "
        "restrict to a repo-relative subfolder. Returns matching lines with their "
        "file and line number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression."},
                "path": {"type": "string", "description": "Optional repo-relative folder to search within."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file's content. Pass the staged file path given to "
        "you to read the document under review, or a repo-relative path to read an "
        "existing file. Returns extracted text, or the image itself for pictures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Staged absolute path or repo-relative path."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "submit_verdict",
        "description": "Submit your final routing decision. Call exactly once when "
        "decided. This ends your turn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["MOVE", "REVIEW", "SKIP"],
                    "description": "MOVE to place it, REVIEW if unsure, SKIP if not a document to file.",
                },
                "dest_folder": {
                    "type": "string",
                    "description": "Repo-relative destination folder (existing or new). "
                    "Empty for REVIEW/SKIP. Always end folders with '/'.",
                },
                "new_filename": {
                    "type": "string",
                    "description": "New filename WITH extension to match the folder's "
                    "naming convention, or the literal 'keep' to retain the original.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Calibrated confidence in [0,1] that this placement is correct.",
                },
                "reason": {
                    "type": "string",
                    "description": "One concise sentence explaining the decision.",
                },
            },
            "required": ["outcome", "confidence", "reason"],
        },
    },
]


# ------------------------------------------------------------------ dispatch
def run_tool(name: str, tool_input: dict, ctx: ToolContext) -> list[dict]:
    """Execute a non-terminal tool, returning anthropic tool_result content blocks."""
    try:
        if name == "list_dir":
            return _text_block(_list_dir(ctx, tool_input.get("path", ".")))
        if name == "glob":
            return _text_block(_glob(ctx, tool_input.get("pattern", "*")))
        if name == "grep":
            return _text_block(_grep(ctx, tool_input.get("pattern", ""), tool_input.get("path")))
        if name == "read_file":
            return _read_file(ctx, tool_input.get("path", ""))
        return _text_block(f"Unknown tool: {name}")
    except SandboxError as e:
        return _text_block(f"Denied: {e}")
    except Exception as e:  # surface errors to the model, don't crash the loop
        return _text_block(f"Error running {name}: {type(e).__name__}: {e}")


def parse_verdict(tool_input: dict) -> Verdict:
    try:
        outcome = Outcome(str(tool_input.get("outcome", "REVIEW")).upper())
    except ValueError:
        outcome = Outcome.REVIEW
    return Verdict(
        outcome=outcome,
        dest_folder=str(tool_input.get("dest_folder", "") or "").strip(),
        new_filename=str(tool_input.get("new_filename", "keep") or "keep").strip(),
        confidence=_clamp(tool_input.get("confidence", 0.0)),
        reason=str(tool_input.get("reason", "")).strip(),
    )


# ------------------------------------------------------------------ tool bodies
def _list_dir(ctx: ToolContext, raw: str) -> str:
    folder = ctx.resolve(raw)
    if not folder.exists():
        return f"(does not exist: {raw})"
    if not folder.is_dir():
        return f"(not a folder: {raw})"
    entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines: list[str] = []
    for e in entries[:_MAX_LISTING]:
        lines.append(f"{e.name}/" if e.is_dir() else e.name)
    if len(entries) > _MAX_LISTING:
        lines.append(f"... ({len(entries) - _MAX_LISTING} more)")
    return "\n".join(lines) if lines else "(empty folder)"


def _glob(ctx: ToolContext, pattern: str, ) -> str:
    matches = []
    try:
        for p in ctx.repo_root.glob(pattern):
            if _within(p, ctx.repo_root):
                matches.append(_rel(ctx, p) + ("/" if p.is_dir() else ""))
            if len(matches) >= _MAX_GLOB_RESULTS:
                break
    except (ValueError, OSError) as e:
        return f"(invalid glob: {e})"
    matches.sort()
    if not matches:
        return f"(no matches for {pattern!r})"
    out = "\n".join(matches)
    if len(matches) >= _MAX_GLOB_RESULTS:
        out += f"\n... (capped at {_MAX_GLOB_RESULTS})"
    return out


def _grep(ctx: ToolContext, pattern: str, path: str | None) -> str:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"(invalid regex: {e})"
    root = ctx.resolve(path) if path else ctx.repo_root
    if not root.exists():
        return f"(does not exist: {path})"
    matches: list[str] = []
    scanned = 0
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        scanned += 1
        if scanned > _MAX_GREP_FILES:
            break
        if f.stat().st_size > 1_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append(f"{_rel(ctx, f)}:{i}: {line.strip()[:200]}")
                if len(matches) >= _MAX_GREP_MATCHES:
                    return "\n".join(matches) + f"\n... (capped at {_MAX_GREP_MATCHES})"
    return "\n".join(matches) if matches else f"(no matches for {pattern!r})"


def _read_file(ctx: ToolContext, raw: str) -> list[dict]:
    target = ctx.resolve(raw)
    if not target.exists() or not target.is_file():
        return _text_block(f"(not a readable file: {raw})")
    result = extract(target, max_bytes=ctx.max_file_bytes)
    if result.is_image:
        return [
            {"type": "text", "text": f"Image file: {target.name}"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.media_type,
                    "data": result.data_b64,
                },
            },
        ]
    if result.kind == "text":
        return _text_block(f"--- {target.name} ---\n{result.text}")
    return _text_block(f"[{target.name}] {result.note}")


def _text_block(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def _clamp(value, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.0
