import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from exa_py import AsyncExa

from core.text import tokens as _count_tokens

logger = logging.getLogger(__name__)

_NUM_RESULTS = 8
_MAX_HIGHLIGHT_CHARS = 2_000
_MAX_WEB_SEARCH_OUTPUT_TOKENS = 10_000
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
    return json.dumps(_format_results(resp.results), ensure_ascii=False)


def _truncate_highlight(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return "[highlight omitted to fit web_search output budget]"
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    keep = max(0, max_chars - 32)
    return text[:keep].rstrip() + f" [...{omitted} chars truncated]"


def _apply_highlight_cap(items: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        highlights = item["highlights"]
        capped = [_truncate_highlight(h, max_chars) for h in highlights]
        out.append({**item, "highlights": capped})
    return out


def _format_results(
    results: list[Any],
    *,
    max_output_tokens: int = _MAX_WEB_SEARCH_OUTPUT_TOKENS,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for r in results:
        item: dict[str, Any] = {
            "title": getattr(r, "title", None),
            "url": getattr(r, "url", None),
            "highlights": [str(h) for h in (getattr(r, "highlights", None) or [])],
        }
        items.append(item)

    if _count_tokens(json.dumps(items, ensure_ascii=False)) <= max_output_tokens:
        return items

    longest = max((len(h) for item in items for h in item["highlights"]), default=0)
    lo, hi = 0, min(longest, _MAX_HIGHLIGHT_CHARS)
    best = _apply_highlight_cap(items, 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _apply_highlight_cap(items, mid)
        if _count_tokens(json.dumps(candidate, ensure_ascii=False)) <= max_output_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best
