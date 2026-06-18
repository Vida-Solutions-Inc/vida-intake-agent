"""The routing agent: an Anthropic tool-use loop that yields a structured Verdict.

This replaces the old Node-based claude-CLI dependency. It drives the Messages
API directly with the sandboxed tools in tools.py, and ends when the model calls
`submit_verdict`. Pure Python — installs and runs anywhere the `anthropic`
package does (Windows incl. ARM64, macOS, Linux).
"""

from __future__ import annotations

import time
from pathlib import Path

import anthropic

from .config import Config
from .extract import Extracted, extract
from .models import Outcome, Verdict
from .prompts import build_system_prompt
from .tools import TOOL_DEFS, ToolContext, parse_verdict, run_tool

_MAX_TOKENS = 2048
_API_TIMEOUT_S = 120.0
_API_MAX_RETRIES = 4
_API_BACKOFF_S = 4.0
_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


class Router:
    """Reusable router. Build once per config; call decide() per file."""

    def __init__(self, config: Config, api_key: str):
        self.config = config
        self.client = anthropic.Anthropic(
            api_key=api_key, timeout=_API_TIMEOUT_S, max_retries=0
        )
        self._system_prompt: str | None = None

    def system_prompt(self, refresh: bool = False) -> str:
        # Rebuilt lazily; refresh picks up new folders/rules without a restart.
        if self._system_prompt is None or refresh:
            self._system_prompt = build_system_prompt(self.config)
        return self._system_prompt

    def decide(self, staged_path: Path, original_filename: str) -> Verdict:
        ctx = ToolContext(
            repo_root=self.config.repo_path,
            staged_file=staged_path,
            max_file_bytes=self.config.max_file_bytes,
        )
        doc = extract(staged_path, max_bytes=self.config.max_file_bytes)
        messages: list[dict] = [
            {"role": "user", "content": self._initial_content(staged_path, original_filename, doc)}
        ]
        transcript: list[str] = [f"# routing {original_filename}"]

        for _ in range(self.config.max_tool_iterations):
            response = self._create(messages)
            messages.append({"role": "assistant", "content": response.content})

            verdict, tool_results = self._handle_turn(response, ctx, transcript)
            if verdict is not None:
                verdict.raw_transcript = "\n".join(transcript)
                return verdict
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue
            # Model stopped without a verdict and without tools — nudge once.
            messages.append({"role": "user", "content": [{
                "type": "text",
                "text": "You did not call submit_verdict. Call it now with your "
                        "best decision, choosing REVIEW if you remain unsure.",
            }]})

        return Verdict(
            outcome=Outcome.REVIEW,
            reason="Agent exhausted its tool budget without a confident decision.",
            raw_transcript="\n".join(transcript),
        )

    # -------------------------------------------------------------- internals
    def _initial_content(self, staged_path: Path, original_filename: str, doc: Extracted) -> list[dict]:
        intro = (
            "A new file landed in the inbox. Decide where it belongs in the "
            "repository and what it should be named.\n\n"
            f"- Original filename: {original_filename}\n"
            f"- Staged copy (re-read with read_file if needed): {staged_path}\n\n"
            "Explore the repository with list_dir / glob / grep / read_file, then "
            "call submit_verdict. The document content follows."
        )
        blocks: list[dict] = [{"type": "text", "text": intro}]
        if doc.is_image:
            blocks.append({"type": "text", "text": f"[image: {original_filename}]"})
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": doc.media_type, "data": doc.data_b64},
            })
        elif doc.kind == "text":
            blocks.append({"type": "text", "text": f"--- document content ---\n{doc.text}"})
        else:
            blocks.append({"type": "text", "text": f"[document note] {doc.note}"})
        return blocks

    def _handle_turn(self, response, ctx: ToolContext, transcript: list[str]):
        """Process one assistant turn. Returns (verdict_or_None, tool_result_blocks)."""
        tool_results: list[dict] = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                transcript.append(f"[think] {block.text.strip()}")
            elif block.type == "tool_use":
                if block.name == "submit_verdict":
                    transcript.append(f"[verdict] {block.input}")
                    return parse_verdict(block.input), []
                transcript.append(f"[tool] {block.name}({block.input})")
                content = run_tool(block.name, block.input, ctx)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })
        return None, tool_results

    def _create(self, messages: list[dict]):
        last_exc: Exception | None = None
        for attempt in range(1, _API_MAX_RETRIES + 1):
            try:
                return self.client.messages.create(
                    model=self.config.model,
                    max_tokens=_MAX_TOKENS,
                    system=self.system_prompt(),
                    tools=TOOL_DEFS,
                    messages=messages,
                )
            except _RETRYABLE as e:
                last_exc = e
                if attempt < _API_MAX_RETRIES:
                    time.sleep(_API_BACKOFF_S * attempt)
                    continue
                raise
            except anthropic.APIStatusError as e:
                # 529 overloaded is retryable; other 4xx/5xx are not.
                if e.status_code in (429, 500, 502, 503, 529) and attempt < _API_MAX_RETRIES:
                    last_exc = e
                    time.sleep(_API_BACKOFF_S * attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("unreachable")
