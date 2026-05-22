from core.tools.shell import run_command


async def test_shell_blocks_deletion_commands_and_protected_path_mutations():
    assert await run_command("rm -rf .git", timeout=1) == (
        "FATAL: shell deletion commands are disabled. Use delete_file for normal files; "
        "protected runtime paths like .git/, node_modules/, and local .db files must stay intact."
    )
    assert await run_command("rm definitely_missing_scratch_file_for_test", timeout=1) == (
        "FATAL: shell deletion commands are disabled. Use delete_file for normal files; "
        "protected runtime paths like .git/, node_modules/, and local .db files must stay intact."
    )
    assert await run_command("find . -name '*.db' -delete", timeout=1) == (
        "FATAL: shell deletion commands are disabled. Use delete_file for normal files; "
        "protected runtime paths like .git/, node_modules/, and local .db files must stay intact."
    )
    assert await run_command("D=.g; D=${D}it; rm -rf $D", timeout=1) == (
        "FATAL: shell deletion commands are disabled. Use delete_file for normal files; "
        "protected runtime paths like .git/, node_modules/, and local .db files must stay intact."
    )
    assert await run_command("mv .git /tmp/git-backup", timeout=1) == (
        "FATAL: shell command appears to modify a protected runtime path. "
        "Please avoid changing .git/, dependency caches, or local .db files."
    )
    assert await run_command("truncate -s 0 .agent.db", timeout=1) == (
        "FATAL: shell command appears to modify a protected runtime path. "
        "Please avoid changing .git/, dependency caches, or local .db files."
    )
    assert await run_command(": > .agent.db", timeout=1) == (
        "FATAL: shell command appears to modify a protected runtime path. "
        "Please avoid changing .git/, dependency caches, or local .db files."
    )
    assert await run_command("dd if=/dev/zero of=.agent.db", timeout=1) == (
        "FATAL: shell command appears to modify a protected runtime path. "
        "Please avoid changing .git/, dependency caches, or local .db files."
    )
    assert await run_command("python -c \"import os; os.remove('.git/config')\"", timeout=1) == (
        "FATAL: shell command appears to modify a protected runtime path. "
        "Please avoid changing .git/, dependency caches, or local .db files."
    )
