"""Generated images live in the running coder's worktree, and the gateway
serves them from there via the workdir registry."""

import pytest
from fastapi.testclient import TestClient

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


async def test_resolve_parent_base_returns_none_for_unknown():
    from core.agents.manager import _resolve_parent_base
    assert await _resolve_parent_base(None) is None
    assert await _resolve_parent_base("no_such_task_id_exists_xyz") is None
