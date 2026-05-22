"""Central debug tracing — flip DEBUG=true in env to enable.

Stdout: truncated one-liners for at-a-glance monitoring.
File:   full untruncated JSONL at .debug_logs/<pid>.jsonl for post-mortem inspection.
"""

import json
import os
import time
from pathlib import Path

ENABLED = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

_LOG_DIR = Path(__file__).parents[2] / ".debug_logs"
_log_file = None


def _get_log_file():
    global _log_file
    if _log_file is None and ENABLED:
        _LOG_DIR.mkdir(exist_ok=True)
        path = _LOG_DIR / f"{os.getpid()}.jsonl"
        _log_file = open(path, "a", buffering=1)  # line-buffered
    return _log_file


def trace(tag: str, **fields: object) -> None:
    if not ENABLED:
        return
    try:
        from core.agents.agent_ctx import AGENT_ID_CTX
        from core.agents.task_ctx import current_task_id
        task_id = current_task_id()
        agent_id = AGENT_ID_CTX.get()
    except Exception:
        task_id = None
        agent_id = None
    if task_id and "task_id" not in fields:
        fields["task_id"] = task_id
    if agent_id and "agent" not in fields:
        fields["agent"] = agent_id

    # Stdout: truncated for readability
    parts = " ".join(f"{k}={_fmt(v, 300)}" for k, v in fields.items())
    print(f"  [DEBUG:{tag}] {parts}", flush=True)

    # File: full untruncated JSON
    f = _get_log_file()
    if f:
        entry = {"ts": time.time(), "tag": tag, **{k: str(v) for k, v in fields.items()}}
        f.write(json.dumps(entry) + "\n")


def _fmt(v: object, limit: int) -> str:
    s = str(v).strip().replace("\n", " ⏎ ")
    return s[:limit] + "…" if len(s) > limit else s
