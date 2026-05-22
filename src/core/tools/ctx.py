"""Shared session context vars for tool enforcement."""

import time
from contextvars import ContextVar
from pathlib import Path

from core.log import Category
from core.log import log as _log

REPO_ROOT = Path(__file__).parents[3]

# Resolved file paths surfaced in this session (via read_file or grep_file).
# edit_file checks this before allowing edits.
READ_CTX: ContextVar[set[str]] = ContextVar("READ_CTX")

# Append-only log of every tool call: {tool, args, result, ts}.
# Used for ordering enforcement (e.g. git_add before git_commit).
TOOL_LOG: ContextVar[list[dict]] = ContextVar("TOOL_LOG")

# Working directory for fs + git tool calls. Defaults to the repo root; parallel
# coders override it to point at their own git worktree.
WORKDIR: ContextVar[Path] = ContextVar("WORKDIR", default=REPO_ROOT)

# Provider-specific payloads loaded dynamically by tools during a provider tool
# loop. Provider clients pop these after tool execution and attach them once to
# the next model request.
PENDING_MULTIMODAL: ContextVar[list] = ContextVar("PENDING_MULTIMODAL", default=[])


def queue_multimodal(items: list) -> None:
    if not items:
        return
    PENDING_MULTIMODAL.set([*PENDING_MULTIMODAL.get([]), *items])


def pop_pending_multimodal() -> list:
    items = PENDING_MULTIMODAL.get([])
    if items:
        PENDING_MULTIMODAL.set([])
    return items


def log_call(tool: str, args: dict, result: str) -> None:
    entry = TOOL_LOG.get(None)
    if entry is not None:
        entry.append({"tool": tool, "args": args, "result": result, "ts": time.time()})
    ok = not result.startswith(("FATAL", "RETRYABLE", "Error"))
    # Rename keys that collide with log()'s positional params (category, message)
    _RESERVED = {"category", "message"}
    scalar_args = {
        (f"arg_{k}" if k in _RESERVED else k): v
        for k, v in args.items()
        if isinstance(v, (str, int, float, bool))
    }
    result_preview = result[:120].replace("\n", " ") if result else ""
    _log(Category.TOOL, tool, ok=ok, result=result_preview, **scalar_args)


def was_called(tool: str) -> bool:
    """Check if a tool was called earlier in this session."""
    log = TOOL_LOG.get(None)
    if log is None:
        return True  # no enforcement context — allow
    return any(e["tool"] == tool for e in log)
