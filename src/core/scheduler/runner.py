"""Background scheduler — ticks every TICK_S, fires due schedules via callback."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from core.log import Category
from core.log import log as _log
from core.scheduler import store

TICK_S = 30.0  # how often the loop wakes up to check for due schedules

# Cron expressions are interpreted in this timezone — so "0 9 * * 1-5" means 9am
# wall-clock in Stockholm, regardless of whether the server itself runs in UTC.
# DST transitions are handled by zoneinfo.
SCHEDULE_TZ = ZoneInfo("Europe/Stockholm")

# Callback shape: takes a Schedule, kicks off a task. Set via start().
FireCallback = Callable[[store.Schedule], Awaitable[Optional[str]]]

_task: asyncio.Task | None = None
_fire_cb: FireCallback | None = None


def next_fire_at(sched: store.Schedule, now: float | None = None) -> float:
    """When this schedule should next fire — the first cron match strictly after
    `last_run_at` (or `created_at` if it has never fired). May be in the past.
    The runner either fires one catch-up run or skips the missed window depending
    on the schedule's `catch_up` setting, then writes back `last_run_at = now`.

    Cron is interpreted in `SCHEDULE_TZ` (Europe/Stockholm) so the user types
    schedules in their wall-clock time. zoneinfo handles DST transparently."""
    del now  # unused — caller compares against time.time()
    base_ts = sched.last_run_at or sched.created_at
    base = datetime.fromtimestamp(base_ts, tz=SCHEDULE_TZ)
    nxt = croniter(sched.cron, base).get_next(datetime)
    return nxt.timestamp()


async def _tick_once() -> None:
    now = time.time()
    for sched in store.list_all():
        if not sched.enabled:
            continue
        try:
            due_at = next_fire_at(sched)
        except Exception as e:
            _log(Category.GATEWAY, "schedule next-fire failed", id=sched.id, error=str(e)[:200])
            continue
        if due_at > now:
            continue
        if not sched.catch_up and due_at < now - TICK_S:
            store.update(sched.id, last_run_at=now)
            _log(Category.GATEWAY, "schedule missed fire skipped", id=sched.id, due_at=due_at)
            continue
        # Mark fired BEFORE invoking, so a slow callback can't double-fire next tick.
        store.update(sched.id, last_run_at=now)
        try:
            assert _fire_cb is not None
            task_id = await _fire_cb(sched)
            _log(Category.GATEWAY, "schedule fired", id=sched.id, task_id=task_id)
        except Exception as e:
            _log(Category.GATEWAY, "schedule fire failed", id=sched.id, error=str(e)[:200])


async def _loop() -> None:
    while True:
        try:
            await _tick_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(Category.GATEWAY, "scheduler tick errored", error=str(e)[:200])
        await asyncio.sleep(TICK_S)


def start(fire_cb: FireCallback) -> None:
    global _task, _fire_cb
    if _task is not None and not _task.done():
        return
    _fire_cb = fire_cb
    _task = asyncio.create_task(_loop(), name="scheduler-loop")
    _log(Category.GATEWAY, "scheduler started", tick_s=TICK_S)


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
    _log(Category.GATEWAY, "scheduler stopped")
