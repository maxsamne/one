"""Coder agent — single agentic loop that executes a task using tools."""

from __future__ import annotations

from pathlib import Path

from core.agents.board import get_board
from core.agents.compact import ConversationHistory
from core.agents.hooks import DEFAULT_HOOK_RETRIES, DEFAULT_HOOKS, Hook, HookContext, run_hooks
from core.agents.ledger import Ledger
from core.agents.agent_ctx import AGENT_ID_CTX, CURRENT_TURN, ROLE_CTX, SPAWN_CTX, SUBAGENT_DEPTH, SpawnContext
from core.agents.task_ctx import current_task_id
from core.ai_client import AiClient
from core.ai_client.models import ImageContent, ThinkingLevel, Tool
from core.log import Category
from core.log import log as _log
from core.log import stat_inc, transcript_save
from core.tools.board import BOARD_POST_TOOL
from core.tools.ctx import PENDING_MULTIMODAL, READ_CTX, TOOL_LOG, WORKDIR
from core.tools.fs import FS_TOOLS
from core.tools.git import GIT_TOOLS, git_create_branch
from core.tools.shell import SHELL_TOOLS
from core.tools.image_gen import GENERATE_IMAGE_TOOL
from core.tools.skill_tool import LOAD_SKILL_TOOL
from core.tools.subagent import SPAWN_TOOL
from core.tools.todo import TODO_KEY, TODO_TOOL, all_complete, clear as clear_todos
from core.tools.visual_refs import LOAD_WEBSITE_IMAGE_REFS_TOOL
from core.tools.web import make_web_search_tool

from core.debug import trace as _dtrace


def _trace(agent_id: str, turn: int, kind: str, body: str) -> None:
    _dtrace(f"{agent_id} t{turn}", kind=f"{kind}: {body}")

_INSTRUCTIONS_BASE = """\
## General rules
- If the task requires current data, facts, or external information — call web_search first.
- If a task requires extensive data gathering before producing output (e.g. 3+ web searches, large file reads, broad codebase discovery), delegate the research/gathering phase to a conversational sub-agent first — have it collect and return a concise summary, then synthesise the output yourself. This keeps your context lean for generation.
- Before producing any visual or design-led output (HTML artifact, image-rich response, dashboard, briefing, article, page), scan the skill index above. If any skill looks relevant (e.g. `artifact-design`, `morning-brief`), call `load_skill(name)` BEFORE generating — those skills carry templates, palette, image-embedding syntax, and component patterns that the cheap-tier model otherwise misses.
- If a task asks you to match the visual style of an existing website/article, or to create a new article cover that fits previous articles, call `load_website_image_refs` BEFORE `generate_image`. This loads actual reference images only when needed, instead of spending image tokens on every task.
- When you emit image URLs returned by `generate_image` in a plain-text/markdown response (no HTML wrapper), ALWAYS use markdown image syntax `![alt](/images/<task>/<file>.png)` — never bare paths. Bare paths render as literal text and the user sees broken output. Inside an HTML block use `<img src="...">` instead.
- FATAL errors: stop and report clearly — do not retry.
- RETRYABLE errors: retry the operation (e.g. call read_file first, then edit_file).
- Never call an external API without first confirming it is safe and appropriate for the task.
- Prefer well-known, read-only public APIs (e.g. REST Countries, Wikipedia). Avoid any API that requires auth, sends data, or has side effects unless explicitly instructed.\
"""

_INSTRUCTIONS_PERSISTENT = """\
You are a coding agent working in a git repository.

## Output paths
Write outputs to the correct location — never pollute src/ with generated content:
- Research findings → knowledge/research/<topic-slug>.md
- Analysis / data outputs → knowledge/analysis/<name>.md
- Generated reports → generated/reports/YYYY-MM-DD-<name>.md
- Generated scripts / one-off code → generated/scripts/<name>.py
- Generated apps (new, built from scratch) → generated/apps/<platform>/<name>/
- Core engine changes → src/core/<module>/ — ONLY when the task explicitly modifies infrastructure
- Tests for repo code changes → tests/<name>.py
- Repo configuration changes → the existing config file (e.g. pyproject.toml, Taskfile.yml) — ONLY when explicitly requested
- Existing app changes → apps/<platform>/<name>/ — ONLY when the task explicitly targets an existing app

## Workflow
1. Work through the task — read_file before edit_file, make small focused commits.
2. After completing a logical chunk: git_add → git_commit with a clear message.
   Commit messages: imperative mood, ~50 chars (e.g. "Add RevenueCat paywall view").
3. If the task has 3 or more distinct steps, use todo_write to track them.
   Update each todo to in_progress when you start it, completed when done.

Never guess at file contents. Always read or grep before editing.

If the user explicitly asks for an inline/full HTML preview, include the complete
self-contained HTML document inside a ```html``` code block. Otherwise, for persistent
repo edits, commit the file changes and summarize the files/commit instead of pasting
large HTML documents into the final response.\
"""


async def run(
    task: str,
    client: AiClient,
    *,
    instructions: str | None = None,
    thinking: ThinkingLevel | None = ThinkingLevel.MEDIUM,
    tools: list[Tool] | None = None,
    branch: str | None = None,
    workdir: Path | None = None,
    max_turns: int = 30,
    ledger: Ledger | None = None,
    context_window: int = 128_000,
    agent_id: str | None = None,
    role: str = "default",
    images: list[ImageContent] | None = None,
    hooks: list[Hook] | None = None,
    extra_hooks: list[Hook] | None = None,
    hook_retries: int = DEFAULT_HOOK_RETRIES,
    prior_history: dict | None = None,
    include_default_tools: bool = True,
) -> str:
    """Run the coder loop for a task. Returns the final response.

    `extra_hooks` appends to DEFAULT_HOOKS — use this for GraderHook and other
    task-specific additions so lint/inline-html checks always run alongside them.

    `hooks` fully replaces DEFAULT_HOOKS — use only when you genuinely want to
    suppress the defaults (e.g. sub-agents that never emit HTML).

    `prior_history` (a `ConversationHistory.snapshot()` dict) seeds the loop with
    a previous task's transcript — used by `@task_id` follow-ups so the model picks
    up where the parent left off. Compaction kicks in naturally if context fills.
    """

    effective_tools = list(tools or (FS_TOOLS + SHELL_TOOLS + GIT_TOOLS))
    if include_default_tools:
        effective_tools += [TODO_TOOL, BOARD_POST_TOOL, LOAD_SKILL_TOOL, GENERATE_IMAGE_TOOL, LOAD_WEBSITE_IMAGE_REFS_TOOL]
        if web_tool := make_web_search_tool():
            effective_tools.append(web_tool)
        # Only top-level coders can spawn sub-agents (SUBAGENT_DEPTH=0). Sub-agents
        # cannot themselves spawn — keeps trees shallow and predictable for v1.
        if SUBAGENT_DEPTH.get() == 0:
            effective_tools.append(SPAWN_TOOL)
    effective_tools = _dedupe_tools(effective_tools)
    effective_instructions = "\n\n---\n\n".join(filter(None, [instructions, tools_prompt(effective_tools)]))
    effective_agent_id = agent_id or current_task_id() or "default"

    workdir_token = WORKDIR.set(workdir) if workdir else None

    if branch:
        result = await git_create_branch(branch)
        if result.startswith("FATAL"):
            _log(Category.AGENT, "branch failed", branch=branch, error=result)
            if workdir_token:
                WORKDIR.reset(workdir_token)
            return f"Failed to create branch {branch!r}: {result}"
        _log(Category.AGENT, "branch created", branch=branch)

    todo_token = TODO_KEY.set(effective_agent_id)
    clear_todos()
    reads_token = READ_CTX.set(set())
    log_token = TOOL_LOG.set([])
    pending_images_token = PENDING_MULTIMODAL.set([])
    role_token = ROLE_CTX.set(role)
    agent_id_token = AGENT_ID_CTX.set(effective_agent_id)
    spawn_token = SPAWN_CTX.set(SpawnContext(
        client=client,
        thinking=thinking,
        parent_workdir=workdir,
    ))

    board = get_board()
    task_id = current_task_id() or "default"
    last_seq_seen = 0

    history = ConversationHistory(goal=task, window=context_window)
    if prior_history:
        history.load(prior_history)
        _log(Category.AGENT, "coder resumed", agent=effective_agent_id,
             prior_turns=len(prior_history.get("turns", [])),
             prior_images=len(history.images))
    # Merge parent's images (from history) with this turn's new uploads (from kwarg).
    # Parent first so the model sees originals before follow-up references.
    merged = list(history.images) + [i for i in (images or []) if i not in history.images]
    images = merged
    history.images = list(merged)
    response = ""
    effective_hooks = (list(DEFAULT_HOOKS) + list(extra_hooks or [])) if hooks is None else hooks
    hook_retries_left = hook_retries
    hook_feedback: str | None = None  # if set, used as next turn's user input

    _log(Category.AGENT, "coder start", agent=effective_agent_id, task=task[:120], model=client.model_name, thinking=str(thinking) if thinking else None, provider=client.provider, max_turns=max_turns)
    stat_inc("coder.runs")

    try:
        for turn in range(max_turns):
            CURRENT_TURN.set(turn + 1)

            # Hook feedback (when set) takes priority — the previous response had
            # issues that the agent must address this turn.
            if hook_feedback:
                base_input = hook_feedback
                hook_feedback = None
            else:
                base_input = task if turn == 0 else "Continue."
            board_update = _format_board_update(board, task_id, role, last_seq_seen)
            if board_update:
                last_seq_seen = board.max_seq(task_id)
                user_input = f"{base_input}\n\n{board_update}"
            else:
                user_input = base_input

            history.add("user", user_input)
            prompt = await history.next_prompt(client)

            _log(Category.AGENT, "turn", ui=False, n=turn + 1,
                 tokens=history.total_tokens, window=context_window)
            _trace(effective_agent_id, turn + 1, "→ user", user_input)

            tools_before = len(TOOL_LOG.get())
            # Images attach to turn 0 only — model internalises them once, then iterates
            # text-only against its own descriptions in conversation history.
            turn_images = images if turn == 0 else None
            response = await client.complete(
                prompt,
                instructions=effective_instructions,
                thinking=thinking,
                extra_tools=effective_tools,
                images=turn_images,
            )
            new_tool_entries = TOOL_LOG.get()[tools_before:]
            if new_tool_entries:
                for entry in new_tool_entries:
                    summary = f"{entry.get('tool')}({entry.get('args')}) → {str(entry.get('result'))[:120]}"
                    _trace(effective_agent_id, turn + 1, "tool", summary)
            else:
                _trace(effective_agent_id, turn + 1, "tool", "(none)")

            history.add("assistant", response)
            _trace(effective_agent_id, turn + 1, "← assistant", response or "<empty>")
            if (tid := current_task_id()):
                transcript_save(tid, history.snapshot())

            if response or all_complete():
                # Run post-response hooks. If any flag issues AND we have retries left,
                # combine their feedback and run one more turn. Otherwise ship.
                if effective_hooks and hook_retries_left > 0 and response:
                    ctx = HookContext(
                        response=response, turn=turn + 1,
                        agent_id=effective_agent_id, role=role,
                    )
                    hook_feedback = await run_hooks(effective_hooks, ctx)
                    if hook_feedback:
                        hook_retries_left -= 1
                        _log(Category.AGENT, "hook retry",
                             retries_left=hook_retries_left, agent=effective_agent_id)
                        continue
                _log(Category.AGENT, "coder done", turns=turn + 1)
                stat_inc("coder.done")
                break
        else:
            _log(Category.AGENT, "coder timeout", max_turns=max_turns)
            stat_inc("coder.timeout")

    finally:
        READ_CTX.reset(reads_token)
        TOOL_LOG.reset(log_token)
        PENDING_MULTIMODAL.reset(pending_images_token)
        TODO_KEY.reset(todo_token)
        ROLE_CTX.reset(role_token)
        AGENT_ID_CTX.reset(agent_id_token)
        SPAWN_CTX.reset(spawn_token)
        if workdir_token:
            WORKDIR.reset(workdir_token)

    return response


def _format_board_update(board, task_id: str, role: str, since_seq: int) -> str:
    """Render new entries from other roles + open requests for this role.

    Returns "" when there's nothing to inject (e.g. single-loop tasks where the
    coder is the only writer)."""
    new_entries = board.read_since(task_id, role, since_seq)
    open_reqs = board.open_requests_for(task_id, role)
    if not new_entries and not open_reqs:
        return ""

    lines: list[str] = []
    if new_entries:
        lines.append("=== Board updates from other loops ===")
        for e in new_entries:
            tgt = f" → {e['target_role']}" if e['target_role'] else ""
            ref = f" (re: seq={e['responded_to_seq']})" if e['responded_to_seq'] else ""
            lines.append(f"[seq={e['seq']}, {e['role']}{tgt}, {e['kind']}]{ref} {e['payload']}")
    if open_reqs:
        lines.append("=== Open requests addressed to you ===")
        for r in open_reqs:
            lines.append(f"[seq={r['seq']}, from {r['from_role']}] {r['payload']}")
    return "\n".join(lines)


def _dedupe_tools(tools: list[Tool]) -> list[Tool]:
    seen: set[str] = set()
    out: list[Tool] = []
    for tool in tools:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        out.append(tool)
    return out




def tools_prompt(tools: list[Tool]) -> str:
    """Render a tool list into a system prompt section from each tool's name + description."""
    lines = ["## Available tools"]
    for t in tools:
        lines.append(f"- `{t.name}` — {t.description}")
    return "\n".join(lines)
