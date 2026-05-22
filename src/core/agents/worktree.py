"""Git worktree setup, merge, and cleanup for parallel coder dispatch."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from core.agents.ledger import get_ledger
from core.log import Category
from core.log import log as _log
from core.tools.ctx import REPO_ROOT

WORKTREE_DIR = REPO_ROOT / ".worktrees"
_GIT_RESOURCE = "git:repo"

# Open a draft PR on origin after a successful merge+push.
AUTO_OPEN_PR = True


@dataclass(frozen=True)
class Worktree:
    provider: str
    branch: str
    path: Path


@asynccontextmanager
async def branch_lock(branch: str, *, agent_id: str) -> AsyncIterator[None]:
    """Serialize direct reuse of a task branch across follow-up runs."""
    async with get_ledger().lock(f"git:branch:{branch}", agent_id=agent_id):
        yield


async def _git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    # Resolve REPO_ROOT at call time, not def time — tests monkeypatch the module attr.
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd or REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def _current_branch() -> str:
    _, name = await _git("rev-parse", "--abbrev-ref", "HEAD")
    return name


async def fetch_branch(branch: str) -> None:
    """Refresh origin/<branch> when a remote exists. Best-effort for local-only repos."""
    rc, _ = await _git("remote", "get-url", "origin")
    if rc != 0:
        return
    rc, out = await _git("fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")
    if rc != 0:
        _log(Category.AGENT, "branch fetch failed", branch=branch, error=out.splitlines()[0] if out else "unknown")


async def _fast_forward_local_branch_from_origin(branch: str) -> None:
    rc, _ = await _git("rev-parse", "--verify", f"origin/{branch}")
    if rc != 0:
        return
    rc, _ = await _git("rev-parse", "--verify", branch)
    if rc != 0:
        rc, out = await _git("branch", branch, f"origin/{branch}")
        if rc != 0:
            _log(Category.AGENT, "base branch restore failed", branch=branch, error=out)
            raise RuntimeError(f"could not restore {branch} from origin/{branch}: {out}")
        return
    rc, _ = await _git("merge-base", "--is-ancestor", branch, f"origin/{branch}")
    if rc == 0:
        rc, out = await _git("branch", "-f", branch, f"origin/{branch}")
        if rc != 0:
            _log(Category.AGENT, "base branch fast-forward failed", branch=branch, error=out)
            raise RuntimeError(f"could not fast-forward {branch} from origin/{branch}: {out}")


async def setup(
    task_id: str,
    providers: list[str],
    base_ref: str | None = None,
    *,
    reuse_base_branch: bool = False,
) -> tuple[str, str, list[Worktree]]:
    """Create the task's base branch + one worktree per provider.

    Returns (starting_ref, base_branch, worktrees). starting_ref is the branch
    the task forked off — the natural PR target. Holds the repo lock for the
    whole setup so concurrent tasks don't fight over branch creation.

    `reuse_base_branch=True` (single-provider follow-up mode): the worktree
    checks out `base_ref` directly with no inner `task/<id>-<provider>` branch.
    Coder commits land on `base_ref`, which is also returned as `base_branch`.
    Caller is responsible for pushing it and skipping PR creation. Requires
    `base_ref` to be set and `len(providers) == 1`.
    """

    if reuse_base_branch:
        if not base_ref:
            raise ValueError("reuse_base_branch requires base_ref")
        if len(providers) != 1:
            raise ValueError("reuse_base_branch only supports a single provider")
        base_branch = base_ref
        starting_ref = base_ref
    else:
        base_branch = f"task/{task_id}"
        starting_ref = base_ref or await _current_branch()

    async with get_ledger().lock(_GIT_RESOURCE, agent_id=f"{task_id}:setup"):
        if reuse_base_branch:
            await _fast_forward_local_branch_from_origin(base_branch)
            rc, out = await _git("rev-parse", "--verify", base_branch)
            if rc != 0:
                raise RuntimeError(f"reuse base branch {base_branch} does not exist: {out}")
        if not reuse_base_branch:
            rc, _ = await _git("rev-parse", "--verify", base_branch)
            if rc != 0:
                await _git("branch", base_branch, starting_ref)

        WORKTREE_DIR.mkdir(exist_ok=True)
        worktrees: list[Worktree] = []
        for provider in providers:
            path = WORKTREE_DIR / f"{task_id}-{provider}"
            if reuse_base_branch:
                branch = base_branch  # commits land directly on the parent task branch
                rc, out = await _git("worktree", "add", str(path), base_branch)
            else:
                branch = f"task/{task_id}-{provider}"
                rc, out = await _git("worktree", "add", "-b", branch, str(path), base_branch)
            if rc != 0:
                _log(Category.AGENT, "worktree create failed", provider=provider, error=out)
                raise RuntimeError(f"worktree add failed for {provider}: {out}")
            worktrees.append(Worktree(provider=provider, branch=branch, path=path))

    _log(Category.AGENT, "worktrees ready",
         base=base_branch, starting_ref=starting_ref,
         providers=providers, reuse=reuse_base_branch)
    return starting_ref, base_branch, worktrees


async def _commits_ahead_of_origin(branch: str) -> int:
    """Count commits on `branch` not yet on its origin/ remote. Returns the count if
    origin/<branch> exists, else any commits on the branch are assumed unpushed."""
    rc, _ = await _git("rev-parse", "--verify", f"origin/{branch}")
    if rc != 0:
        rc2, c = await _git("rev-list", "--count", branch)
        return int(c.strip() or "0") if rc2 == 0 else 1
    rc, ahead = await _git("rev-list", "--count", f"origin/{branch}..{branch}")
    return int(ahead.strip() or "0") if rc == 0 else 0


async def _pr_title_from_commits(head: str, base: str, fallback: str | None) -> str:
    rc, out = await _git("log", "--reverse", "--format=%s", f"{base}..{head}")
    if rc == 0:
        for subject in out.splitlines():
            subject = subject.strip()
            if subject and not subject.startswith("Merge "):
                return subject[:72]
    return (fallback or f"task {head.removeprefix('task/')}")[:72]


async def _worktree_status(wt: Worktree) -> tuple[str, str | None]:
    rc, head = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt.path)
    if rc != 0:
        return "error", head or "could not read HEAD"
    rc, dirty = await _git("status", "--porcelain", cwd=wt.path)
    if rc == 0 and dirty.strip():
        return "dirty", dirty.splitlines()[0]
    return head, None


async def merge(
    task_id: str,
    base_branch: str,
    worktrees: list[Worktree],
    push: bool = True,
    pr_base: str | None = None,
    pr_title: str | None = None,
    open_pr: bool = True,
) -> dict[str, str]:
    """Sequentially merge each provider branch into base_branch.

    Uses a temporary worktree so the main working tree's HEAD is never touched.
    Returns {provider: status} where status is 'merged', 'no-op', or 'conflict: <msg>'.
    If `push` and at least one provider merged, push base_branch to origin.
    If `pr_base` is set, `open_pr` is True, and AUTO_OPEN_PR is True, open a
    draft PR against that branch.

    Follow-up reuse mode: when a worktree's branch equals base_branch (commits
    landed directly on base_branch — see `setup(reuse_base_branch=True)`), the
    merge step is skipped for that provider; push handles it.
    """

    merge_path = WORKTREE_DIR / f"{task_id}-merge"
    results: dict[str, str] = {}
    needs_merge_worktree = any(wt.branch != base_branch for wt in worktrees)

    async with get_ledger().lock(_GIT_RESOURCE, agent_id=f"{task_id}:merge"):
        if needs_merge_worktree:
            await _git("worktree", "add", str(merge_path), base_branch)
        try:
            for wt in worktrees:
                head, detail = await _worktree_status(wt)
                if head == "dirty":
                    results[wt.provider] = f"dirty: uncommitted changes remain ({detail})"
                    _log(Category.AGENT, "merge skipped — worktree dirty", provider=wt.provider, dirty=detail)
                    continue
                if head == "error":
                    results[wt.provider] = f"conflict: {detail}"
                    continue
                if head != wt.branch:
                    results[wt.provider] = f"branch-mismatch: expected {wt.branch}, got {head}"
                    _log(Category.AGENT, "merge skipped — branch mismatch",
                         provider=wt.provider, expected=wt.branch, actual=head)
                    continue
                if wt.branch == base_branch:
                    # Reuse mode — commits already on base_branch. Mark "merged" if
                    # the branch has anything unpushed, else "no-op".
                    ahead = await _commits_ahead_of_origin(base_branch)
                    results[wt.provider] = "merged" if ahead > 0 else "no-op"
                    continue
                rc, ahead = await _git("rev-list", "--count", f"{base_branch}..{wt.branch}")
                if rc == 0 and ahead.strip() == "0":
                    results[wt.provider] = "no-op"
                    continue
                rc, out = await _git("merge", "--no-ff", "-m", f"Merge {wt.provider} into {base_branch}", wt.branch, cwd=merge_path)
                if rc != 0:
                    await _git("merge", "--abort", cwd=merge_path)
                    results[wt.provider] = f"conflict: {out.splitlines()[0] if out else 'unknown'}"
                    _log(Category.AGENT, "merge conflict", provider=wt.provider)
                else:
                    results[wt.provider] = "merged"
        finally:
            if needs_merge_worktree:
                await _git("worktree", "remove", "--force", str(merge_path))

        if push and any(s == "merged" for s in results.values()):
            rc, out = await _git("push", "-u", "origin", base_branch)
            if rc == 0:
                _log(Category.AGENT, "branch pushed", branch=base_branch)
                if AUTO_OPEN_PR and open_pr and pr_base:
                    await _open_pr(task_id, base_branch, pr_base, pr_title)
            else:
                _log(Category.AGENT, "push failed", branch=base_branch, error=out.splitlines()[0] if out else "unknown")

    _log(Category.AGENT, "merge complete", base=base_branch, results=results, open_pr=open_pr)
    return results


async def _open_pr(task_id: str, head: str, base: str, title: str | None) -> None:
    from core.agents.task_ctx import PR_URL_CTX
    title = await _pr_title_from_commits(head, base, title)
    body = f"Auto-generated by task `{task_id}`.\n\nTitle: {title}"
    proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "create", "--draft",
        "--base", base, "--head", head,
        "--title", title, "--body", body,
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="replace").strip()
    if proc.returncode == 0:
        url = text.splitlines()[-1] if text else ""
        _log(Category.AGENT, "pr opened", url=url, base=base, head=head)
        if url:
            PR_URL_CTX.set(url)
    else:
        _log(Category.AGENT, "pr open failed", base=base, head=head, error=text.splitlines()[-1] if text else "unknown")


async def cleanup(worktrees: list[Worktree]) -> None:
    for wt in worktrees:
        rc, out = await _git("worktree", "remove", "--force", str(wt.path))
        if rc != 0:
            _log(Category.AGENT, "worktree cleanup failed", provider=wt.provider, error=out)


# --- Sub-agent worktree helpers ---


@dataclass(frozen=True)
class SubWorktree:
    sub_id: str
    branch: str
    path: Path
    parent_branch: str


async def setup_subagent_worktree(task_id: str, sub_id: str, parent_workdir: Path) -> SubWorktree:
    """Create a worktree branched from the parent coder's current HEAD.

    Holds the repo lock for the create. Parent must already be in a worktree
    (e.g. created by setup() above) — we read its current branch to fork from."""
    rc, parent_branch = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=parent_workdir)
    if rc != 0 or not parent_branch or parent_branch == "HEAD":
        raise RuntimeError(f"could not determine parent branch from {parent_workdir}: {parent_branch}")

    sub_branch = f"{parent_branch}-sub-{sub_id}"
    sub_path = WORKTREE_DIR / f"{task_id}-sub-{sub_id}"

    async with get_ledger().lock(_GIT_RESOURCE, agent_id=f"{task_id}:sub-{sub_id}:setup"):
        WORKTREE_DIR.mkdir(exist_ok=True)
        rc, out = await _git("worktree", "add", "-b", sub_branch, str(sub_path), parent_branch)
        if rc != 0:
            _log(Category.AGENT, "subagent worktree create failed", sub_id=sub_id, error=out)
            raise RuntimeError(f"subagent worktree add failed: {out}")

    _log(Category.AGENT, "subagent worktree ready", sub_id=sub_id, branch=sub_branch, parent_branch=parent_branch)
    return SubWorktree(sub_id=sub_id, branch=sub_branch, path=sub_path, parent_branch=parent_branch)


async def merge_subagent_worktree(task_id: str, sub: SubWorktree, parent_workdir: Path) -> str:
    """Merge sub-agent's branch back into parent's branch.

    Runs `git merge` inside the parent's workdir under the git:repo lock.
    The parent coder is awaiting the spawn_subagent call so its workdir is
    idle during the merge — safe to mutate. Aborts cleanly on uncommitted
    changes in the parent or on merge conflicts.

    Returns 'merged' | 'no-op' | 'conflict: <line>' | 'dirty: <line>'.
    """
    async with get_ledger().lock(_GIT_RESOURCE, agent_id=f"{task_id}:sub-{sub.sub_id}:merge"):
        rc, ahead = await _git("rev-list", "--count", f"{sub.parent_branch}..{sub.branch}")
        if rc == 0 and ahead.strip() == "0":
            _log(Category.AGENT, "subagent merge no-op", sub_id=sub.sub_id)
            return "no-op"

        rc, dirty = await _git("status", "--porcelain", cwd=parent_workdir)
        if rc == 0 and dirty.strip():
            line = dirty.splitlines()[0]
            _log(Category.AGENT, "subagent merge skipped — parent dirty", sub_id=sub.sub_id, dirty=line)
            return f"dirty: parent has uncommitted changes ({line}). Sub-agent's commits remain on branch {sub.branch}."

        rc, out = await _git(
            "merge", "--no-ff",
            "-m", f"Merge sub-{sub.sub_id} into {sub.parent_branch}",
            sub.branch,
            cwd=parent_workdir,
        )
        if rc != 0:
            await _git("merge", "--abort", cwd=parent_workdir)
            line = out.splitlines()[0] if out else "unknown"
            _log(Category.AGENT, "subagent merge conflict", sub_id=sub.sub_id, error=line)
            return f"conflict: {line}"

    _log(Category.AGENT, "subagent merged", sub_id=sub.sub_id, branch=sub.branch)
    return "merged"


async def cleanup_subagent_worktree(sub: SubWorktree) -> None:
    rc, out = await _git("worktree", "remove", "--force", str(sub.path))
    if rc != 0:
        _log(Category.AGENT, "subagent worktree cleanup failed", sub_id=sub.sub_id, error=out)
