import base64
import subprocess

from core.agents.coder import _dedupe_tools
from core.ai_client.models import Tool
from core.tools.ctx import PENDING_MULTIMODAL, WORKDIR
from core.tools.visual_refs import load_website_image_refs


def _run(cmd: list[str], cwd) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), stderr=subprocess.STDOUT).decode().strip()


def _tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )


async def _noop() -> str:
    return "ok"


def test_dedupe_tools_removes_duplicate_names():
    first = Tool("todo_write", "first", {"type": "object"}, _noop)
    second = Tool("todo_write", "second", {"type": "object"}, _noop)
    other = Tool("read_file", "read", {"type": "object"}, _noop)

    deduped = _dedupe_tools([first, other, second])

    assert [tool.name for tool in deduped] == ["todo_write", "read_file"]
    assert deduped[0].description == "first"


async def test_load_website_image_refs_queues_docs_images(tmp_path):
    docs = tmp_path / "docs"
    images = docs / "images"
    images.mkdir(parents=True)
    (images / "silicon.png").write_bytes(_tiny_png())
    (docs / "silicon-sociology.html").write_text(
        '<html><body><img src="/one/images/silicon.png" alt="Silicon Sociology"></body></html>',
        encoding="utf-8",
    )

    workdir_tok = WORKDIR.set(tmp_path)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(max_images=2)
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "Loaded 1 website image reference" in result
    assert "docs/images/silicon.png" in result
    assert len(queued) == 1
    assert queued[0].mime == "image/jpeg"
    assert queued[0].data.startswith(b"\xff\xd8")


async def test_load_website_image_refs_can_read_prior_task_branch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t.t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)

    _run(["git", "checkout", "-q", "-b", "task/abc123"], repo)
    docs = repo / "docs"
    (docs / "images").mkdir(parents=True)
    (docs / "images" / "hero.png").write_bytes(_tiny_png())
    (docs / "essay.html").write_text('<img src="/one/images/hero.png">', encoding="utf-8")
    _run(["git", "add", "docs/essay.html", "docs/images/hero.png"], repo)
    _run(["git", "commit", "-q", "-m", "add article image"], repo)
    _run(["git", "checkout", "-q", "main"], repo)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.setattr("core.tools.visual_refs.REPO_ROOT", repo)
    workdir_tok = WORKDIR.set(workdir)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(max_images=1, from_task_id="abc123")
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "task/abc123:docs/images/hero.png" in result
    assert len(queued) == 1
    assert queued[0].mime == "image/jpeg"


async def test_load_website_image_refs_query_prefers_matching_page(tmp_path):
    docs = tmp_path / "docs"
    images = docs / "images"
    images.mkdir(parents=True)
    (images / "backtesting.png").write_bytes(_tiny_png())
    (images / "silicon.png").write_bytes(_tiny_png())
    (docs / "backtesting-the-future.html").write_text(
        '<html><body><h1>The Historical Sandbox</h1><img src="/one/images/backtesting.png"></body></html>',
        encoding="utf-8",
    )
    (docs / "silicon-sociology.html").write_text(
        '<html><body><h1>Silicon Sociology</h1><img src="/one/images/silicon.png" alt="Silicon Sociology cover"></body></html>',
        encoding="utf-8",
    )

    workdir_tok = WORKDIR.set(tmp_path)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(query="Silicon Sociology cover image style", max_images=1)
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "docs/images/silicon.png" in result
    assert "docs/images/backtesting.png" not in result
    assert len(queued) == 1


async def test_load_website_image_refs_query_does_not_load_unrelated_fallback(tmp_path):
    docs = tmp_path / "docs"
    images = docs / "images"
    images.mkdir(parents=True)
    (images / "backtesting.png").write_bytes(_tiny_png())
    (docs / "backtesting-the-future.html").write_text(
        '<html><body><h1>The Historical Sandbox</h1><img src="/one/images/backtesting.png"></body></html>',
        encoding="utf-8",
    )

    workdir_tok = WORKDIR.set(tmp_path)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(query="Silicon Sociology", max_images=1)
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "No matching website image references found" in result
    assert queued == []


async def test_load_website_image_refs_paths_load_exact_image(tmp_path):
    images = tmp_path / "docs" / "images"
    images.mkdir(parents=True)
    (images / "exact.png").write_bytes(_tiny_png())

    workdir_tok = WORKDIR.set(tmp_path)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(paths=["docs/images/exact.png"], max_images=1)
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "docs/images/exact.png" in result
    assert "explicit path" in result
    assert len(queued) == 1


async def test_load_website_image_refs_query_can_find_named_docs_image_without_html_ref(tmp_path):
    images = tmp_path / "docs" / "images"
    images.mkdir(parents=True)
    (images / "silicon-sociology-cover.png").write_bytes(_tiny_png())
    (tmp_path / "docs" / "index.html").write_text("<html><body>No image refs here.</body></html>", encoding="utf-8")

    workdir_tok = WORKDIR.set(tmp_path)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(query="Silicon Sociology cover image style", max_images=1)
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "docs/images/silicon-sociology-cover.png" in result
    assert len(queued) == 1


async def test_load_website_image_refs_query_can_find_main_image_from_old_followup_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t.t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)

    _run(["git", "checkout", "-q", "-b", "task/old"], repo)
    old_images = repo / "docs" / "images"
    old_images.mkdir(parents=True)
    (old_images / "historical-sandbox-card.png").write_bytes(_tiny_png())
    (repo / "docs" / "historical-sandbox.html").write_text(
        '<img src="/one/images/historical-sandbox-card.png" alt="warm editorial card">',
        encoding="utf-8",
    )
    _run(["git", "add", "docs"], repo)
    _run(["git", "commit", "-q", "-m", "add old article image"], repo)

    _run(["git", "checkout", "-q", "main"], repo)
    main_images = repo / "docs" / "images"
    main_images.mkdir(parents=True)
    (main_images / "silicon-sociology-cover.png").write_bytes(_tiny_png())
    (repo / "docs" / "index.html").write_text(
        '<h1>Silicon Sociology</h1><img src="/one/images/silicon-sociology-cover.png" alt="Silicon Sociology cover">',
        encoding="utf-8",
    )
    _run(["git", "add", "docs"], repo)
    _run(["git", "commit", "-q", "-m", "add canonical silicon image"], repo)

    workdir = tmp_path / "old-worktree"
    _run(["git", "worktree", "add", "-q", str(workdir), "task/old"], repo)

    monkeypatch.setattr("core.tools.visual_refs.REPO_ROOT", repo)
    workdir_tok = WORKDIR.set(workdir)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(
            query="Silicon Sociology writing card style editorial warm parchment monochrome",
            max_images=1,
        )
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "main:docs/images/silicon-sociology-cover.png" in result
    assert "historical-sandbox-card" not in result
    assert len(queued) == 1

    workdir_tok = WORKDIR.set(workdir)
    pending_tok = PENDING_MULTIMODAL.set([])
    try:
        result = await load_website_image_refs(
            paths=["/one/images/silicon-sociology-cover.png"],
            max_images=1,
        )
        queued = PENDING_MULTIMODAL.get()
    finally:
        PENDING_MULTIMODAL.reset(pending_tok)
        WORKDIR.reset(workdir_tok)

    assert "main:docs/images/silicon-sociology-cover.png" in result
    assert len(queued) == 1
