from core.tools.ctx import WORKDIR
from core.tools.fs import write_file


async def test_persistent_repo_worktree_scope_allows_source_edits_but_blocks_runtime_paths(tmp_path):
    workdir_token = WORKDIR.set(tmp_path)
    try:
        src_result = await write_file("src/core/skills/general/article-writer/SKILL.md", "guidance\n")
        git_result = await write_file(".git/config", "bad\n")
        db_result = await write_file(".agent.db", "bad\n")
    finally:
        WORKDIR.reset(workdir_token)

    assert src_result.startswith("Created:")
    assert (tmp_path / "src/core/skills/general/article-writer/SKILL.md").read_text() == "guidance\n"
    assert git_result == "FATAL: writing to '.git/config' is not allowed — protected runtime path"
    assert db_result == "FATAL: writing to '.agent.db' is not allowed — protected runtime path"
