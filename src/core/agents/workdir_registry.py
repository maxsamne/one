"""Process-local registry of active task workdirs.

Lets the gateway resolve `/images/<task_id>/...` URLs to the worktree where the
running coder wrote the file, instead of guessing against REPO_ROOT (where
generated images don't exist because they live inside each task's worktree).

The manager registers on dispatch and unregisters in `finally`. Reads return
None for unknown task_ids — the gateway falls back to REPO_ROOT for completed
tasks (though their generated/images won't survive worktree cleanup anyway —
this is correct for live preview during the run).
"""

from __future__ import annotations

import threading
from pathlib import Path

_lock = threading.Lock()
_active: dict[str, Path] = {}


def register(task_id: str, workdir: Path) -> None:
    with _lock:
        _active[task_id] = workdir


def unregister(task_id: str) -> None:
    with _lock:
        _active.pop(task_id, None)


def get(task_id: str) -> Path | None:
    with _lock:
        return _active.get(task_id)
