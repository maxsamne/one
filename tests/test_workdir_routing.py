"""Generated images live in the running coder's worktree, and the gateway
serves them from there via the workdir registry."""

import pytest
import subprocess
from fastapi.testclient import TestClient
from pathlib import Path

from core.agents import workdir_registry
from core.agents.task_ctx import TASK_CTX, TIER_CTX, TaskContext
from core.ai_client.models import ImageContent
from core.gateway.server import app
from core.tools.ctx import WORKDIR
from core.tools.image_gen import generate_image


class _FakeImageClient:
    provider = "fake"
    model_name = "fake-1"

    async def generate(self, prompt: str, size: str) -> ImageContent:
        return ImageContent(mime="image/png", data=b"\x89PNG\r\n\x1a\nfake-bytes")


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), stderr=subprocess.STDOUT).decode().strip()


async def test_generate_image_writes_into_workdir(tmp_path, monkeypatch):
    monkeypatch.setattr("core.tools.image_gen.image_client_for_tier", lambda tier: _FakeImageClient())
    tier_tok = TIER_CTX.set("cheap")
    task_tok = TASK_CTX.set(TaskContext(task_id="wdr_test", prompt="x"))
    wd_tok = WORKDIR.set(tmp_path)
    try:
        url = await generate_image("a tiny dot")
    finally:
        WORKDIR.reset(wd_tok)
        TASK_CTX.reset(task_tok)
        TIER_CTX.reset(tier_tok)

    assert url.startswith("/images/wdr_test/")
    written = tmp_path / "generated" / "images" / "wdr_test" / url.rsplit("/", 1)[-1]
    assert written.exists() and written.read_bytes().startswith(b"\x89PNG")


def test_gateway_image_route_serves_from_registry(tmp_path):
    img_dir = tmp_path / "generated" / "images" / "gw_test"
    img_dir.mkdir(parents=True)
    (img_dir / "1-hero.png").write_bytes(b"\x89PNG\r\n\x1a\nhello")

    workdir_registry.register("gw_test", tmp_path)
    try:
        client = TestClient(app)
        r = client.get("/images/gw_test/1-hero.png")
        assert r.status_code == 200 and r.content.startswith(b"\x89PNG")

        r = client.get("/images/gw_test/missing.png")
        assert r.status_code == 404
    finally:
        workdir_registry.unregister("gw_test")


def test_workdir_registry_roundtrip(tmp_path):
    assert workdir_registry.get("nope") is None
    workdir_registry.register("t1", tmp_path)
    assert workdir_registry.get("t1") == tmp_path
    workdir_registry.unregister("t1")
    assert workdir_registry.get("t1") is None


def test_persist_generated_images_copies_to_repo_root(tmp_path, monkeypatch):
    from core.agents import manager

    workdir = tmp_path / "work"
    src = workdir / "generated" / "images" / "img_task"
    src.mkdir(parents=True)
    (src / "1-hero.png").write_bytes(b"\x89PNG\r\n\x1a\nstable")

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(manager, "REPO_ROOT", repo)

    manager._persist_generated_images("img_task", workdir)

    copied = repo / "generated" / "images" / "img_task" / "1-hero.png"
    assert copied.read_bytes().endswith(b"stable")


def test_persistent_manager_hides_lifecycle_git_tools():
    from core.agents import manager

    names = {tool.name for tool in manager._PERSISTENT_TOOLS}
    assert {"git_status", "git_diff", "git_add", "git_commit", "git_log"} <= names
    assert "git_create_branch" not in names
    assert "git_checkout" not in names
    assert "git_push" not in names
    assert "git_create_pr" not in names


async def test_persistent_run_serves_generated_image_after_cleanup(tmp_path, monkeypatch):
    from core.agents import manager, worktree
    from core.ai_client.models import ThinkingLevel

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t.t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / ".gitignore").write_text("generated/images/\n.worktrees/\n", encoding="utf-8")
    _run(["git", "add", ".gitignore"], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)

    monkeypatch.setattr(manager, "REPO_ROOT", repo)
    monkeypatch.setattr(worktree, "REPO_ROOT", repo)
    monkeypatch.setattr(worktree, "WORKTREE_DIR", repo / ".worktrees")
    monkeypatch.setattr(worktree, "AUTO_OPEN_PR", False)
    monkeypatch.setattr("core.gateway.server._IMAGES_DIR", repo / "generated" / "images")
    monkeypatch.setattr("core.tools.image_gen.image_client_for_tier", lambda tier: _FakeImageClient())

    captured: dict[str, str] = {}

    class _ImageGeneratingClient:
        model_name = "fake-model"
        provider = "fake"

        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=(), images=None, response_model=None):
            tool = next(t for t in extra_tools if t.name == "generate_image")
            url = await tool.fn("stable local preview image")
            captured["url"] = url
            return f'```html\n<html><body><img src="{url}" alt="hero"></body></html>\n```'

    async def fake_route(task: str, pre_loaded_paths: list[str]):
        return _ImageGeneratingClient(), ThinkingLevel.MINIMAL, "fakeprov"

    monkeypatch.setattr(manager, "_route", fake_route)

    task_tok = TASK_CTX.set(TaskContext(task_id="img_e2e", prompt="make persistent image artifact"))
    tier_tok = TIER_CTX.set("cheap")
    try:
        plan = manager._Plan(
            pre_loaded_paths=[],
            skill_bodies="",
            skill_index="",
            images=[],
            n_skill_images=0,
            n_user_images=0,
            date_ctx="",
        )
        await manager._dispatch(
            "make persistent image artifact",
            manager.TaskMode.PERSISTENT,
            plan,
            extra_tools=None,
        )
    finally:
        TIER_CTX.reset(tier_tok)
        TASK_CTX.reset(task_tok)

    assert captured["url"].startswith("/images/img_e2e/")
    assert not (repo / ".worktrees" / "img_e2e-fakeprov").exists()

    client = TestClient(app)
    r = client.get(captured["url"])
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


async def test_resolve_parent_base_returns_none_for_unknown():
    from core.agents.manager import _resolve_parent_base
    assert await _resolve_parent_base(None) is None
    assert await _resolve_parent_base("no_such_task_id_exists_xyz") is None
