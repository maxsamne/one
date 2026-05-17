"""Hooks: HTML lint catches the markdown-leak bug class; clean HTML passes through."""

from core.agents.hooks import HookContext, HtmlLintHook, run_hooks


_DIRTY_HTML = """```html
<!doctype html>
<html><body>
  <p>Source: [Bloomberg](https://www.bloomberg.com/news/articles/2026-05-10/some-very-long-slug-that-overflows)</p>
  <p>**emphatic**: visit https://www.example.com/some/very/long/path/that/will/overflow for details.</p>
</body></html>
```"""

_CLEAN_HTML = """```html
<!doctype html>
<html><body>
  <p>Source: <a href="https://www.bloomberg.com/long/url">Bloomberg</a></p>
  <p><strong>emphatic</strong>: more in the <a href="https://example.com">docs</a>.</p>
</body></html>
```"""


async def test_html_lint_catches_markdown_leak_bare_url_and_bold():
    fb = await HtmlLintHook().check(HookContext(response=_DIRTY_HTML, turn=1, agent_id="t", role="r"))
    assert fb is not None
    assert "markdown-link" in fb and "markdown-bold" in fb and "bare-url" in fb


async def test_html_lint_passes_clean_html_through():
    fb = await HtmlLintHook().check(HookContext(response=_CLEAN_HTML, turn=1, agent_id="t", role="r"))
    assert fb is None


async def test_run_hooks_combines_feedback_and_skips_clean_ones():
    # Two hooks: a clean stub + the real lint on dirty html. Combined output must
    # include the lint feedback and skip the clean stub silently.
    class _CleanStub:
        name = "stub-clean"
        async def check(self, ctx): return None
    out = await run_hooks([_CleanStub(), HtmlLintHook()],
                          HookContext(response=_DIRTY_HTML, turn=1, agent_id="t", role="r"))
    assert out is not None and "html-lint" in out and "stub-clean" not in out


async def test_broken_image_hook_fires_on_empty_src_and_passes_on_real_src():
    from core.agents.hooks import BrokenImageHook
    h = BrokenImageHook()
    ctx = lambda r: HookContext(response=r, turn=1, agent_id="t", role="r")

    broken_empty  = '```html\n<html><body><img src="" alt="hero"></body></html>\n```'
    broken_none   = '```html\n<html><body><img alt="hero"></body></html>\n```'
    broken_space  = '```html\n<html><body><img src="   " alt="hero"></body></html>\n```'
    good          = '```html\n<html><body><img src="/images/abc/1-hero.png" alt="hero"></body></html>\n```'
    no_html       = "Here is the result with no html block."

    assert await h.check(ctx(broken_empty)) is not None
    assert await h.check(ctx(broken_none))  is not None
    assert await h.check(ctx(broken_space)) is not None
    assert await h.check(ctx(good))         is None
    assert await h.check(ctx(no_html))      is None


async def test_missing_inline_html_fires_when_path_mentioned_but_no_block():
    from core.agents.hooks import MissingInlineHtmlHook
    h = MissingInlineHtmlHook()
    # Mentions the file path, no ```html``` block → should fire.
    bad = "Done — I wrote `generated/reports/2026-05-10-week-ahead-briefing.html`. The file is committed."
    assert await h.check(HookContext(response=bad, turn=1, agent_id="t", role="r")) is not None
    # Pure conversational answer, no .html mention → silent.
    plain = "The capital of France is Paris."
    assert await h.check(HookContext(response=plain, turn=1, agent_id="t", role="r")) is None
    # File mentioned AND inline block present → silent.
    good = bad + "\n\n```html\n<!doctype html><html><body>x</body></html>\n```"
    assert await h.check(HookContext(response=good, turn=1, agent_id="t", role="r")) is None
    # News URLs ending in .html in body text must NOT trigger the hook —
    # research summaries cite sources like techcrunch.com/article.html all the time.
    cite = "Source: https://techcrunch.com/2026/05/10/some-startup-raised.html and eu-startups.com/post.html."
    assert await h.check(HookContext(response=cite, turn=1, agent_id="t", role="r")) is None
