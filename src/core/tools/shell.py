"""Shell tool — run bash commands with working directory and timeout."""

import asyncio
from pathlib import Path

from core.ai_client.models import Tool
from core.tools.ctx import WORKDIR

_DEFAULT_TIMEOUT = 60


async def run_command(command: str, workdir: str | None = None, timeout: int = _DEFAULT_TIMEOUT) -> str:
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
        "Prefer specific commands over broad ones. Avoid interactive commands."
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
