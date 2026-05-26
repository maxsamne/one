"""Git tools — branch, status, diff, commit, push."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from core.agents.ledger import get_ledger
from core.agents.task_ctx import current_task_id
from core.ai_client.models import Tool
from core.tools.ctx import WORKDIR, log_call, was_called

_GIT_RESOURCE = "git:repo"
_TIMELINE_DEFAULT_COMMITS = 6
_TIMELINE_MAX_COMMITS = 12
_TIMELINE_MAX_BYTES = 7_500
_TIMELINE_PER_COMMIT_PATCH_BYTES = 1_400


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


async def _git_raw(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(WORKDIR.get()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace").strip()


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


def _clip_text(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    head = encoded[: max_bytes // 2].decode("utf-8", errors="ignore")
    tail = encoded[-max_bytes // 2:].decode("utf-8", errors="ignore")
    omitted = len(encoded) - len(head.encode("utf-8")) - len(tail.encode("utf-8"))
    return f"{head}\n[...{omitted} bytes omitted...]\n{tail}"


async def git_diff_timeline(
    base: str = "main",
    n: int = _TIMELINE_DEFAULT_COMMITS,
    output_mode: str = "patch",
    path: str | None = None,
) -> str:
    """Show per-commit branch history, oldest to newest, with bounded diffs."""
    args = {"base": base, "n": n, "output_mode": output_mode, "path": path or ""}
    if output_mode not in {"stat", "patch"}:
        result = "FATAL: invalid output_mode; use 'stat' or 'patch'"
        log_call("git_diff_timeline", args, result)
        return result
    n = max(1, min(int(n or _TIMELINE_DEFAULT_COMMITS), _TIMELINE_MAX_COMMITS))

    rc, merge_base = await _git_raw("merge-base", base, "HEAD")
    if rc != 0 or not merge_base:
        result = f"FATAL: could not find merge-base with {base!r}: {merge_base}"
        log_call("git_diff_timeline", args, result)
        return result

    rev_list_args = ["rev-list", "--reverse", f"{merge_base}..HEAD"]
    if path:
        rev_list_args.extend(["--", path])
    rc, revs = await _git_raw(*rev_list_args)
    if rc != 0:
        result = f"FATAL: could not list branch commits: {revs}"
        log_call("git_diff_timeline", args, result)
        return result
    commits = [line.strip() for line in revs.splitlines() if line.strip()]
    if not commits:
        scope = f" touching {path!r}" if path else ""
        result = f"No commits on current branch after merge-base with {base}{scope}."
        log_call("git_diff_timeline", args, result)
        return result

    omitted = max(0, len(commits) - n)
    selected = commits[-n:]
    pathspec = ["--", path] if path else []
    sections = [
        (
            f"Commit diff timeline for HEAD since {base} "
            f"(showing {len(selected)} of {len(commits)} commit(s), oldest to newest)."
        )
    ]
    if omitted:
        sections.append(
            f"[{omitted} older commit(s) omitted; "
            f"increase n up to {_TIMELINE_MAX_COMMITS} if needed.]"
        )
    sections.append(
        "Use this for follow-ups, regressions, or restoring an earlier branch version; "
        "compare adjacent commits instead of only the final flattened diff."
    )

    for idx, commit in enumerate(selected, start=1):
        rc, title = await _git_raw("show", "-s", "--format=%h %s", commit)
        if rc != 0:
            title = commit[:12]
        rc, stat = await _git_raw("show", "--stat", "--format=", commit, *pathspec)
        stat = stat or "(no matching file changes)"
        section = [f"## {idx}. {title}", "```text", stat, "```"]
        if output_mode == "patch":
            rc, patch = await _git_raw(
                "show",
                "--format=",
                "--find-renames",
                "--unified=2",
                commit,
                *pathspec,
            )
            patch = _clip_text(patch or "(no matching patch)", _TIMELINE_PER_COMMIT_PATCH_BYTES)
            section.extend(["```diff", patch, "```"])
        sections.append("\n".join(section))

    result = _clip_text("\n\n".join(sections), _TIMELINE_MAX_BYTES)
    log_call("git_diff_timeline", args, f"OK: {len(selected)} commit(s) shown from {len(commits)} total")
    return result


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
    target = branch or (await _git("rev-parse", "--abbrev-ref", "HEAD")).strip()
    args = ("push", "--set-upstream", remote, target)
    return await _write("git_push", {"remote": remote, "branch": target}, *args)


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

GIT_DIFF_TIMELINE = Tool(
    name="git_diff_timeline",
    description=(
        "Show commit-by-commit diffs for the current branch since a base ref. "
        "Use this on follow-up PR tasks, regressions, or when the user refers to an earlier version "
        "so you can see how the branch evolved instead of only the final flattened diff."
    ),
    parameters={
        "type": "object",
        "properties": {
            "base": {"type": "string", "description": "Base ref to compare from (default 'main')"},
            "n": {
                "type": "integer",
                "description": (
                    "Number of latest branch commits to show, oldest to newest. "
                    f"Default {_TIMELINE_DEFAULT_COMMITS}, max {_TIMELINE_MAX_COMMITS}."
                ),
            },
            "output_mode": {
                "type": "string",
                "enum": ["stat", "patch"],
                "description": (
                    "stat = per-commit file stats only; "
                    "patch = include bounded per-commit patches (default)"
                ),
            },
            "path": {"type": "string", "description": "Optional path filter, e.g. 'docs/index.html'"},
        },
        "required": [],
    },
    fn=git_diff_timeline,
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

GIT_TOOLS = [
    GIT_STATUS,
    GIT_DIFF,
    GIT_DIFF_TIMELINE,
    GIT_CREATE_BRANCH,
    GIT_CHECKOUT,
    GIT_ADD,
    GIT_COMMIT,
    GIT_PUSH,
    GIT_LOG,
    GIT_CREATE_PR,
]
