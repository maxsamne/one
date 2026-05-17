import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from exa_py import AsyncExa

logger = logging.getLogger(__name__)

_NUM_RESULTS = 8
_MAX_HIGHLIGHT_CHARS = 2_000
_LOW_BUDGET_WARNING = 5


class ExaSearchTool:
    """Async-callable Exa search wrapper with per-instance budget and librarian gate."""

    def __init__(self, api_key: str, max_searches: int = 10) -> None:
        self._exa = AsyncExa(api_key=api_key)
        self.max_searches = max_searches
        self._count = 0

    @property
    def searches_used(self) -> int:
        return self._count

    def budget_instruction(self) -> str:
        return f"You have {self.max_searches} web searches available. Plan them strategically."

    async def __call__(self, query: str) -> str:
        from core.tools.librarian import LIBRARIAN_CTX

        librarian = LIBRARIAN_CTX.get()
        if librarian is not None:
            return await librarian.route(query, self._raw_call)
        return await self._raw_call(query)

    async def _raw_call(self, query: str) -> str:
        from core.agents.task_ctx import EXA_CALL_LOG
        if self._count >= self.max_searches:
            return "No more web searches available. Answer based on what you already know."

        self._count += 1
        EXA_CALL_LOG.get().append(query)
        remaining = self.max_searches - self._count
        logger.info("Exa search %d/%d: %r", self._count, self.max_searches, query)

        try:
            result = await _call_exa(self._exa, query)
        except Exception as e:
            logger.warning("Exa search failed: %s", e)
            result = f"Search failed: {e}"

        if 0 < remaining < _LOW_BUDGET_WARNING:
            result += f"\n\n[{remaining} search(es) remaining — plan carefully.]"

        return result


WebSearchFallback = Callable[[str], Coroutine[Any, Any, str]]


def with_budget(instructions: str | None, tool: ExaSearchTool) -> str:
    """Prepend/append the search budget line to a system prompt."""
    budget_line = tool.budget_instruction()
    return f"{instructions}\n\n{budget_line}" if instructions else budget_line


async def _call_exa(exa: AsyncExa, query: str) -> str:
    resp = await exa.search(
        query,
        num_results=_NUM_RESULTS,
        contents={"highlights": {"max_characters": _MAX_HIGHLIGHT_CHARS}},
    )
    return json.dumps(
        [{"title": r.title, "url": r.url, "highlights": r.highlights or []} for r in resp.results]
    )
