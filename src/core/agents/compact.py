"""Conversation history with token-aware auto-compaction.

Keeps the last N turns verbatim. When total tokens exceed the threshold,
asks the model to summarise everything older into a rolling summary.
The summary + recent turns are then fed as context for the next call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.ai_client import AiClient
from core.ai_client.models import ThinkingLevel
from core.log import Category
from core.log import log as _log
from core.log import stat_inc
from core.text import tokens as _count_tokens

_KEEP_RECENT = 6  # turns always kept verbatim after compaction

_COMPACT_INSTRUCTIONS = (
    "You are a context compactor. Given a conversation history and the original goal, "
    "produce a concise summary preserving: key decisions made, files written or changed, "
    "current task state, and what remains to be done. "
    "Output only the summary — no preamble, no markdown headers."
)


@dataclass
class Turn:
    role: str   # "user" | "assistant"
    content: str
    ts: float = field(default_factory=time.time)

    @property
    def tokens(self) -> int:
        return _count_tokens(self.content)


class ConversationHistory:
    """Manages a multi-turn conversation with automatic compaction.

    Args:
        goal:      The original task — included in every compaction prompt.
        window:    Model context window in tokens (default: 8192 for Gemma4).
        threshold: Fraction of window at which compaction triggers (default: 0.75).
    """

    def __init__(
        self,
        goal: str,
        window: int = 8_192,
        threshold: float = 0.75,
    ) -> None:
        self.goal = goal
        self._window = window
        self._threshold = threshold
        self._turns: list[Turn] = []
        self._summary: str | None = None

    # ------------------------------------------------------------------
    # Public API

    def add(self, role: str, content: str) -> None:
        self._turns.append(Turn(role=role, content=content))

    def snapshot(self) -> dict:
        """Serialisable snapshot — used to persist + replay the loop on follow-ups."""
        return {
            "goal":    self.goal,
            "summary": self._summary,
            "turns":   [{"role": t.role, "content": t.content, "ts": t.ts} for t in self._turns],
        }

    def load(self, snapshot: dict) -> None:
        """Restore state from snapshot. The original goal is preserved on this instance."""
        self._summary = snapshot.get("summary")
        self._turns = [
            Turn(role=t["role"], content=t["content"], ts=t.get("ts", time.time()))
            for t in snapshot.get("turns", [])
        ]

    @property
    def total_tokens(self) -> int:
        summary_tokens = _count_tokens(self._summary) if self._summary else 0
        return summary_tokens + sum(t.tokens for t in self._turns)

    def needs_compaction(self) -> bool:
        return self.total_tokens > self._window * self._threshold

    async def compact(self, client: AiClient) -> None:
        """Summarise old turns into a rolling summary, keep recent turns verbatim."""
        if len(self._turns) <= _KEEP_RECENT:
            return

        to_compact = self._turns[:-_KEEP_RECENT]
        self._turns = self._turns[-_KEEP_RECENT:]

        history_text = "\n".join(
            f"{t.role.upper()}: {t.content}" for t in to_compact
        )
        if self._summary:
            history_text = f"Previous summary:\n{self._summary}\n\n---\n\n{history_text}"

        turns_compacted = len(to_compact)
        _log(Category.COMPACT, "compacting", turns=turns_compacted, tokens_before=self.total_tokens)
        stat_inc("compact.events")

        self._summary = await client.complete(
            f"Goal: {self.goal}\n\nHistory to summarise:\n{history_text}",
            instructions=_COMPACT_INSTRUCTIONS,
            thinking=ThinkingLevel.LOW,
        )

        _log(Category.COMPACT, "done", turns_compacted=turns_compacted, summary_tokens=_count_tokens(self._summary))

    def build_prompt(self, user_input: str) -> str:
        """Assemble a single prompt string from summary + turns + new input."""
        parts: list[str] = []
        if self._summary:
            parts.append(f"[Context so far]\n{self._summary}")
        for t in self._turns:
            parts.append(f"{t.role.upper()}: {t.content}")
        parts.append(f"USER: {user_input}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Compact-then-build helper

    async def next_prompt(self, user_input: str, client: AiClient) -> str:
        """Auto-compact if needed, then return the prompt for the next LLM call."""
        if self.needs_compaction():
            await self.compact(client)
        return self.build_prompt(user_input)
