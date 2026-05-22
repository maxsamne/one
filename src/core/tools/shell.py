"""Shell tool — run bash commands with working directory and timeout."""

import asyncio
import re
from pathlib import Path

from core.ai_client.models import Tool
from core.tools.ctx import WORKDIR
from core.tools.fs import PROTECTED_PATH_FILES, PROTECTED_PATH_PARTS

_DEFAULT_TIMEOUT = 60
_SHELL_DELETE_RE = re.compile(r"\b(?:rm|rmdir|unlink|git\s+clean)\b|(?:\bfind\b.*\s-delete\b)")
_PROTECTED_MUTATION_RE = re.compile(
    r"\b(?:mv|truncate|dd|chmod|chown|python\d*|python|node|ruby|perl)\b"
    r"|(?:^|[;&|])\s*:"
    r"|(?:^|[^<>])>{1,2}(?!>)"
)


def _targets_protected_path(command: str) -> bool:
    if re.search(r"\.db(?:\b|$)", command):
        return True
    return any(re.search(rf"(^|[^\w.-]){re.escape(name)}([^\w.-]|$)", command) for name in PROTECTED_PATH_FILES) or any(
        re.search(rf"(^|[^\w.-]){re.escape(part)}(?:/|[^\w.-]|$)", command) for part in PROTECTED_PATH_PARTS
    )


def _check_command(command: str) -> str | None:
    if _SHELL_DELETE_RE.search(command):
        return (
            "FATAL: shell deletion commands are disabled. Use delete_file for normal files; "
            "protected runtime paths like .git/, node_modules/, and local .db files must stay intact."
        )
    if _PROTECTED_MUTATION_RE.search(command) and _targets_protected_path(command):
        return (
            "FATAL: shell command appears to modify a protected runtime path. "
            "Please avoid changing .git/, dependency caches, or local .db files."
        )
    return None


async def run_command(command: str, workdir: str | None = None, timeout: int = _DEFAULT_TIMEOUT) -> str:
    if err := _check_command(command):
        return err
    base = WORKDIR.get()
    if workdir:
        target = (Path(workdir) if Path(workdir).is_absolute() else base / workdir).resolve()
        if not str(target).startswith(str(base.resolve())):
            return f"FATAL: workdir {workdir!r} is outside the allowed directory"
        cwd = str(target)
    else:
        cwd = str(base)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        return f"[exit {proc.returncode}]\n{output}" if output else f"[exit {proc.returncode}]"
    except asyncio.TimeoutError:
        proc.kill()
        return f"RETRYABLE: command timed out after {timeout}s"
    except Exception as e:
        return f"FATAL: {e}"


SHELL = Tool(
    name="run_command",
    description=(
        "Run a bash command. Use workdir to set the working directory relative to repo root. "
        "Prefer specific commands over broad ones. Avoid interactive commands. "
        "Do not use shell deletion commands; use delete_file for normal file deletion."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to run"},
            "workdir": {"type": "string", "description": "Working directory relative to repo root"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
        },
        "required": ["command"],
    },
    fn=run_command,
)

SHELL_TOOLS = [SHELL]
