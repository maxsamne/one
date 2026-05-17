"""Post-response hooks — pluggable checks that fire when the coder's loop is about to end.

Each hook gets a final response (model returned text, didn't call any tools — i.e.
the deliverable). It returns either:
  - None → clean, hook is happy
  - a str → feedback to the agent. The coder loop runs ONE more turn with the
    combined feedback as the next user message.

If multiple hooks return feedback, they're concatenated. The agent sees all issues
at once and fixes them in a single retry — cheaper than one-hook-at-a-time loops.

A shared retry budget (default 2) caps how many fix-up turns can happen before the
coder ships the response anyway. This prevents stubborn models / impossible-to-fix
issues from looping forever.

Pattern: "reflexion loop" / "validator-in-the-loop". See coder.py for the wiring.

Adding a new hook:
1. Subclass `Hook`, implement `check(ctx)`.
2. Append to `DEFAULT_HOOKS` (or pass a custom list to `coder.run`).
3. Add a sharp pytest test for the rule it enforces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import re

from core.agents.lint import extract_html_block, format_feedback, lint_html
from core.log import Category
from core.log import log as _log


@dataclass(frozen=True)
class HookContext:
    """Inputs every hook sees. Add fields here as more hooks need more context."""
    response: str
    turn: int            # 1-based turn number that produced the response
    agent_id: str
    role: str


class Hook(ABC):
    """A single deterministic check on the agent's final response."""
    name: str = "unnamed-hook"

    @abstractmethod
    async def check(self, ctx: HookContext) -> str | None:
        """Return feedback text if the response needs another turn, else None."""
        ...


# --- Built-in hooks --------------------------------------------------------

class HtmlLintHook(Hook):
    """Catches markdown leaks, bare URLs, and other common HTML hygiene issues
    in any ```html``` block the agent emits. Cheap (regex) — runs zero LLM calls."""
    name = "html-lint"

    async def check(self, ctx: HookContext) -> str | None:
        html = extract_html_block(ctx.response)
        if not html:
            return None
        issues = lint_html(html)
        if not issues:
            return None
        return format_feedback(issues)


# Detects responses that say "I wrote `path/to/foo.html`" but never include the
# ```html``` block inline. The chat iframe + persisted /artifacts/ pipeline both
# need the inline block — without it the user can't open the artifact at all.
#
# Match a backtick-wrapped relative path ending in .html. The leading backtick
# is intentional — it excludes URLs in body text (e.g. "techcrunch.com/x.html")
# which would otherwise trip this on any response that cites a news source.
_HTML_PATH_RE = re.compile(r"`(?!https?://)[\w./\-]+\.html`")


class MissingInlineHtmlHook(Hook):
    """If the response references writing an HTML file but doesn't include the
    full document inline as a ```html``` block, ask the agent to paste it."""
    name = "missing-inline-html"

    async def check(self, ctx: HookContext) -> str | None:
        if extract_html_block(ctx.response) is not None:
            return None  # inline block present, nothing to do
        if not _HTML_PATH_RE.search(ctx.response):
            return None  # response doesn't claim to have written an html file
        return (
            "Your response references writing an HTML file but does not include the "
            "document inline. The chat iframe and the open-in-tab link both need the "
            "full HTML to render — paste the complete file contents inside a ```html``` "
            "block as your final output. Do not summarize or describe — emit the full "
            "document."
        )


# Matches <img> tags with an empty, whitespace-only, or missing src attribute.
_BROKEN_IMG_RE = re.compile(
    r'<img\b(?![^>]*\bsrc=["\'][^"\'\s][^"\']*["\'])[^>]*/?>',
    re.IGNORECASE,
)


class BrokenImageHook(Hook):
    """Catches <img> tags with empty or missing src in the HTML block and asks
    the agent to call generate_image() and fill them in. Zero LLM cost."""
    name = "broken-image"

    async def check(self, ctx: HookContext) -> str | None:
        html = extract_html_block(ctx.response)
        if not html:
            return None
        if not _BROKEN_IMG_RE.search(html):
            return None
        return (
            "Your HTML contains one or more <img> tags with an empty or missing src. "
            "Either call `generate_image(prompt)` and replace the src with the returned path, "
            "or remove the broken <img> tag entirely if no image is needed."
        )


# Registered hooks run in this order on every loop-end. Override via coder.run(hooks=...).
DEFAULT_HOOKS: list[Hook] = [
    MissingInlineHtmlHook(),  # cheapest first — runs before HtmlLintHook so the
    HtmlLintHook(),           # lint can actually see content
    BrokenImageHook(),
]


# --- Runner ----------------------------------------------------------------

DEFAULT_HOOK_RETRIES = 2


async def run_hooks(hooks: list[Hook], ctx: HookContext) -> str | None:
    """Run all hooks, combine feedback. Returns None if every hook is clean."""
    feedbacks: list[str] = []
    for hook in hooks:
        try:
            fb = await hook.check(ctx)
        except Exception as e:
            _log(Category.AGENT, "hook crashed", hook=hook.name, error=str(e)[:200])
            continue
        if fb:
            _log(Category.AGENT, "hook fired", hook=hook.name, agent=ctx.agent_id, turn=ctx.turn)
            feedbacks.append(f"### {hook.name}\n\n{fb}")
    if not feedbacks:
        return None
    return "\n\n---\n\n".join(feedbacks)
