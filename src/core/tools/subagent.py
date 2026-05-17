"""SPAWN_TOOL — Tool wrapper for the spawn_subagent function.

Implementation lives in `core.agents.subagent.spawn_subagent`. It's split out because
`coder.py` needs to import this Tool, but the spawn implementation needs to call
`coder.run`. By keeping THIS file dependency-free at module import time and lazy-importing
the implementation inside the Tool's `fn`, the cycle is broken cleanly.
"""

from core.ai_client.models import Tool


async def _spawn(description: str, prompt: str, edit_mode: str = "read_only") -> str:
    # Lazy import — see module docstring for why.
    from core.agents.subagent import spawn_subagent
    return await spawn_subagent(description, prompt, edit_mode)


SPAWN_TOOL = Tool(
    name="spawn_subagent",
    description=(
        "Delegate bounded work to a fresh-context sub-agent. The sub-agent runs in isolation, "
        "uses tools, then returns a single summary string. Use for research, lookups, calculations, "
        "or self-contained analysis that would otherwise pollute your context. "
        "edit_mode='read_only' (default) shares your workdir but blocks writes — use for codebase research. "
        "edit_mode='conversational' gives a fresh tmp scratch dir with no git — use for Q&A/analysis. "
        "edit_mode='worktree' runs in its own git worktree branched from your HEAD; commits merge back. "
        "Make multiple calls in one turn for parallel sub-agents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short label for what the sub-agent does (1-5 words). Shown in logs/UI."},
            "prompt":      {"type": "string", "description": "The full task for the sub-agent. It starts with no context, so include all needed paths, requirements, and constraints."},
            "edit_mode":   {"type": "string", "enum": ["read_only", "conversational", "worktree"], "description": "Default read_only (shares your workdir, no writes). 'conversational' = fresh tmp scratch dir, no git. 'worktree' = own git worktree branched from your HEAD; commits merge back when sub-agent returns. Use worktree only for genuinely independent write work."},
        },
        "required": ["description", "prompt"],
    },
    fn=_spawn,
    is_read_only=False,
    is_concurrency_safe=True,
)
