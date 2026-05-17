"""In-memory task registry — lifecycle for submitted agent tasks."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal


TaskStatus = Literal["queued", "running", "done", "failed", "cancelled"]


@dataclass
class TaskRecord:
    task_id: str
    prompt: str
    tier: str = "ultra_cheap"
    status: TaskStatus = "queued"
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str | None = None
    error: str | None = None
    pr_url: str | None = None
    # User-attached at submit time. Manager reads via TASK_SKILLS_CTX / TASK_GRADERS_CTX / TASK_IMAGES_CTX.
    skills: list[str] = field(default_factory=list)
    graders: list[str] = field(default_factory=list)
    images: list = field(default_factory=list)  # list[ImageContent], typed Any to avoid import cycle
    # Linkage:
    #   schedule_id    — set when a cron schedule fired this task.
    #   parent_task_id — set when this task is an `@task_id` follow-up; coder seeds from parent's transcript.
    schedule_id: str | None = None
    parent_task_id: str | None = None
    # null = let manager auto-classify; "conversational" / "persistent" = force.
    mode_override: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    def elapsed(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return round(end - self.started_at, 2)

    def to_dict(self) -> dict:
        return {
            "task_id":         self.task_id,
            "prompt":          self.prompt,
            "status":          self.status,
            "submitted_at":    self.submitted_at,
            "started_at":      self.started_at,
            "finished_at":     self.finished_at,
            "elapsed_s":       self.elapsed(),
            "result":          self.result,
            "error":           self.error,
            "pr_url":          self.pr_url,
            "schedule_id":     self.schedule_id,
            "parent_task_id":  self.parent_task_id,
            "tier":            self.tier,
            "skills":          list(self.skills),
            "graders":         list(self.graders),
            "mode_override":   self.mode_override,
        }


_registry: dict[str, TaskRecord] = {}


def register(record: TaskRecord) -> None:
    _registry[record.task_id] = record


def get(task_id: str) -> TaskRecord | None:
    return _registry.get(task_id)


def list_all(status: TaskStatus | None = None) -> list[TaskRecord]:
    records = sorted(_registry.values(), key=lambda r: r.submitted_at, reverse=True)
    if status:
        records = [r for r in records if r.status == status]
    return records
