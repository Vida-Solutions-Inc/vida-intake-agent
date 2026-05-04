"""Agent SDK wrapper — decides where a single intake item should go.

The agent is read-only: Read, Glob, Grep, Skill. It never moves files.
The watcher takes the agent's verdict and performs the actual move,
ensuring atomicity and skipping a class of crashes from OneDrive sync.
"""

import asyncio
import re
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    query,
)

import config


# Agent emits: VERDICT: <MOVE|REVIEW> | <repo-relative dest folder> | <new filename or "keep"> | <reason>
VERDICT_RE = re.compile(
    r"\**VERDICT\**\s*:\s*\**\s*(\S+)\s*\**\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.*?)$",
    re.MULTILINE,
)

# Retry on Windows native crashes from the underlying CLI (e.g. 0xC0000005).
_RETRYABLE_ERROR_FRAGMENTS = (
    "3221225477",
    "exit code: -1073741819",
    "Command failed with exit code",
)
_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_S = 3.0
_PER_ATTEMPT_TIMEOUT_S = 180.0


def _build_options() -> ClaudeAgentOptions:
    system_prompt = config.SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    return ClaudeAgentOptions(
        model=config.MODEL,
        system_prompt=system_prompt,
        cwd=str(config.REPO_ROOT),
        max_turns=config.MAX_TURNS,
        # Read-only allowlist. Watcher does the actual move; agent never writes.
        allowed_tools=["Read", "Glob", "Grep", "Skill"],
        permission_mode="default",
    )


async def _run_once(user_msg: str) -> str:
    options = _build_options()
    chunks: list[str] = []
    async for message in query(prompt=user_msg, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    chunks.append(f"[TOOL_USE {block.name}] {block.input}")
    return "\n".join(chunks)


async def decide(staged_path: Path, original_filename: str) -> dict:
    """Ask the agent where the file should go. Read-only.

    Returns:
        {
          "outcome": "MOVE" | "REVIEW" | "UNKNOWN",
          "dest_folder": "admin/Finance/02_Expenses/Vendors/Apify/" or "",
          "new_filename": "<filename>" or "keep" — what to rename to,
          "reason": "...",
          "raw": full transcript including tool-use blocks,
        }
    """
    staged_rel = str(staged_path)  # absolute temp path; agent reads it directly
    user_msg = (
        f"Decide where this intake file should be routed.\n\n"
        f"- Staged copy to read: `{staged_rel}`\n"
        f"- Original filename (use for naming decisions): `{original_filename}`\n\n"
        f"Follow the rules in your system prompt. The watcher will perform the "
        f"actual move based on your VERDICT line — do not try to move the file "
        f"yourself."
    )

    transcript = ""
    last_error: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        print(f"[agent] {original_filename}: attempt {attempt}/{_MAX_ATTEMPTS}", flush=True)
        try:
            transcript = await asyncio.wait_for(
                _run_once(user_msg), timeout=_PER_ATTEMPT_TIMEOUT_S
            )
            break
        except asyncio.TimeoutError:
            last_error = TimeoutError(
                f"agent loop hung past {_PER_ATTEMPT_TIMEOUT_S}s"
            )
            print(f"[agent] {original_filename}: timeout, retrying", flush=True)
            await asyncio.sleep(_RETRY_BACKOFF_S)
            continue
        except BaseException as e:  # native crashes can raise BaseException
            last_error = e
            msg = str(e)
            retryable = any(frag in msg for frag in _RETRYABLE_ERROR_FRAGMENTS)
            if retryable and attempt < _MAX_ATTEMPTS:
                print(f"[agent] {original_filename}: native crash "
                      f"({type(e).__name__}), retrying in {_RETRY_BACKOFF_S}s",
                      flush=True)
                await asyncio.sleep(_RETRY_BACKOFF_S)
                continue
            raise
    else:
        if last_error is not None:
            raise last_error

    match = VERDICT_RE.search(transcript)
    if not match:
        return {
            "outcome": "UNKNOWN",
            "dest_folder": "",
            "new_filename": "keep",
            "reason": "Agent did not emit a VERDICT line",
            "raw": transcript,
        }
    outcome, dest_folder, new_filename, reason = match.groups()
    return {
        "outcome": outcome.upper(),
        "dest_folder": dest_folder.strip().strip("`").strip(),
        "new_filename": new_filename.strip().strip("`").strip(),
        "reason": reason.strip(),
        "raw": transcript,
    }
