"""Agent-scoped ContextVars — per-coder identity, role, turn, sub-agent depth.

Set/reset by `coder.run` (top-level + sub-agents). Inherited automatically by tools called
inside the coder loop, by the board (which reads role + turn), and by the log (which stamps
agent_id on every event).

For *task-scoped* vars (set by the gateway, lifetime of one /task request), see `task_ctx.py`.
"""

from contextvars import ContextVar
from dataclasses import dataclass


# Short role label — set by coder.run, used by board entries and log events.
ROLE_CTX: ContextVar[str] = ContextVar("role_ctx", default="default")


# Current turn number within this coder loop — written deterministically into board entries.
CURRENT_TURN: ContextVar[int] = ContextVar("current_turn", default=0)


# Stable per-coder identifier (`<task_id>:<provider>` or `<task_id>:sub-<id>`). Auto-injected
# into every log event by core.log so the UI can group events into per-agent rows.
AGENT_ID_CTX: ContextVar[str | None] = ContextVar("agent_id_ctx", default=None)


@dataclass(frozen=True)
class SpawnContext:
    """Inherited by spawn_subagent — what a sub-agent gets from its parent.

    `client` and `thinking` are kept for fallback only — sub-agents normally get a
    fresh router pick at the spawn seam (see core.agents.router).
    """
    client: object               # AiClient — typed Any to avoid import cycle
    thinking: object | None      # ThinkingLevel | None
    parent_workdir: object       # Path | None — sub-agent in read_only mode shares this


# Set by coder.run; read by spawn_subagent at the spawn seam.
SPAWN_CTX: ContextVar[SpawnContext | None] = ContextVar("spawn_ctx", default=None)


# Caps sub-agent nesting at 2 levels (parent → sub → sub-sub is max). Sub-agents at depth=1
# don't get the spawn tool — keeps trees shallow and predictable.
SUBAGENT_DEPTH: ContextVar[int] = ContextVar("subagent_depth", default=0)
