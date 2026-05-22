from core.tools.shell import run_command


async def test_shell_blocks_destructive_commands_targeting_protected_paths():
    assert await run_command("rm -rf .git", timeout=1) == (
        "FATAL: destructive shell command targets a protected runtime path; "
        "use filesystem tools for file deletion"
    )
    assert await run_command("rm .agent.db", timeout=1) == (
        "FATAL: destructive shell command targets a protected runtime path; "
        "use filesystem tools for file deletion"
    )
    assert await run_command("find . -name '*.db' -delete", timeout=1) == (
        "FATAL: destructive shell command targets a protected runtime path; "
        "use filesystem tools for file deletion"
    )
    assert (await run_command("rm definitely_missing_scratch_file_for_test", timeout=1)).startswith("[exit ")
