import subprocess

from core.tools.ctx import WORKDIR
from core.tools.git import git_diff_timeline


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo, message):
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


async def test_git_diff_timeline_shows_commit_by_commit_patches(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "site.html").write_text("icon: ◐\nblur: old\n", encoding="utf-8")
    _commit(tmp_path, "Initial site")
    _git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "site.html").write_text("icon: ◑\nblur: old\n", encoding="utf-8")
    _commit(tmp_path, "Change icon")
    (tmp_path / "site.html").write_text("icon: ◑\nblur: glass\n", encoding="utf-8")
    _commit(tmp_path, "Restore glass")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await git_diff_timeline(base="main", path="site.html")
    finally:
        WORKDIR.reset(tok)

    assert "Commit diff timeline for HEAD since main" in out
    assert "Change icon" in out
    assert "Restore glass" in out
    assert "-icon: ◐" in out
    assert "+blur: glass" in out


async def test_git_diff_timeline_bounds_commit_count(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    _commit(tmp_path, "Initial")
    _git(tmp_path, "checkout", "-b", "feature")
    for idx in range(3):
        (tmp_path / "a.txt").write_text(f"{idx}\n", encoding="utf-8")
        _commit(tmp_path, f"Change {idx}")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await git_diff_timeline(base="main", n=2)
    finally:
        WORKDIR.reset(tok)

    assert "showing 2 of 3 commit(s)" in out
    assert "1 older commit(s) omitted" in out
    assert "Change 0" not in out
    assert "Change 1" in out
    assert "Change 2" in out
    assert "```diff" in out
