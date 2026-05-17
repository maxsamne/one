"""Sub-agent orchestration — three edit modes, router-picked model per spawn.

This module owns the full spawn logic. The Tool wrapper that exposes it to the LLM lives
at `core.tools.subagent.SPAWN_TOOL` (which lazy-imports `spawn_subagent` to break the
inevitable coder ↔ subagent cycle: coder needs the tool, the tool needs to call coder).

Three modes:
- read_only:    sub-agent shares parent's WORKDIR, write tools stripped. For research/lookup.
- conversational: sub-agent gets a fresh tmp scratch dir, no git. For Q&A/analysis.
- worktree:     sub-agent gets its own git worktree branched from parent's HEAD, merges back on success.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from core.agents import coder, router, worktree as worktree_mod
from core.agents.worktree import WORKTREE_DIR
from core.agents.agent_ctx import ROLE_CTX, SPAWN_CTX, SUBAGENT_DEPTH
from core.agents.task_ctx import TIER_CTX, current_task_id
from core.log import Category
from core.log import log as _log
from core.tools.board import BOARD_POST_TOOL
from core.tools.calc import CALC_TOOLS
from core.tools.ctx import REPO_ROOT, WORKDIR
from core.tools.fs import FS_TOOLS
from core.tools.git import GIT_TOOLS
from core.tools.image_gen import GENERATE_IMAGE_TOOL
from core.tools.shell import SHELL_TOOLS
from core.tools.skill_tool import LOAD_SKILL_TOOL
from core.tools.todo import TODO_TOOL
from core.tools.web import make_web_search_tool

_TMP_DIR = REPO_ROOT / "generated" / "tmp"
_MAX_DEPTH = 2  # parent → sub-agent → sub-sub-agent. Beyond this, refuse.

_READ_ONLY_TOOL_NAMES = frozenset({
    "read_file", "grep_file", "list_dir",
    "git_status", "git_diff", "git_log",
    "web_search", "calculate", "months_between",
    "todo_write", "board_post", "load_skill",
})

_CONVERSATIONAL_TOOL_NAMES = frozenset({
    "read_file", "write_file", "edit_file", "grep_file", "list_dir", "delete_file",
    "calculate", "months_between",
    "todo_write", "board_post", "load_skill", "web_search", "generate_image",
})


def _validate_tool_names() -> None:
    """Fail loudly at import if a name in the sets above no longer matches a real tool.

    Catches the silent-break path where a tool is renamed in fs.py / git.py / etc.
    and the sub-agent filter quietly drops it. (We can't derive these sets from
    `is_read_only` because TODO_TOOL/BOARD_POST_TOOL write to per-agent state but
    are still safe in read-only sub-agents.)
    """
    # web_search is registered only when EXA_API_KEY is set — treat as known regardless.
    known = {t.name for t in _base_tool_set()} | {"web_search"}
    for label, names in (("_READ_ONLY_TOOL_NAMES", _READ_ONLY_TOOL_NAMES),
                         ("_CONVERSATIONAL_TOOL_NAMES", _CONVERSATIONAL_TOOL_NAMES)):
        unknown = names - known
        if unknown:
            raise RuntimeError(
                f"subagent.{label} references tools that no longer exist: {sorted(unknown)}. "
                f"A tool was likely renamed — update the set or the tool name."
            )


_READ_ONLY_INSTRUCTIONS = """\
You are a sub-agent with READ-ONLY access to the codebase. You cannot write, edit, delete, or commit.
Your job is to investigate and report back. Read files, grep, list dirs, search the web — then return a concise summary.

Your return value is the only thing your parent will see. Be specific:
- Cite file paths and line numbers (file.py:42)
- Quote exact strings/snippets that matter
- Lead with the answer, then the supporting evidence

Do not narrate your search process. The parent doesn't need to know which files you read — only what you found.
If you cannot answer with read-only tools, say so explicitly: "Need write access to do X — re-spawn me as worktree."\
"""

_CONVERSATIONAL_INSTRUCTIONS = """\
You are a conversational sub-agent. You have a sandboxed scratch directory for any temporary files
(intermediate scripts, calculations, notes) and basic file/calc tools — but no git and no shell.
Nothing you write here is kept; the directory is wiped after you return.

Your return value is the only thing your parent will see. Be concise and direct.\
"""


_WORKTREE_INSTRUCTIONS = """\
You are a write-capable sub-agent running in your own isolated git worktree.
Anything you commit here will be merged back into your parent's branch when you return.

Workflow:
1. Make focused edits — read_file before edit_file.
2. git_add → git_commit when a logical chunk is done. Commit messages: imperative, ~50 chars.
3. Return a concise summary describing WHAT you built and WHERE (file paths). The merge result
   will be appended to your return value automatically.

Keep your scope tight — your parent delegated this for a reason. Do not wander into unrelated changes.\
"""


def _base_tool_set() -> list:
    base = list(FS_TOOLS) + list(SHELL_TOOLS) + list(GIT_TOOLS) + list(CALC_TOOLS) + [
        TODO_TOOL, BOARD_POST_TOOL, LOAD_SKILL_TOOL, GENERATE_IMAGE_TOOL,
    ]
    if web := make_web_search_tool():
        base.append(web)
    return base


_validate_tool_names()


async def _setup_workspace(edit_mode: str, task_id: str, sub_id: str):
    """Returns (workdir, allowed_tool_names_or_None, instructions, sub_worktree, cleanup_dir)."""
    if edit_mode == "read_only":
        return WORKDIR.get(), _READ_ONLY_TOOL_NAMES, _READ_ONLY_INSTRUCTIONS, None, None
    if edit_mode == "conversational":
        sub_workdir = _TMP_DIR / task_id / f"sub-{sub_id}"
        sub_workdir.mkdir(parents=True, exist_ok=True)
        return sub_workdir, _CONVERSATIONAL_TOOL_NAMES, _CONVERSATIONAL_INSTRUCTIONS, None, sub_workdir
    # worktree
    parent_workdir = WORKDIR.get()
    if not parent_workdir or WORKTREE_DIR not in parent_workdir.parents:
        raise ValueError(
            "edit_mode='worktree' requires the parent coder to be running in a git worktree. "
            "This usually means the top-level task is conversational — use edit_mode='conversational' "
            "or 'read_only' instead."
        )
    sub_worktree = await worktree_mod.setup_subagent_worktree(task_id, sub_id, parent_workdir)
    return sub_worktree.path, None, _WORKTREE_INSTRUCTIONS, sub_worktree, None


async def _route_subagent(prompt: str, description: str, edit_mode: str, sub_agent_id: str):
    """Pick (client, thinking) for the sub-agent via DispatchRouter. Falls back to parent's."""
    spawn = SPAWN_CTX.get()
    try:
        choice = await router.pick(router.RoutingRequest(
            task=prompt,
            tier=TIER_CTX.get(),
            seam="subagent",
            edit_mode=edit_mode,
            parent_intent=description,
            parent_role=ROLE_CTX.get(),
        ))
        client = router.make_client(choice, tier=TIER_CTX.get())
        _log(Category.AGENT, "subagent routed",
             agent=sub_agent_id, provider=choice.provider, model=choice.model, thinking=choice.thinking)
        return client, choice.thinking_level()
    except Exception as e:
        _log(Category.AGENT, "subagent router fallback", agent=sub_agent_id, error=str(e)[:200])
        return spawn.client, spawn.thinking


async def spawn_subagent(description: str, prompt: str, edit_mode: str = "read_only") -> str:
    """Run a sub-agent in one of three modes. Returns its final string output."""
    if edit_mode not in ("read_only", "conversational", "worktree"):
        return f"FATAL: invalid edit_mode {edit_mode!r}. Must be: read_only | conversational | worktree"

    depth = SUBAGENT_DEPTH.get()
    if depth >= _MAX_DEPTH:
        return f"FATAL: max sub-agent depth ({_MAX_DEPTH}) exceeded. Cannot nest further."

    if SPAWN_CTX.get() is None:
        return "FATAL: no spawn context — spawn_subagent called outside a coder session"

    task_id = current_task_id() or "task"
    sub_id = uuid.uuid4().hex[:6]
    sub_agent_id = f"{task_id}:sub-{sub_id}"
    sub_role = f"sub-{sub_id}-{description[:20].replace(' ', '_')}"

    try:
        sub_workdir, allowed, instructions, sub_worktree, cleanup_dir = await _setup_workspace(
            edit_mode, task_id, sub_id,
        )
    except (ValueError, RuntimeError) as e:
        return f"FATAL: {e}"

    base_tools = _base_tool_set()
    sub_tools = base_tools if allowed is None else [t for t in base_tools if t.name in allowed]

    _log(
        Category.AGENT, "subagent spawn",
        parent=task_id, agent=sub_agent_id,
        description=description[:120], edit_mode=edit_mode, depth=depth + 1,
    )

    sub_client, sub_thinking = await _route_subagent(prompt, description, edit_mode, sub_agent_id)

    depth_token = SUBAGENT_DEPTH.set(depth + 1)
    merge_status: str | None = None
    try:
        result = await coder.run(
            prompt, sub_client,
            instructions=instructions, thinking=sub_thinking,
            tools=sub_tools, workdir=sub_workdir,
            agent_id=sub_agent_id, role=sub_role,
            max_turns=15,  # sub-agents should be short — half the parent's budget
            hooks=[],      # sub-agents return text/research; the parent owns artifact emission
        )
        if sub_worktree is not None:
            merge_status = await worktree_mod.merge_subagent_worktree(task_id, sub_worktree, WORKDIR.get())
    finally:
        SUBAGENT_DEPTH.reset(depth_token)
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        if sub_worktree is not None:
            await worktree_mod.cleanup_subagent_worktree(sub_worktree)

    _log(Category.AGENT, "subagent done", agent=sub_agent_id, chars=len(result or ""), merge=merge_status)
    body = result or "(no response)"
    if merge_status:
        body = f"{body}\n\n[merge: {merge_status}]"
    return body
