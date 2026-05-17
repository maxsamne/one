"""TodoWrite tool — model-driven task tracking that survives context compaction.

The model calls todo_write when it discovers 3+ distinct sub-tasks. Status flows:
pending → in_progress → completed. The coder loop checks all_complete() as a done signal.
Todos are scoped per coder via TODO_KEY.
"""

import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from core.ai_client.models import Tool

_TODO_DIR = Path(__file__).parents[3]
TODO_KEY: ContextVar[str] = ContextVar("todo_key", default="default")


class TodoItem(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed"]


def _path() -> Path:
    return _TODO_DIR / f".coder_todos.{TODO_KEY.get()}.json"


def _read() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


async def todo_write(todos: list[dict[str, Any]]) -> str:
    try:
        items = [TodoItem.model_validate(t) for t in todos]
    except ValidationError as e:
        return f"RETRYABLE: invalid todo data — {e.error_count()} error(s): {e.errors(include_url=False)}"
    _path().write_text(
        json.dumps([i.model_dump() for i in items], indent=2), encoding="utf-8"
    )
    by_status = {"pending": 0, "in_progress": 0, "completed": 0}
    for item in items:
        by_status[item.status] += 1
    return (
        f"Todos saved ({by_status['completed']} completed, "
        f"{by_status['in_progress']} in_progress, {by_status['pending']} pending)"
    )


def all_complete() -> bool:
    """True if todo list exists and every item is completed."""
    todos = _read()
    return bool(todos) and all(t.get("status") == "completed" for t in todos)


def clear() -> None:
    p = _path()
    if p.exists():
        p.unlink()


def clear_all_stale() -> None:
    """Remove all .coder_todos.*.json files — called at gateway startup to wipe
    leftovers from previously interrupted or cancelled tasks."""
    for p in _TODO_DIR.glob(".coder_todos.*.json"):
        p.unlink(missing_ok=True)


TODO_TOOL = Tool(
    name="todo_write",
    description=(
        "Create or update the task list for this session. Use when the task has 3 or more "
        "distinct steps to track. Pass the full list every call — update statuses as you go. "
        "Status must be exactly one of: pending, in_progress, completed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":      {"type": "string"},
                        "content": {"type": "string"},
                        "status":  {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["id", "content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
    fn=todo_write,
    is_read_only=False,
    is_concurrency_safe=False,
)
