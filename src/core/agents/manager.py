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
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

from core.agents import coder, graders, router, skills, worktree
from core.agents.coder import _INSTRUCTIONS_BASE, _INSTRUCTIONS_PERSISTENT
from core.agents.grader import GRADER_HOOK_RETRIES
from core.agents.hooks import DEFAULT_HOOK_RETRIES, Hook
from core.agents.task_ctx import TASK_GRADERS_CTX, TASK_IMAGES_CTX, TASK_SKILLS_CTX, TIER_CTX, current_task_id
from core.ai_client import AiClient
from core.ai_client.models import ImageContent, ThinkingLevel, Tool
from core.log import Category
from core.log import log as _log
from core.log import transcript_load
from core.prompt import date_context
from core.tools.calc import CALC_TOOLS
from core.tools.ctx import REPO_ROOT, WORKDIR, WRITE_SCOPE
from core.tools.fs import FS_TOOLS
from core.tools.git import GIT_TOOLS
from core.tools.shell import SHELL_TOOLS


class TaskMode(StrEnum):
    CONVERSATIONAL = "conversational"  # Q&A, calc, explanations — answer is the deliverable
    PERSISTENT = "persistent"          # code/file changes that should be committed


CONVERSATIONAL_TMP_CLEANUP_ON_SUCCESS = False
_TMP_DIR = REPO_ROOT / "generated" / "tmp"
_PERSISTENT_TOOLS = FS_TOOLS + SHELL_TOOLS + GIT_TOOLS + CALC_TOOLS
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


def _build_instructions(base: str, skill_bodies: str, skill_index: str, date_ctx: str) -> str | None:
    return "\n\n---\n\n".join(filter(None, [base, skill_bodies, skill_index, date_ctx])) or None


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

    return await _dispatch(task, mode, plan, extra_tools, prior_history)


async def _dispatch(
    task: str,
    mode: TaskMode,
    plan: _Plan,
    extra_tools: list[Tool] | None,
    prior_history: dict | None = None,
) -> str:
    """One coder dispatch. Mode chooses workspace (tmp vs worktree), tools, and base instructions."""
    task_id = current_task_id() or "task"

    # Route first — worktree.setup needs the provider name.
    ai, thinking, provider = await _route(task, plan.pre_loaded_paths)

    # Workspace setup based on mode.
    if mode == TaskMode.CONVERSATIONAL:
        workdir = _TMP_DIR / task_id
        workdir.mkdir(parents=True, exist_ok=True)
        tools = list(_CONVERSATIONAL_TOOLS) + list(extra_tools or [])
        instructions = _build_instructions(_CONVERSATIONAL_BASE, plan.skill_bodies, plan.skill_index, plan.date_ctx)
        worktrees: list = []
        base_branch = starting_ref = ""
        write_scope: frozenset[str] | None = None
        _log(Category.AGENT, "conversational dispatch",
             provider=provider, model=ai.model_name, thinking=str(thinking),
             tmp=str(workdir.relative_to(REPO_ROOT)))
    else:
        starting_ref, base_branch, worktrees = await worktree.setup(task_id, [provider])
        workdir = worktrees[0].path
        tools = list(_PERSISTENT_TOOLS) + list(extra_tools or [])
        instructions = _build_instructions(_PERSISTENT_BASE, plan.skill_bodies, plan.skill_index, plan.date_ctx)
        write_scope = frozenset({"generated/", "knowledge/"})
        _log(Category.AGENT, "dispatching",
             provider=provider, model=ai.model_name, thinking=str(thinking))

    workdir_token = WORKDIR.set(workdir)
    scope_token = WRITE_SCOPE.set(write_scope) if write_scope else None
    success = False
    merge_results: dict[str, str] = {}
    extra_hooks, hook_retries = _build_extra_hooks()
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
        )
        if worktrees:
            merge_results = await worktree.merge(
                task_id, base_branch, worktrees, pr_base=starting_ref, pr_title=task[:70],
            )
        success = True
    finally:
        WORKDIR.reset(workdir_token)
        if scope_token is not None:
            WRITE_SCOPE.reset(scope_token)
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
