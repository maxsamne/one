"""Git tools — branch, status, diff, commit, push."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from core.agents.ledger import get_ledger
from core.agents.task_ctx import current_task_id
from core.ai_client.models import Tool
from core.tools.ctx import WORKDIR, log_call, was_called

_GIT_RESOURCE = "git:repo"


async def _git(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(WORKDIR.get()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace").strip()
    prefix = "FATAL" if proc.returncode != 0 else "OK"
    return f"{prefix}: [exit {proc.returncode}]\n{output}" if output else f"{prefix}: [exit {proc.returncode}]"


@asynccontextmanager
async def _repo_lock(tool: str) -> AsyncIterator[None]:
    agent_id = f"{current_task_id() or 'anon'}:{tool}"
    async with get_ledger().lock(_GIT_RESOURCE, agent_id=agent_id):
        yield


async def _read(tool: str, args: dict, *git_args: str) -> str:
    result = await _git(*git_args)
    log_call(tool, args, result)
    return result


async def _write(tool: str, args: dict, *git_args: str) -> str:
    async with _repo_lock(tool):
        result = await _git(*git_args)
    log_call(tool, args, result)
    return result


def _check(requires: str, current: str) -> str | None:
    if not was_called(requires):
        return f"RETRYABLE: must call {requires} before {current}"
    return None


async def git_status() -> str:
    return await _read("git_status", {}, "status", "--short")


async def git_diff(target: str = "HEAD") -> str:
    return await _read("git_diff", {"target": target}, "diff", target)


async def git_log(n: int = 10) -> str:
    return await _read("git_log", {"n": n}, "log", f"-{n}", "--oneline")


async def git_create_branch(branch: str) -> str:
    return await _write("git_create_branch", {"branch": branch}, "checkout", "-b", branch)


async def git_checkout(branch: str) -> str:
    return await _write("git_checkout", {"branch": branch}, "checkout", branch)


async def git_add(path: str | list[str] = ".") -> str:
    # Accept either a single path or a list — git itself takes multiple pathspec
    # args, but the tool's old `path: str` shape tempted the model to concatenate
    # paths with spaces, which git then read as one bogus pathspec.
    paths = [path] if isinstance(path, str) else list(path)
    if not paths:
        paths = ["."]
    return await _write("git_add", {"path": paths if len(paths) > 1 else paths[0]}, "add", *paths)


async def git_commit(message: str) -> str:
    if err := _check("git_add", "git_commit"):
        return err
    return await _write("git_commit", {"message": message}, "commit", "-m", message)


async def git_push(remote: str = "origin", branch: str | None = None) -> str:
    if err := _check("git_commit", "git_push"):
        return err
    args = ("push", remote, *((branch,) if branch else ()))
    return await _write("git_push", {"remote": remote, "branch": branch}, *args)


async def git_create_pr(title: str, body: str = "", base: str = "main") -> str:
    if err := _check("git_push", "git_create_pr"):
        return err
    proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "create", "--title", title, "--base", base, "--body", body or "",
        cwd=str(WORKDIR.get()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace").strip()
    prefix = "FATAL" if proc.returncode != 0 else "OK"
    result = f"{prefix}: [exit {proc.returncode}]\n{output}" if output else f"{prefix}: [exit {proc.returncode}]"
    log_call("git_create_pr", {"title": title, "base": base}, result)
    return result


# --- Tool definitions ---

GIT_STATUS = Tool(
    name="git_status",
    description="Show working tree status (short format).",
    parameters={"type": "object", "properties": {}, "required": []},
    fn=git_status,
    is_read_only=True,
    is_concurrency_safe=True,
)

GIT_DIFF = Tool(
    name="git_diff",
    description="Show diff against a target (default HEAD). Use 'main' to see branch diff.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string", "description": "Ref to diff against (default HEAD)"}},
        "required": [],
    },
    fn=git_diff,
    is_read_only=True,
    is_concurrency_safe=True,
)

GIT_CREATE_BRANCH = Tool(
    name="git_create_branch",
    description="Create and checkout a new branch.",
    parameters={
        "type": "object",
        "properties": {"branch": {"type": "string", "description": "Branch name, e.g. task/my-feature"}},
        "required": ["branch"],
    },
    fn=git_create_branch,
)

GIT_CHECKOUT = Tool(
    name="git_checkout",
    description="Checkout an existing branch.",
    parameters={
        "type": "object",
        "properties": {"branch": {"type": "string", "description": "Branch name to checkout"}},
        "required": ["branch"],
    },
    fn=git_checkout,
)

GIT_ADD = Tool(
    name="git_add",
    description="Stage files for commit. Defaults to all changes ('.').",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "description": "Path(s) to stage. Pass a single string OR a list of strings for multiple files. Default '.' stages everything.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
        },
        "required": [],
    },
    fn=git_add,
)

GIT_COMMIT = Tool(
    name="git_commit",
    description="Commit staged changes with a message.",
    parameters={
        "type": "object",
        "properties": {"message": {"type": "string", "description": "Commit message (use 'message', not 'commit_message' or 'msg')"}},
        "required": ["message"],
    },
    fn=git_commit,
)

GIT_LOG = Tool(
    name="git_log",
    description="Show recent commit history.",
    parameters={
        "type": "object",
        "properties": {"n": {"type": "integer", "description": "Number of commits (default 10)"}},
        "required": [],
    },
    fn=git_log,
    is_read_only=True,
    is_concurrency_safe=True,
)

GIT_PUSH = Tool(
    name="git_push",
    description="Push commits to a remote. Requires git_commit to have been called first.",
    parameters={
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote name (default 'origin')"},
            "branch": {"type": "string", "description": "Branch to push (default: current branch)"},
        },
        "required": [],
    },
    fn=git_push,
)

GIT_CREATE_PR = Tool(
    name="git_create_pr",
    description="Open a GitHub pull request from the current branch into base (default 'main'). Requires git_push to have been called first.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR description (markdown). Leave empty for a minimal PR."},
            "base": {"type": "string", "description": "Base branch to merge into (default 'main')"},
        },
        "required": ["title"],
    },
    fn=git_create_pr,
)

GIT_TOOLS = [GIT_STATUS, GIT_DIFF, GIT_CREATE_BRANCH, GIT_CHECKOUT, GIT_ADD, GIT_COMMIT, GIT_PUSH, GIT_LOG, GIT_CREATE_PR]
