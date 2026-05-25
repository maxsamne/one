"""Task-chain inheritance for PR URLs and effective modes."""

import pytest
from fastapi.testclient import TestClient

from core import log as log_mod
from core.gateway import server
from core.gateway.tasks import TaskRecord


@pytest.fixture
def isolated_log_db(tmp_path, monkeypatch):
    with log_mod._lock:
        if log_mod._con is not None:
            log_mod._con.close()
        log_mod._con = None
        monkeypatch.setattr(log_mod, "_DB_PATH", tmp_path / ".agent.db")
    yield
    with log_mod._lock:
        if log_mod._con is not None:
            log_mod._con.close()
        log_mod._con = None


def test_task_chain_inherits_nearest_pr_url_and_mode(isolated_log_db):
    log_mod.tasks_insert("root", "root task", 1.0, tier="cheap")
    log_mod.tasks_update("root", status="done", pr_url="https://github.com/maxsamne/one/pull/70", mode="persistent")
    log_mod.tasks_insert("middle", "middle task", 2.0, parent_task_id="root", tier="cheap")
    log_mod.tasks_insert("child", "child task", 3.0, parent_task_id="middle", tier="cheap")

    assert log_mod.task_inherited_pr_url("child") == "https://github.com/maxsamne/one/pull/70"
    assert log_mod.task_inherited_mode("child") == "persistent"

    log_mod.tasks_update("middle", status="done", mode="conversational")
    assert log_mod.task_inherited_mode("child") == "conversational"


def test_submit_task_inherits_parent_effective_mode(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(server, "_validate_parent", lambda parent_task_id: None)
    monkeypatch.setattr(server, "task_inherited_mode", lambda parent_task_id: "persistent")

    def _fake_spawn_task(**kwargs):
        captured.update(kwargs)
        return TaskRecord(task_id="child", prompt=kwargs["prompt"])

    monkeypatch.setattr(server, "_spawn_task", _fake_spawn_task)

    response = TestClient(server.app).post(
        "/task",
        json={"task": "follow up", "tier": "cheap", "parent_task_id": "parent"},
    )

    assert response.status_code == 202
    assert captured["mode_override"] == "persistent"


def test_submit_task_explicit_mode_overrides_parent_mode(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(server, "_validate_parent", lambda parent_task_id: None)
    monkeypatch.setattr(server, "task_inherited_mode", lambda parent_task_id: "persistent")

    def _fake_spawn_task(**kwargs):
        captured.update(kwargs)
        return TaskRecord(task_id="child", prompt=kwargs["prompt"])

    monkeypatch.setattr(server, "_spawn_task", _fake_spawn_task)

    response = TestClient(server.app).post(
        "/task",
        json={
            "task": "follow up",
            "tier": "cheap",
            "parent_task_id": "parent",
            "mode": "conversational",
        },
    )

    assert response.status_code == 202
    assert captured["mode_override"] == "conversational"
