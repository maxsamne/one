"""Hooks: HTML lint catches the markdown-leak bug class; clean HTML passes through."""

import subprocess

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


async def test_missing_image_file_hook_flags_dead_srcs_and_passes_real_ones(tmp_path):
    from core.agents.hooks import MissingImageFileHook
    from core.tools.ctx import WORKDIR

    (tmp_path / "docs" / "images").mkdir(parents=True)
    (tmp_path / "docs" / "images" / "hero.png").write_bytes(b"\x89PNG-real")
    (tmp_path / "generated" / "images" / "tid").mkdir(parents=True)
    (tmp_path / "generated" / "images" / "tid" / "1-cover.png").write_bytes(b"\x89PNG-gen")

    h = MissingImageFileHook()
    ctx = lambda r: HookContext(response=r, turn=1, agent_id="t", role="r")

    real_relative   = '```html\n<html><body><img src="images/hero.png"></body></html>\n```'
    real_one_prefix = '```html\n<html><body><img src="/one/images/hero.png"></body></html>\n```'
    real_gen_url    = '```html\n<html><body><img src="/images/tid/1-cover.png"></body></html>\n```'
    remote_ok       = '```html\n<html><body><img src="https://example.com/x.png"><img src="data:image/png;base64,AAA"></body></html>\n```'
    remote_case_ok  = '```html\n<html><body><img src="HTTPS://example.com/x.png"><img src="//cdn.example.com/x.png"></body></html>\n```'
    query_ok        = '```html\n<html><body><img src="images/hero.png?v=1#hero"></body></html>\n```'
    traversal_bad   = '```html\n<html><body><img src="../outside.png"></body></html>\n```'
    missing         = '```html\n<html><body><img src="/one/images/nope.png"><img src="images/also-fake.png"></body></html>\n```'
    no_html         = "Plain answer with no html block."
    (tmp_path.parent / "outside.png").write_bytes(b"\x89PNG-outside")

    tok = WORKDIR.set(tmp_path)
    try:
        assert await h.check(ctx(real_relative))   is None
        assert await h.check(ctx(real_one_prefix)) is None
        assert await h.check(ctx(real_gen_url))    is None
        assert await h.check(ctx(remote_ok))       is None
        assert await h.check(ctx(remote_case_ok))  is None
        assert await h.check(ctx(query_ok))        is None
        assert await h.check(ctx(no_html))         is None
        assert "../outside.png" in (await h.check(ctx(traversal_bad)) or "")
        fb = await h.check(ctx(missing))
        assert fb is not None
        assert "/one/images/nope.png" in fb and "images/also-fake.png" in fb
    finally:
        WORKDIR.reset(tok)


async def test_docs_static_image_hook_rejects_gateway_images_in_docs(tmp_path):
    from core.agents.hooks import DocsStaticImageHook
    from core.tools.ctx import WORKDIR

    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=tmp_path)
    subprocess.check_call(["git", "config", "user.email", "t@t.t"], cwd=tmp_path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=tmp_path)

    docs = tmp_path / "docs"
    (docs / "images").mkdir(parents=True)
    (docs / "images" / "hero.png").write_bytes(b"\x89PNG-docs")
    (tmp_path / "generated" / "images" / "tid").mkdir(parents=True)
    (tmp_path / "generated" / "images" / "tid" / "1-hero.png").write_bytes(b"\x89PNG-local")
    (docs / "legacy.html").write_text('<img src="/images/old_task/legacy.png">', encoding="utf-8")
    (docs / "index.html").write_text('<img src="/one/images/hero.png">', encoding="utf-8")
    subprocess.check_call(["git", "add", "docs"], cwd=tmp_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed docs"], cwd=tmp_path)

    h = DocsStaticImageHook()
    ctx = HookContext(response="Done", turn=1, agent_id="t", role="r")
    tok = WORKDIR.set(tmp_path)
    try:
        (docs / "index.html").write_text(
            '<img src="/one/images/hero.png"><div style="background-image:url(images/hero.png)"></div>',
            encoding="utf-8",
        )
        assert await h.check(ctx) is None

        (docs / "index.html").write_text(
            '<img src="/images/tid/1-hero.png"><img src="/one/images/missing.png">',
            encoding="utf-8",
        )
        fb = await h.check(ctx)
        assert fb is not None
        assert "/images/tid/1-hero.png" in fb
        assert "/one/images/missing.png" in fb
        assert "legacy.html" not in fb
        assert "docs/images" in fb
    finally:
        WORKDIR.reset(tok)


async def test_docs_image_path_satisfies_local_and_pages_hooks(tmp_path):
    from core.agents.hooks import DocsStaticImageHook, MissingImageFileHook
    from core.tools.ctx import WORKDIR

    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=tmp_path)
    subprocess.check_call(["git", "config", "user.email", "t@t.t"], cwd=tmp_path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=tmp_path)

    docs = tmp_path / "docs"
    (docs / "images").mkdir(parents=True)
    (docs / "index.html").write_text("<p>seed</p>", encoding="utf-8")
    subprocess.check_call(["git", "add", "docs"], cwd=tmp_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed docs"], cwd=tmp_path)

    html = '<img src="/one/images/shared-hero.png">'
    response = f"```html\n<html><body>{html}</body></html>\n```"
    ctx = HookContext(response=response, turn=1, agent_id="t", role="r")
    docs_hook = DocsStaticImageHook()
    local_hook = MissingImageFileHook()

    tok = WORKDIR.set(tmp_path)
    try:
        (docs / "index.html").write_text(html, encoding="utf-8")
        assert await docs_hook.check(ctx) is not None
        assert await local_hook.check(ctx) is not None

        (docs / "images" / "shared-hero.png").write_bytes(b"\x89PNG-shared")
        assert await docs_hook.check(ctx) is None
        assert await local_hook.check(ctx) is None
    finally:
        WORKDIR.reset(tok)


async def test_missing_inline_html_fires_when_path_mentioned_but_no_block():
    from core.agents.hooks import HookPolicy, MissingInlineHtmlHook
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
    # Internal manager cleanup runs can opt out of artifact checks entirely.
    cleanup_ctx = HookContext(
        response=bad,
        turn=1,
        agent_id="t",
        role="r",
        policy=HookPolicy(check_referenced_html=False),
    )
    assert await h.check(cleanup_ctx) is None
    # A future explicit "require HTML" UI checkbox can force an artifact even
    # when the response does not mention one.
    required_ctx = HookContext(
        response=plain,
        turn=1,
        agent_id="t",
        role="r",
        policy=HookPolicy(require_inline_html=True),
    )
    assert await h.check(required_ctx) is not None
    # News URLs ending in .html in body text must NOT trigger the hook —
    # research summaries cite sources like techcrunch.com/article.html all the time.
    cite = "Source: https://techcrunch.com/2026/05/10/some-startup-raised.html and eu-startups.com/post.html."
    assert await h.check(HookContext(response=cite, turn=1, agent_id="t", role="r")) is None


async def test_missing_inline_html_skips_when_file_exists_in_workdir(tmp_path):
    from core.agents.hooks import MissingInlineHtmlHook
    from core.tools.ctx import WORKDIR

    html = tmp_path / "docs" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        response = "Done — I wrote `docs/index.html`."
        fb = await MissingInlineHtmlHook().check(HookContext(response=response, turn=1, agent_id="t", role="r"))
        assert fb is None
    finally:
        WORKDIR.reset(tok)


def test_hook_policy_requires_html_for_artifact_language():
    from core.agents import manager

    assert manager._hook_policy("please give me an artifact").require_inline_html is True
    assert manager._hook_policy("make a visualization of this").require_inline_html is True
    assert manager._hook_policy("write a normal answer").require_inline_html is False
