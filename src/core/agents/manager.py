"""Manager — mode classification + deterministic skill pre-loading + dispatch.

Pivot (2026-05): the manager no longer LLM-picks domains or skills. Instead:
1. Skills are pre-loaded from `TASK_SKILLS_CTX` (user explicitly attached via the UI).
2. Mode is classified (conversational vs persistent) by either a heuristic or, if an
   `orchestrator` AiClient is provided, one cheap LLM call. Mode determines tmp dir vs worktree.
3. The DispatchRouter (`core.agents.router`) picks `(provider, model, thinking)` per dispatch.
4. The coder gets pre-loaded skill bodies + the always-injected skills index + the
   `load_skill` tool to fetch any other skill mid-loop.

The result: zero LLM calls inside manager when mode is unambiguous; one when not.
"""

import shutil
import time
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from core.agents import coder, graders, router, skills, workdir_registry, worktree
from core.agents.coder import _INSTRUCTIONS_BASE, _INSTRUCTIONS_PERSISTENT
from core.agents.grader import GRADER_HOOK_RETRIES
from core.agents.hooks import DEFAULT_HOOK_RETRIES, Hook, HookPolicy
from core.agents.task_ctx import PR_URL_CTX, TASK_GRADERS_CTX, TASK_IMAGES_CTX, TASK_SKILLS_CTX, TIER_CTX, current_task_id
from core.ai_client import AiClient
from core.ai_client.models import ImageContent, ThinkingLevel, Tool
from core.log import Category
from core.log import log as _log
from core.log import task_pr_url
from core.log import transcript_load
from core.prompt import date_context
from core.tools.calc import CALC_TOOLS
from core.tools.ctx import REPO_ROOT, WORKDIR
from core.tools.fs import FS_TOOLS
from core.tools.git import GIT_ADD, GIT_COMMIT, GIT_DIFF, GIT_LOG, GIT_STATUS
from core.tools.shell import SHELL_TOOLS


class TaskMode(StrEnum):
    CONVERSATIONAL = "conversational"  # Q&A, calc, explanations — answer is the deliverable
    PERSISTENT = "persistent"          # code/file changes that should be committed


CONVERSATIONAL_TMP_CLEANUP_ON_SUCCESS = False
_TMP_DIR = REPO_ROOT / "generated" / "tmp"
_MANAGED_GIT_TOOLS = [GIT_STATUS, GIT_DIFF, GIT_ADD, GIT_COMMIT, GIT_LOG]
_PERSISTENT_TOOLS = FS_TOOLS + SHELL_TOOLS + _MANAGED_GIT_TOOLS + CALC_TOOLS
_CONVERSATIONAL_TOOLS = FS_TOOLS + CALC_TOOLS

_MODE_INSTRUCTIONS = (
    "Classify this task as either 'conversational' or 'persistent'.\n\n"
    "- 'conversational': the answer itself is the deliverable. Q&A, calculations, "
    "explanations, simple lookups, summaries, code review without changes. No need "
    "to modify the codebase.\n"
    "- 'persistent': the task requires creating or modifying files that should be kept. "
    "Code changes, new features, generated reports/scripts, anything that modifies the "
    "repo and should be committed.\n\n"
    "When in doubt: prefer 'conversational' for short questions and 'persistent' for "
    "anything mentioning files, scripts, code, building, or generating an artifact."
)


class _ModePlan(BaseModel):
    mode: TaskMode = Field(description="One of: conversational, persistent")


def _heuristic_mode(task: str) -> TaskMode:
    return TaskMode.CONVERSATIONAL if len(task.split()) < 3 else TaskMode.PERSISTENT


async def _classify_mode(task: str, orchestrator: AiClient | None) -> TaskMode:
    """One cheap LLM call to decide conversational vs persistent. Falls back to heuristic."""
    if orchestrator is None or len(task.split()) < 3:
        return _heuristic_mode(task)
    try:
        plan = await orchestrator.complete(
            f"Task: {task}",
            instructions=_MODE_INSTRUCTIONS,
            thinking=ThinkingLevel.MINIMAL,
            response_model=_ModePlan,
        )
        return plan.mode
    except Exception as e:
        _log(Category.AGENT, "mode classification failed, using heuristic", error=str(e)[:120])
        return _heuristic_mode(task)


_CONVERSATIONAL_INSTRUCTIONS = """\
This task is conversational — your final answer is the deliverable, not files in the repo.

You have an isolated scratch directory (your current workdir) for any temporary files
you need (notes, intermediate scripts, calculations). All file tools and shell commands
are sandboxed to this directory — you cannot read or write the main repo.

When you're done, output your answer clearly and concisely to the user.
Do not commit anything. Do not git_add. Just answer the question.

Output: cite sources as [text](url), never bare URLs. Don't name tools, providers, or formats.

"Artifact" (also: interactive, report, dashboard, page, infographic, visualization) = a complete self-contained HTML document. If the user asks for one — or for any chart/dashboard/visualization — your response is a single ```html``` code block, no prose around it, no asking which format. Load libraries from cdnjs.cloudflare.com.\
"""

_CONVERSATIONAL_BASE = "\n\n---\n\n".join([_INSTRUCTIONS_BASE, _CONVERSATIONAL_INSTRUCTIONS])
_PERSISTENT_BASE = "\n\n---\n\n".join([_INSTRUCTIONS_BASE, _INSTRUCTIONS_PERSISTENT])

_MANAGED_GIT_INSTRUCTIONS = """\
## Managed git lifecycle
The manager already created the correct branch and will push/open/update the PR after
your final answer. Do not create branches, check out branches, push, or open PRs.
Use only git_status, git_diff, git_add, git_commit, and git_log for your own changes.
"""

_HTML_ARTIFACT_REQUEST_RE = re.compile(
    r"\b(?:"
    r"artifact|interactive|dashboard|visualization|visualisation|infographic|"
    r"report|page|standalone|self-contained"
    r")\b|"
    r"\b(?:full|complete|inline|self-contained)\s+html\b|"
    r"html\s+block|```html|paste\s+.*html",
    re.IGNORECASE,
)
_HTML_ARTIFACT_LIMIT = 3
_HTML_ARTIFACT_MAX_BYTES = 750_000


def _hook_policy(task: str) -> HookPolicy:
    """Referenced HTML must be renderable; explicit inline requests require HTML."""
    return HookPolicy(require_inline_html=bool(_HTML_ARTIFACT_REQUEST_RE.search(task)))


async def _dirty_line(workdir: Path) -> str | None:
    rc, out = await worktree._git("status", "--porcelain", cwd=workdir)
    if rc == 0 and out.strip():
        return out.splitlines()[0]
    return None


def _safe_workdir_file(workdir: Path, rel: str) -> Path | None:
    candidate = workdir / rel
    try:
        resolved = candidate.resolve(strict=True)
        root = workdir.resolve()
    except (FileNotFoundError, OSError):
        return None
    if not (resolved == root or root in resolved.parents):
        return None
    return resolved if resolved.is_file() else None


async def _changed_html_files(workdir: Path, start_ref: str | None) -> list[Path]:
    """HTML files created/changed in this workdir since dispatch started."""
    changed: set[Path] = set()

    if start_ref:
        rc, out = await worktree._git("diff", "--name-only", "--diff-filter=ACMR", f"{start_ref}..HEAD", cwd=workdir)
        if rc == 0:
            changed.update(
                p for rel in out.splitlines()
                if rel.endswith(".html") and (p := _safe_workdir_file(workdir, rel))
            )
        rc, out = await worktree._git("diff", "--name-only", "--diff-filter=ACMR", "HEAD", cwd=workdir)
        if rc == 0:
            changed.update(
                p for rel in out.splitlines()
                if rel.endswith(".html") and (p := _safe_workdir_file(workdir, rel))
            )
        rc, out = await worktree._git("ls-files", "--others", "--exclude-standard", "--", "*.html", cwd=workdir)
        if rc == 0:
            changed.update(
                p for rel in out.splitlines()
                if rel.endswith(".html") and (p := _safe_workdir_file(workdir, rel))
            )
    else:
        ignored = {".git", ".worktrees", ".venv", "node_modules", "__pycache__"}
        for path in workdir.rglob("*.html"):
            if ignored.intersection(path.relative_to(workdir).parts):
                continue
            if safe := _safe_workdir_file(workdir, str(path.relative_to(workdir))):
                changed.add(safe)

    return sorted(changed, key=lambda p: str(p.relative_to(workdir)))


def _append_html_artifacts(result: str, html_files: list[Path], workdir: Path) -> str:
    if not html_files:
        return result

    parts = [result.rstrip()] if result.strip() else []
    appended = 0
    for path in html_files[:_HTML_ARTIFACT_LIMIT]:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not content.strip() or content in result:
            continue
        if len(content.encode("utf-8")) > _HTML_ARTIFACT_MAX_BYTES:
            _log(Category.AGENT, "html artifact skipped", path=str(path.relative_to(workdir)), reason="too large")
            continue
        rel = path.relative_to(workdir)
        parts.append(f"Rendered HTML artifact from `{rel}`:\n\n```html\n{content}\n```")
        appended += 1

    omitted = len(html_files) - _HTML_ARTIFACT_LIMIT
    if omitted > 0:
        parts.append(f"{omitted} additional HTML artifact(s) omitted from preview.")
    if appended:
        _log(Category.AGENT, "html artifacts appended", count=appended)
    return "\n\n---\n\n".join(parts)


async def _recover_dirty_worktree(
    *,
    task: str,
    task_id: str,
    provider: str,
    ai: AiClient,
    thinking: ThinkingLevel,
    tools: list[Tool],
    instructions: str | None,
    workdir: Path,
) -> str:
    dirty = await _dirty_line(workdir)
    if not dirty:
        return ""

    _log(Category.AGENT, "dirty cleanup start", provider=provider, dirty=dirty)
    cleanup_task = f"""\
Your worktree still has uncommitted changes, so the manager cannot merge it yet.

Original user task:
{task}

Current dirty status starts with:
{dirty}

Do not do new feature work. Inspect git_status and git_diff. If the dirty changes
are intentional and satisfy the original request, stage and commit them with a
clear message. If they are accidental, remove only those accidental edits. End
with a brief summary.
"""
    result = await coder.run(
        cleanup_task,
        ai,
        instructions=instructions,
        thinking=thinking,
        tools=tools,
        workdir=workdir,
        agent_id=f"{task_id}:{provider}:cleanup",
        prior_history=transcript_load(task_id),
        hooks=[],
        hook_retries=0,
        max_turns=3,
        hook_policy=HookPolicy(check_referenced_html=False),
    )

    if still_dirty := await _dirty_line(workdir):
        _log(Category.AGENT, "dirty cleanup incomplete", provider=provider, dirty=still_dirty)
    else:
        _log(Category.AGENT, "dirty cleanup complete", provider=provider)
    return result


def _build_instructions(base: str, skill_bodies: str, skill_index: str, date_ctx: str) -> str | None:
    return "\n\n---\n\n".join(filter(None, [base, skill_bodies, skill_index, date_ctx])) or None


def _persist_generated_images(task_id: str, workdir: Path) -> None:
    """Keep generated image URLs serveable after the task worktree is cleaned up."""
    src = workdir / "generated" / "images" / task_id
    if not src.is_dir():
        return
    dest = REPO_ROOT / "generated" / "images" / task_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _prune_generated_images(max_age_days: int = 183) -> None:
    """Delete old local preview image directories; durable site images live in docs/."""
    root = REPO_ROOT / "generated" / "images"
    if not root.is_dir():
        return
    cutoff = time.time() - max_age_days * 24 * 60 * 60
    for task_dir in root.iterdir():
        if not task_dir.is_dir():
            continue
        try:
            newest = max((p.stat().st_mtime for p in task_dir.rglob("*") if p.is_file()), default=task_dir.stat().st_mtime)
        except OSError:
            continue
        if newest < cutoff:
            shutil.rmtree(task_dir, ignore_errors=True)


@dataclass(frozen=True)
class _Plan:
    """Everything the dispatcher needs once collected."""
    pre_loaded_paths: list[str]
    skill_bodies: str
    skill_index: str
    images: list[ImageContent]
    n_skill_images: int
    n_user_images: int
    date_ctx: str


def _gather_plan() -> _Plan:
    pre_loaded_paths = list(TASK_SKILLS_CTX.get() or [])
    skill_images = skills.collect_images(pre_loaded_paths)
    user_images = list(TASK_IMAGES_CTX.get() or [])
    return _Plan(
        pre_loaded_paths=pre_loaded_paths,
        skill_bodies=skills.join_bodies(pre_loaded_paths),
        skill_index=skills.index_for_prompt(pre_loaded=pre_loaded_paths),
        # User-uploaded images first (more task-specific), then skill inspirations.
        images=user_images + skill_images,
        n_skill_images=len(skill_images),
        n_user_images=len(user_images),
        date_ctx=date_context(),
    )


def _build_extra_hooks() -> tuple[list[Hook], int]:
    """Instantiate attached graders. Returns (extra_hooks, hook_retries).

    Returned list is passed via `coder.run(extra_hooks=...)` so it appends to
    DEFAULT_HOOKS — the universal lint / inline-html hooks always run alongside.
    Hook retries are the max of the grader budget (when graders are attached) and
    the universal default — a shared budget is fine because the grader is the
    expensive one and the linters don't usually fire on a sane response.
    """
    grader_paths = list(TASK_GRADERS_CTX.get() or [])
    if not grader_paths:
        return [], DEFAULT_HOOK_RETRIES
    grader_hooks: list[Hook] = []
    for p in grader_paths:
        try:
            grader_hooks.append(graders.instantiate(p))
        except ValueError as e:
            _log(Category.AGENT, "grader skipped", path=p, error=str(e)[:120])
    if not grader_hooks:
        return [], DEFAULT_HOOK_RETRIES
    return grader_hooks, max(GRADER_HOOK_RETRIES, DEFAULT_HOOK_RETRIES)


async def _route(task: str, pre_loaded_paths: list[str]) -> tuple[AiClient, ThinkingLevel, str]:
    """Pick (client, thinking, provider_name) via DispatchRouter for the manager → coder seam."""
    choice = await router.pick(router.RoutingRequest(
        task=task, tier=TIER_CTX.get(), seam="manager", skills=pre_loaded_paths,
    ))
    return router.make_client(choice, tier=TIER_CTX.get()), choice.thinking_level(), choice.provider


async def run(
    task: str,
    client: AiClient | None = None,
    *,
    clients: dict[str, AiClient] | None = None,  # accepted for back-compat; unused (router picks)
    orchestrator: AiClient | None = None,
    extra_tools: list[Tool] | None = None,
    use_coder_loop: bool = True,
    branch: str | None = None,
    parent_task_id: str | None = None,
    mode_override: TaskMode | str | None = None,
) -> str:
    """Plan + dispatch a task using user-attached skills and the DispatchRouter.

    `parent_task_id` (set by `@task_id` follow-ups) loads the parent's coder transcript
    and seeds the new loop so the model picks up where it left off.

    `mode_override` (set by scheduled tasks or future task overrides) skips the
    auto-classifier and forces the given mode. Accepts a TaskMode or a string.
    """
    del client, clients, branch  # silence unused — kept for back-compat

    plan = _gather_plan()
    if mode_override is not None:
        mode = TaskMode(mode_override) if not isinstance(mode_override, TaskMode) else mode_override
    else:
        mode = await _classify_mode(task, orchestrator)
    prior_history = transcript_load(parent_task_id) if parent_task_id else None
    if parent_task_id and prior_history is None:
        _log(Category.AGENT, "parent transcript missing", parent=parent_task_id)

    _log(
        Category.AGENT, "manager planned",
        mode=mode.value,
        pre_loaded=plan.pre_loaded_paths,
        skill_images=plan.n_skill_images,
        user_images=plan.n_user_images,
        total_skills=len(skills.discover()),
    )

    if not use_coder_loop:
        # Single-shot: no agent loop, just one model call.
        ai, thinking, _ = await _route(task, plan.pre_loaded_paths)
        return await ai.complete(
            task,
            instructions="\n\n---\n\n".join(filter(None, [plan.skill_bodies, plan.skill_index, plan.date_ctx])) or None,
            thinking=thinking,
            extra_tools=extra_tools or [],
        )

    return await _dispatch(task, mode, plan, extra_tools, prior_history, parent_task_id)


async def _resolve_parent_base(parent_task_id: str | None) -> str | None:
    """Return the parent's task branch if it still exists locally or on origin.

    A remote-only branch is still an active follow-up target; worktree.setup()
    recreates the local tracking branch before checking it out.
    """
    if not parent_task_id:
        return None
    branch = f"task/{parent_task_id}"
    await worktree.fetch_branch(branch)
    rc, _ = await worktree._git("rev-parse", "--verify", branch)
    if rc == 0:
        return branch
    rc, _ = await worktree._git("rev-parse", "--verify", f"origin/{branch}")
    return branch if rc == 0 else None


async def _dispatch(
    task: str,
    mode: TaskMode,
    plan: _Plan,
    extra_tools: list[Tool] | None,
    prior_history: dict | None = None,
    parent_task_id: str | None = None,
) -> str:
    """One coder dispatch. Mode chooses workspace (tmp vs worktree), tools, and base instructions."""
    task_id = current_task_id() or "task"

    # Route first — worktree.setup needs the provider name.
    ai, thinking, provider = await _route(task, plan.pre_loaded_paths)

    result = ""
    worktrees: list[worktree.Worktree] = []
    merge_results: dict[str, str] = {}
    reuse_parent_branch = False
    workdir_token = None
    workdir: Path | None = None
    start_head: str | None = None

    async with AsyncExitStack() as branch_stack:
        # Workspace setup based on mode.
        if mode == TaskMode.CONVERSATIONAL:
            workdir = _TMP_DIR / task_id
            workdir.mkdir(parents=True, exist_ok=True)
            tools = list(_CONVERSATIONAL_TOOLS) + list(extra_tools or [])
            instructions = _build_instructions(_CONVERSATIONAL_BASE, plan.skill_bodies, plan.skill_index, plan.date_ctx)
            base_branch = starting_ref = ""
            _log(Category.AGENT, "conversational dispatch",
                 provider=provider, model=ai.model_name, thinking=str(thinking),
                 tmp=str(workdir.relative_to(REPO_ROOT)), write_scope="workdir")
        else:
            parent_base = await _resolve_parent_base(parent_task_id)
            # Single-provider follow-up: extend the parent's task branch directly
            # (no inner task/<id>-<provider> branch, no fresh PR — push onto the existing one).
            reuse_parent_branch = bool(parent_base)
            if reuse_parent_branch and parent_base:
                await branch_stack.enter_async_context(worktree.branch_lock(parent_base, agent_id=f"{task_id}:follow-up"))
            if parent_task_id:
                parent_url = task_pr_url(parent_task_id)
                if reuse_parent_branch and parent_url:
                    PR_URL_CTX.set(parent_url)
                _log(Category.AGENT, "follow-up base",
                     parent=parent_task_id,
                     base_ref=parent_base or "default (parent branch reaped)",
                     reuse=reuse_parent_branch,
                     pr_url=parent_url)
            starting_ref, base_branch, worktrees = await worktree.setup(
                task_id, [provider], base_ref=parent_base,
                reuse_base_branch=reuse_parent_branch,
            )
            workdir = worktrees[0].path
            tools = list(_PERSISTENT_TOOLS) + list(extra_tools or [])
            git_skill = skills.join_bodies(["general/git.md"])
            persistent_bodies = "\n\n---\n\n".join(filter(None, [_MANAGED_GIT_INSTRUCTIONS, git_skill, plan.skill_bodies]))
            instructions = _build_instructions(_PERSISTENT_BASE, persistent_bodies, plan.skill_index, plan.date_ctx)
            _log(Category.AGENT, "dispatching",
                 provider=provider, model=ai.model_name, thinking=str(thinking),
                 write_scope="repo_worktree")

        assert workdir is not None
        if mode == TaskMode.PERSISTENT:
            rc, out = await worktree._git("rev-parse", "HEAD", cwd=workdir)
            start_head = out.strip() if rc == 0 and out.strip() else None
        workdir_token = WORKDIR.set(workdir)
        workdir_registry.register(task_id, workdir)
        success = False
        extra_hooks, hook_retries = _build_extra_hooks()
        hook_policy = _hook_policy(task)
        try:
            result = await coder.run(
                task, ai,
                instructions=instructions,
                thinking=thinking, tools=tools,
                workdir=workdir,
                agent_id=f"{task_id}:{provider}",
                images=plan.images,
                prior_history=prior_history,
                extra_hooks=extra_hooks,
                hook_retries=hook_retries,
                hook_policy=hook_policy,
            )
            if worktrees:
                cleanup_result = await _recover_dirty_worktree(
                    task=task,
                    task_id=task_id,
                    provider=provider,
                    ai=ai,
                    thinking=thinking,
                    tools=tools,
                    instructions=instructions,
                    workdir=workdir,
                )
                if cleanup_result:
                    result = f"{result}\n\n---\n\n{cleanup_result}"
                result = _append_html_artifacts(
                    result,
                    await _changed_html_files(workdir, start_head),
                    workdir,
                )
                merge_results = await worktree.merge(
                    task_id, base_branch, worktrees,
                    pr_base=starting_ref, pr_title=task[:70],
                    open_pr=not reuse_parent_branch,  # follow-ups extend the parent's PR;
                                                      # but if parent branch was reaped, fork gets its own PR
                )
            success = True
        finally:
            if mode == TaskMode.CONVERSATIONAL and success:
                result = _append_html_artifacts(
                    result,
                    await _changed_html_files(workdir, None),
                    workdir,
                )
            _persist_generated_images(task_id, workdir)
            _prune_generated_images()
            if workdir_token is not None:
                WORKDIR.reset(workdir_token)
            workdir_registry.unregister(task_id)
            if worktrees:
                await worktree.cleanup(worktrees)
            if mode == TaskMode.CONVERSATIONAL and success and CONVERSATIONAL_TMP_CLEANUP_ON_SUCCESS:
                shutil.rmtree(workdir, ignore_errors=True)
                _log(Category.AGENT, "conversational tmp cleaned", task_id=task_id)

    if worktrees:
        merge_status = merge_results.get(provider, "skipped")
        # Successful / harmless statuses (worktree.merge returns "no-op" with hyphen).
        if merge_status not in ("merged", "no-op", "skipped"):
            return f"## {provider}  [{merge_status}]\n{result}"
    return result
