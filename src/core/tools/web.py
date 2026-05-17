"""Web search tool — Exa-backed, routes through LibrarianAgent for dedup when available."""

import os

from core.ai_client.models import Tool
from core.text import text_stats
from core.tools.ctx import log_call
from core.tools.exa_search import ExaSearchTool


def make_web_search_tool(max_searches: int = 10) -> Tool | None:
    """Return a web_search Tool, or None if EXA_API_KEY is not set.

    Creates a fresh ExaSearchTool per call so each coder run gets its own
    budget counter. LibrarianAgent dedup is applied automatically via
    LIBRARIAN_CTX if set — results are cached in the shared vector DB."""
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        return None

    exa = ExaSearchTool(api_key=api_key, max_searches=max_searches)

    async def web_search(query: str) -> str:
        result = await exa(query)
        stats = text_stats(result)
        log_call("web_search", {"query": query[:80]}, f"OK: {stats['words']} words / {stats['tokens']} tokens")
        return result

    return Tool(
        name="web_search",
        description=(
            "Search the web for current facts, data, news, or recent events. "
            "Use whenever the task requires up-to-date information you are not certain about."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
        fn=web_search,
        is_read_only=True,
        is_concurrency_safe=True,
    )
