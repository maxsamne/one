"""Follow-up worktree flow: single-provider follow-ups extend the parent's
task branch directly (no inner per-provider branch, no fresh PR)."""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from core.agents import manager, worktree


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Bare-ish git repo with one commit, all worktree.py globals pointed at it."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo_dir)
    _run(["git", "config", "user.email", "t@t.t"], repo_dir)
    _run(["git", "config", "user.name", "t"], repo_dir)
    (repo_dir / "README.md").write_text("seed\n")
    _run(["git", "add", "README.md"], repo_dir)
    _run(["git", "commit", "-q", "-m", "seed"], repo_dir)

    monkeypatch.setattr(worktree, "REPO_ROOT", repo_dir)
    monkeypatch.setattr(worktree, "WORKTREE_DIR", repo_dir / ".worktrees")
    monkeypatch.setattr(worktree, "AUTO_OPEN_PR", False)  # don't shell out to gh
    return repo_dir


async def test_reuse_base_branch_single_provider_skips_inner_branch_and_pushes_base(repo, monkeypatch):
    # Parent task: normal flow creates task/parent + commits.
    _, parent_base, parent_wts = await worktree.setup("parent", ["fakeprov"])
    assert parent_wts[0].branch == "task/parent-fakeprov"
    (parent_wts[0].path / "p.txt").write_text("parent work\n")
    _run(["git", "add", "p.txt"], parent_wts[0].path)
    _run(["git", "commit", "-q", "-m", "parent commit"], parent_wts[0].path)
    await worktree.merge("parent", parent_base, parent_wts, push=False)
    await worktree.cleanup(parent_wts)

    # Follow-up: reuse_base_branch=True, base_ref=task/parent, single provider.
    starting_ref, base_branch, wts = await worktree.setup(
        "child", ["fakeprov"], base_ref="task/parent", reuse_base_branch=True,
    )
    try:
        assert base_branch == "task/parent"
        assert starting_ref == "task/parent"
        assert len(wts) == 1
        # KEY INVARIANT: worktree's branch IS the base branch — no inner branch.
        assert wts[0].branch == "task/parent"

        # No new task/child-* branch should exist.
        rc = subprocess.call(["git", "rev-parse", "--verify", "task/child-fakeprov"],
                             cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert rc != 0

        # Coder writes a follow-up commit directly on task/parent.
        (wts[0].path / "c.txt").write_text("follow-up\n")
        _run(["git", "add", "c.txt"], wts[0].path)
        _run(["git", "commit", "-q", "-m", "follow-up commit"], wts[0].path)

        # Track every git invocation so we can assert nothing tried to push.
        pushed: list[tuple[str, ...]] = []
        real_git = worktree._git

        async def spy_git(*args, **kwargs):
            if args[:1] == ("push",):
                pushed.append(args)
                return 0, ""  # pretend success — no real remote in this test
            return await real_git(*args, **kwargs)

        monkeypatch.setattr(worktree, "_git", spy_git)

        results = await worktree.merge(
            "child", base_branch, wts,
            push=True, pr_base=starting_ref, pr_title="x",
            open_pr=False,
        )

        # Reuse mode: commits are already on base_branch → status "merged",
        # push attempted (origin doesn't exist but we spy it).
        assert results == {"fakeprov": "merged"}
        assert pushed and pushed[0] == ("push", "-u", "origin", "task/parent")

        # No transient merge worktree should be created for reuse mode.
        assert not (repo / ".worktrees" / "child-merge").exists()
    finally:
        await worktree.cleanup(wts)


async def test_reuse_base_branch_requires_base_ref_and_single_provider(repo):
    with pytest.raises(ValueError):
        await worktree.setup("x", ["a"], reuse_base_branch=True)  # no base_ref
    with pytest.raises(ValueError):
        await worktree.setup("x", ["a", "b"], base_ref="main", reuse_base_branch=True)  # multi-provider


async def test_reuse_base_branch_restores_remote_only_parent_branch(repo):
    origin = repo.parent / "origin.git"
    _run(["git", "init", "-q", "--bare", str(origin)], repo.parent)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)

    _, parent_base, parent_wts = await worktree.setup("parent", ["fakeprov"])
    try:
        (parent_wts[0].path / "p.txt").write_text("parent work\n")
        _run(["git", "add", "p.txt"], parent_wts[0].path)
        _run(["git", "commit", "-q", "-m", "parent commit"], parent_wts[0].path)
        await worktree.merge("parent", parent_base, parent_wts, push=False)
    finally:
        await worktree.cleanup(parent_wts)

    _run(["git", "push", "-u", "origin", "task/parent"], repo)
    _run(["git", "branch", "-D", "task/parent"], repo)

    starting_ref, base_branch, wts = await worktree.setup(
        "child", ["fakeprov"], base_ref="task/parent", reuse_base_branch=True,
    )
    try:
        assert starting_ref == "task/parent"
        assert base_branch == "task/parent"
        assert wts[0].branch == "task/parent"
        assert _run(["git", "rev-parse", "--verify", "task/parent"], repo)
    finally:
        await worktree.cleanup(wts)


async def test_followup_reuse_fetches_and_fast_forwards_parent_branch(repo):
    origin = repo.parent / "origin.git"
    clone = repo.parent / "clone"
    _run(["git", "init", "-q", "--bare", str(origin)], repo.parent)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)

    _run(["git", "checkout", "-q", "-b", "task/parent"], repo)
    (repo / "base.txt").write_text("base\n")
    _run(["git", "add", "base.txt"], repo)
    _run(["git", "commit", "-q", "-m", "parent base"], repo)
    _run(["git", "push", "-u", "origin", "task/parent"], repo)
    local_old = _run(["git", "rev-parse", "task/parent"], repo)

    _run(["git", "clone", "-q", str(origin), str(clone)], repo.parent)
    _run(["git", "config", "user.email", "t@t.t"], clone)
    _run(["git", "config", "user.name", "t"], clone)
    _run(["git", "checkout", "-q", "task/parent"], clone)
    (clone / "remote.txt").write_text("remote update\n")
    _run(["git", "add", "remote.txt"], clone)
    _run(["git", "commit", "-q", "-m", "remote parent update"], clone)
    _run(["git", "push", "origin", "task/parent"], clone)
    remote_new = _run(["git", "rev-parse", "HEAD"], clone)
    assert remote_new != local_old

    _run(["git", "checkout", "-q", "main"], repo)
    assert await manager._resolve_parent_base("parent") == "task/parent"
    _, _, wts = await worktree.setup(
        "child", ["fakeprov"], base_ref="task/parent", reuse_base_branch=True,
    )
    try:
        assert _run(["git", "rev-parse", "HEAD"], wts[0].path) == remote_new
        assert (wts[0].path / "remote.txt").read_text() == "remote update\n"
    finally:
        await worktree.cleanup(wts)


async def test_resolve_parent_base_walks_followup_chain(repo, monkeypatch):
    _run(["git", "checkout", "-q", "-b", "task/root"], repo)
    (repo / "root.txt").write_text("root branch\n")
    _run(["git", "add", "root.txt"], repo)
    _run(["git", "commit", "-q", "-m", "root task"], repo)
    _run(["git", "checkout", "-q", "main"], repo)

    parents = {"mid": "root"}
    monkeypatch.setattr(manager, "task_parent_id", lambda task_id: parents.get(task_id))

    assert await manager._resolve_parent_base("mid") == "task/root"


async def test_new_task_setup_fast_forwards_current_branch_from_origin(repo):
    origin = repo.parent / "origin.git"
    clone = repo.parent / "clone"
    _run(["git", "init", "-q", "--bare", str(origin)], repo.parent)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)

    _run(["git", "clone", "-q", str(origin), str(clone)], repo.parent)
    _run(["git", "config", "user.email", "t@t.t"], clone)
    _run(["git", "config", "user.name", "t"], clone)
    (clone / "remote.txt").write_text("remote main update\n")
    _run(["git", "add", "remote.txt"], clone)
    _run(["git", "commit", "-q", "-m", "remote main update"], clone)
    _run(["git", "push", "origin", "main"], clone)
    remote_new = _run(["git", "rev-parse", "HEAD"], clone)

    assert _run(["git", "rev-parse", "main"], repo) != remote_new
    starting_ref, base_branch, wts = await worktree.setup("child", ["fakeprov"])
    try:
        assert starting_ref == "main"
        assert base_branch == "task/child"
        assert _run(["git", "rev-parse", "main"], repo) == remote_new
        assert (wts[0].path / "remote.txt").read_text() == "remote main update\n"
    finally:
        await worktree.cleanup(wts)


async def test_new_task_setup_defaults_to_main_even_from_feature_branch(repo):
    _run(["git", "checkout", "-q", "-b", "codex/local-feature"], repo)
    (repo / "feature.txt").write_text("feature-only\n")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-q", "-m", "feature-only commit"], repo)

    starting_ref, base_branch, wts = await worktree.setup("child", ["fakeprov"])
    try:
        assert starting_ref == "main"
        assert base_branch == "task/child"
        assert not (wts[0].path / "feature.txt").exists()
        assert (wts[0].path / "README.md").read_text() == "seed\n"
    finally:
        await worktree.cleanup(wts)


async def test_reuse_base_branch_reports_branch_mismatch(repo):
    _, parent_base, parent_wts = await worktree.setup("parent", ["fakeprov"])
    await worktree.merge("parent", parent_base, parent_wts, push=False)
    await worktree.cleanup(parent_wts)

    _, base_branch, wts = await worktree.setup(
        "child", ["fakeprov"], base_ref="task/parent", reuse_base_branch=True,
    )
    try:
        _run(["git", "checkout", "-q", "-b", "accidental"], wts[0].path)
        (wts[0].path / "c.txt").write_text("wrong branch\n")
        _run(["git", "add", "c.txt"], wts[0].path)
        _run(["git", "commit", "-q", "-m", "wrong branch commit"], wts[0].path)

        results = await worktree.merge("child", base_branch, wts, push=False, open_pr=False)
        assert results["fakeprov"].startswith("branch-mismatch: expected task/parent, got accidental")
    finally:
        await worktree.cleanup(wts)


async def test_pr_title_prefers_first_real_commit_subject(repo):
    _run(["git", "checkout", "-q", "-b", "task/title"], repo)
    (repo / "a.txt").write_text("a\n")
    _run(["git", "add", "a.txt"], repo)
    _run(["git", "commit", "-q", "-m", "Merge openai into task/title"], repo)
    (repo / "b.txt").write_text("b\n")
    _run(["git", "add", "b.txt"], repo)
    _run(["git", "commit", "-q", "-m", "Refine article cover and title"], repo)
    (repo / "c.txt").write_text("c\n")
    _run(["git", "add", "c.txt"], repo)
    _run(["git", "commit", "-q", "-m", "Remove duplicate article heading"], repo)

    assert await worktree._pr_title_from_commits(
        "task/title",
        "main",
        "Okay, this is good, but please regenerate the cover image",
    ) == "Refine article cover and title"
