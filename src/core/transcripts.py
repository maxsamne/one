"""Per-task LLM call transcripts — full payloads for debugging.

For every LLM API call made inside a task, append one JSONL line to
`.agent_transcripts/<task_id>.jsonl` capturing exactly what the model received:
the system prompt (`instructions`), the input payload (user message + tool-loop
history, with image bytes elided), the iteration number, and the usage counters
returned for that call.

Read it like a flight recorder when an agent does something surprising:
    tail -n 1 .agent_transcripts/abc12345.jsonl | python3 -m json.tool

Gated by `AGENT_TRANSCRIPTS=1` env var (off by default — these files get large).
No-op when `task_id` isn't available (e.g. outside a request context).
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_DIR = Path(".agent_transcripts")
_LOCK = threading.Lock()
_ENABLED = os.environ.get("AGENT_TRANSCRIPTS", "0") == "1"


def enabled() -> bool:
    return _ENABLED


def _redact_images(item: Any) -> Any:
    """Recursively replace base64 image data URIs with a short placeholder."""
    if isinstance(item, dict):
        out = {}
        for k, v in item.items():
            if k == "image_url" and isinstance(v, str) and v.startswith("data:image/"):
                head = v.split(",", 1)[0]  # e.g. "data:image/jpeg;base64"
                size = len(v) - len(head) - 1
                out[k] = f"<{head} elided, {size} b64 chars>"
            elif k == "source" and isinstance(v, dict) and v.get("type") == "base64":
                d = dict(v); d["data"] = f"<elided {len(v.get('data', '')) } b64 chars>"
                out[k] = d
            else:
                out[k] = _redact_images(v)
        return out
    if isinstance(item, list):
        return [_redact_images(x) for x in item]
    return item


def _safe(obj: Any) -> Any:
    """Coerce pydantic / OpenAI SDK objects to plain JSON-able dicts."""
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe(x) for x in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return repr(obj)


def dump(
    *,
    model: str,
    iteration: int,
    instructions: str | None,
    input_payload: Any,
    output: Any = None,
    usage: dict[str, int] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record one LLM API call. task_id + agent_id are pulled from ContextVars
    so call sites don't have to thread them through."""
    if not _ENABLED:
        return
    try:
        from core.agents.task_ctx import current_task_id
        from core.agents.agent_ctx import AGENT_ID_CTX
        task_id = current_task_id()
        agent_id = AGENT_ID_CTX.get()
    except Exception:
        task_id = None
        agent_id = None
    if not task_id:
        return
    _DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "task_id": task_id,
        "agent_id": agent_id,
        "model": model,
        "iter": iteration,
        "instructions": instructions,
        "instructions_chars": len(instructions or ""),
        "input": _redact_images(_safe(input_payload)),
        "output": _redact_images(_safe(output)) if output is not None else None,
        "usage": usage or {},
    }
    if extra:
        record.update(extra)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    path = _DIR / f"{task_id}.jsonl"
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
