"""Task-scoped ContextVars — set by the gateway on receipt, scoped to one /task request.

These vars carry information about *what the user asked for*. They live for the lifetime
of one task and are read by manager, router, coder, tools. Set/reset is done by the gateway
in `_run`. The asyncio.gather/create_task copy semantics propagate them automatically into
sub-coroutines (sub-agents, parallel coders), no manual plumbing needed.

For *agent-scoped* vars (per-coder/sub-agent identity, role, turn, depth), see `agent_ctx.py`.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    prompt: str = ""  # original user prompt — read by hooks that need to grade against it


# Identity — wraps task_id so log/UI can stamp every event with it.
TASK_CTX: ContextVar[TaskContext | None] = ContextVar("task_ctx", default=None)


def new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def current_task_id() -> str | None:
    ctx = TASK_CTX.get()
    return ctx.task_id if ctx else None


# User-selected pricing band: ultra_cheap | cheap | default | pro.
# DispatchRouter reads this to load the correct band of model options.
TIER_CTX: ContextVar[str] = ContextVar("tier_ctx", default="ultra_cheap")


# Skills the user explicitly attached (UI chips / `/skill` command). Manager pre-loads these
# bodies into the coder's instructions. Empty default → coder relies on the always-injected
# skills index + load_skill tool to pull anything else.
TASK_SKILLS_CTX: ContextVar[list[str]] = ContextVar("task_skills_ctx", default=[])


# Graders the user explicitly attached (UI chips). Manager calls `graders.instantiate(...)`
# for each path and prepends the resulting `GraderHook` instances to `DEFAULT_HOOKS` on
# `coder.run`. Empty default → only the universal linter hooks run.
TASK_GRADERS_CTX: ContextVar[list[str]] = ContextVar("task_graders_ctx", default=[])


# Optional git ref used by the grader to show what changed during a persistent task.
# The manager sets this to the worktree HEAD before the coder starts; conversational
# scratch workdirs leave it unset and the grader falls back to touched file contents.
GRADER_DIFF_BASE_CTX: ContextVar[str | None] = ContextVar("grader_diff_base_ctx", default=None)


# Images the user attached (drag-drop / upload). Manager merges these with skill `inspiration/`
# images and passes the union to the coder for turn-0 attachment.
# Typed as `list` to avoid an import of ImageContent here — gateway constructs, manager consumes.
TASK_IMAGES_CTX: ContextVar[list] = ContextVar("task_images_ctx", default=[])


# Mutable Exa-call counter — appended once per real Exa call (cache hits don't count).
# Set to a fresh list per task in server.py so counts don't bleed across tasks.
EXA_CALL_LOG: ContextVar[list[str]] = ContextVar("exa_call_log", default=[])


# Per-task LLM usage log: (model_name, input_tokens, output_tokens, cached_tokens) per call.
# cached_tokens is the subset of input_tokens that hit cache.
# Set to a fresh list per task in server.py. Read at task completion to compute cost.
# No default — calls outside a task context raise LookupError and are skipped by the appender,
# so scratch/REPL/test uses of clients don't accumulate into a shared module-level list.
TASK_USAGE_LOG: ContextVar[list[tuple[str, int, int, int]]] = ContextVar("task_usage_log")


# Set once when a draft PR is opened for a task; read by server.py after manager.run().
PR_URL_CTX: ContextVar[str | None] = ContextVar("pr_url_ctx", default=None)
