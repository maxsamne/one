"""Scheduler: store CRUD + due-detection."""

import time
from unittest.mock import patch

import pytest

from core.scheduler import runner, store


@pytest.fixture(autouse=True)
def _clean_schedules():
    """Each test starts with no schedules — keep tests independent of dev DB state."""
    for s in store.list_all():
        store.delete(s.id)
    yield
    for s in store.list_all():
        store.delete(s.id)


def test_create_get_update_delete_roundtrip():
    s = store.create(cron="*/5 * * * *", prompt="poll", tier="cheap", skills=["general/python.md"])
    assert s.id.startswith("sch_") and s.enabled and s.last_run_at is None

    fetched = store.get(s.id)
    assert fetched is not None and fetched.prompt == "poll" and fetched.skills == ["general/python.md"]

    updated = store.update(s.id, enabled=False, prompt="poll v2")
    assert updated is not None and updated.enabled is False and updated.prompt == "poll v2"

    assert store.delete(s.id) is True
    assert store.get(s.id) is None
    assert store.delete(s.id) is False  # second delete is a no-op


def test_create_rejects_bad_cron():
    with pytest.raises(ValueError):
        store.create(cron="not a cron", prompt="x")


async def test_runner_fires_due_schedule_and_updates_last_run_at():
    """A schedule whose next-fire-after-creation has elapsed must fire once."""
    s = store.create(cron="* * * * *", prompt="hi")
    # Backdate created_at so the next cron match after `created_at` is in the past.
    from core.log import _get_con, _lock
    with _lock:
        _get_con().execute(
            "UPDATE schedules SET created_at = ? WHERE id = ?",
            [time.time() - 600, s.id],
        )
        _get_con().commit()

    fired_with: list[str] = []

    async def cb(sched):
        fired_with.append(sched.id)
        return "task_xyz"

    runner._fire_cb = cb
    await runner._tick_once()

    assert fired_with == [s.id]
    refreshed = store.get(s.id)
    assert refreshed is not None and refreshed.last_run_at is not None


async def test_runner_skips_disabled():
    store.create(cron="* * * * *", prompt="hi", enabled=False)
    fired: list = []

    async def cb(sched):
        fired.append(sched)
        return "x"

    runner._fire_cb = cb
    await runner._tick_once()
    assert fired == []
