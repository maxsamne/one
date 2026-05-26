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


async def test_git_diff_timeline_stat_mode_omits_patch(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    _commit(tmp_path, "Initial")
    _git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "a.txt").write_text("b\n", encoding="utf-8")
    _commit(tmp_path, "Change a")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await git_diff_timeline(base="main", output_mode="stat")
    finally:
        WORKDIR.reset(tok)

    assert "Change a" in out
    assert "a.txt" in out
    assert "```diff" not in out
