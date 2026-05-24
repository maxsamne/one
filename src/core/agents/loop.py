"""Reusable lightweight agent loop primitives.

This is intentionally smaller than `coder.run()`. The coder loop owns task-specific
state such as hooks, board updates, images, transcripts, todos, and write-capable
workflow conventions. This module is for focused sub-workflows that need the same
core rhythm: add input, auto-compact, call a model with a fixed tool set, optionally
parse a structured result, and continue if the result is not ready.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from core.agents.compact import ConversationHistory
from core.ai_client.interface import AiClient
from core.ai_client.models import ThinkingLevel, Tool
from core.log import Category
from core.log import log as _log

T = TypeVar("T")


@dataclass
class AgentLoopResult(Generic[T]):
    value: T | None
    last_response: str
    turns: int
    completed: bool


def default_turn_input(goal: str, turn: int) -> str:
    return goal if turn == 0 else "Continue."


async def run_agent_loop(
    *,
    goal: str,
    client: AiClient,
    instructions: str,
    tools: list[Tool],
    thinking: ThinkingLevel | None = ThinkingLevel.LOW,
    max_turns: int = 8,
    context_window: int = 128_000,
    compact_instructions: str | None = None,
    turn_input: Callable[[str, int], str] = default_turn_input,
    parse_response: Callable[[str], T] | None = None,
    retry_parse_exceptions: tuple[type[Exception], ...] = (ValueError,),
    log_label: str = "agent loop",
) -> AgentLoopResult[T]:
    history = ConversationHistory(
        goal=goal,
        window=context_window,
        compact_instructions=compact_instructions,
    )
    last_response = ""

    for turn in range(max_turns):
        history.add("user", turn_input(goal, turn))
        prompt = await history.next_prompt(client)
        last_response = await client.complete(
            prompt,
            instructions=instructions,
            thinking=thinking,
            extra_tools=tools,
        )
        history.add("assistant", last_response)

        if parse_response is None:
            _log(Category.AGENT, log_label, turns=turn + 1, completed=True)
            return AgentLoopResult(
                value=None,
                last_response=last_response,
                turns=turn + 1,
                completed=True,
            )

        try:
            value = parse_response(last_response)
        except retry_parse_exceptions:
            continue

        _log(Category.AGENT, log_label, turns=turn + 1, completed=True)
        return AgentLoopResult(
            value=value,
            last_response=last_response,
            turns=turn + 1,
            completed=True,
        )

    _log(Category.AGENT, log_label, turns=max_turns, completed=False)
    return AgentLoopResult(
        value=None,
        last_response=last_response,
        turns=max_turns,
        completed=False,
    )
