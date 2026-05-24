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

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import re

from core.agents.lint import extract_html_block, format_feedback, lint_html
from core.log import Category
from core.log import log as _log
from core.tools.ctx import WORKDIR


@dataclass(frozen=True)
class HookPolicy:
    """Per-run hook strictness switches."""
    check_referenced_html: bool = True
    require_inline_html: bool = False


@dataclass(frozen=True)
class HookContext:
    """Inputs every hook sees. Add fields here as more hooks need more context."""
    response: str
    turn: int            # 1-based turn number that produced the response
    agent_id: str
    role: str
    policy: HookPolicy = HookPolicy()


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


# Detects responses that say "I wrote `path/to/foo.html`" but don't provide a
# renderable artifact. If the file exists, the manager appends it from disk; if
# not, the hook asks the agent to write/provide the HTML.
#
# Match a backtick-wrapped relative path ending in .html. The leading backtick
# is intentional — it excludes URLs in body text (e.g. "techcrunch.com/x.html")
# which would otherwise trip this on any response that cites a news source.
_HTML_PATH_RE = re.compile(r"`((?!https?://)[\w./\-]+\.html)`")


def _html_file_exists(ref: str, workdir: Path) -> bool:
    if ref.startswith("/one/"):
        candidates = [workdir / "docs" / ref[len("/one/"):], workdir / ref.lstrip("/")]
    elif ref.startswith("/"):
        candidates = [workdir / ref.lstrip("/")]
    else:
        candidates = [workdir / ref]
    return any(_candidate_exists(candidate, workdir) for candidate in candidates)


class MissingInlineHtmlHook(Hook):
    """Ensure claimed or explicitly required HTML can be rendered."""
    name = "missing-inline-html"

    async def check(self, ctx: HookContext) -> str | None:
        if extract_html_block(ctx.response) is not None:
            return None  # inline block present, nothing to do
        refs = [m.group(1) for m in _HTML_PATH_RE.finditer(ctx.response)]
        if refs and ctx.policy.check_referenced_html:
            workdir = WORKDIR.get()
            if all(_html_file_exists(ref, workdir) for ref in refs):
                return None  # manager will append renderable HTML from disk
            return (
                "Your response references an HTML file, but I cannot find that file "
                "in the task workdir and there is no inline ```html``` block. Please "
                "write the referenced HTML file, or include the complete HTML inside "
                "a ```html``` block."
            )
        if not ctx.policy.require_inline_html:
            return None
        return (
            "This task requires a renderable HTML artifact, but your response does "
            "not include one. Write an HTML file in the task workdir, or include the "
            "complete HTML inside a ```html``` block."
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


# Matches <img ... src="X" ...>. Captures the src value verbatim (no trimming).
_IMG_SRC_RE = re.compile(
    r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*/?>',
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE)

_REMOTE_SRC_SCHEMES = {"http", "https", "data", "mailto", "javascript", "tel", "ftp", "slack"}


def _normalise_local_img_src(src: str) -> str | None:
    """Return the local path part of an image src, or None for remote/anchor URLs."""
    raw = src.strip()
    if not raw or raw.startswith("#") or raw.startswith("//"):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.lower() in _REMOTE_SRC_SCHEMES:
        return None
    return unquote(parsed.path or raw)


def _resolve_img_candidates(src: str, workdir: Path) -> list[Path]:
    """Plausible on-disk locations for an <img src="..."> in the running coder's workdir.

    Matches what the coder typically writes:
      - "/one/..."          → docs/...                  (GH Pages prefix stripped)
      - "/images/<task>/..." → generated/images/<task>/... (gateway URL → on-disk)
      - bare / relative     → check directly, under docs/, and under generated/
    """
    if src.startswith("/one/"):
        rel = src[len("/one/"):]
        return [workdir / "docs" / rel, workdir / rel]
    if src.startswith("/images/"):
        return [workdir / "generated" / src.lstrip("/")]
    rel = src.lstrip("/")
    return [
        workdir / rel,
        workdir / "docs" / rel,
        workdir / "generated" / rel,
    ]


def _candidate_exists(candidate: Path, workdir: Path) -> bool:
    try:
        resolved = candidate.resolve(strict=True)
        root = workdir.resolve()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return (resolved == root or root in resolved.parents) and resolved.is_file()


def _docs_asset_exists(src: str, html_file: Path, workdir: Path) -> bool:
    local_src = _normalise_local_img_src(src)
    if not local_src:
        return True

    docs_root = workdir / "docs"
    if local_src.startswith("/images/"):
        return False
    if local_src.startswith("/one/"):
        candidate = docs_root / local_src[len("/one/"):]
    elif local_src.startswith("/"):
        candidate = docs_root / local_src.lstrip("/")
    else:
        candidate = html_file.parent / local_src

    try:
        resolved = candidate.resolve(strict=True)
        docs_resolved = docs_root.resolve()
    except (FileNotFoundError, OSError):
        return False
    return (resolved == docs_resolved or docs_resolved in resolved.parents) and resolved.is_file()


async def _git_out(workdir: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def _docs_html_files_changed_in_task(workdir: Path) -> list[Path]:
    """Return docs HTML files changed by the current task branch."""
    changed: set[Path] = set()

    rc, out = await _git_out(workdir, "diff", "--name-only", "--diff-filter=ACMR", "HEAD", "--", "docs")
    if rc == 0:
        changed.update(workdir / p for p in out.splitlines() if p.endswith(".html"))

    rc, branch = await _git_out(workdir, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or not branch or branch == "HEAD":
        return sorted(p for p in changed if p.is_file())

    bases: list[str] = []
    if branch.startswith("task/") and "-" in branch:
        bases.append(branch.rsplit("-", 1)[0])
    if branch.startswith("task/"):
        bases.append(f"origin/{branch}")

    for base in bases:
        rc, _ = await _git_out(workdir, "rev-parse", "--verify", base)
        if rc != 0:
            continue
        rc, out = await _git_out(workdir, "diff", "--name-only", "--diff-filter=ACMR", f"{base}..HEAD", "--", "docs")
        if rc == 0:
            changed.update(workdir / p for p in out.splitlines() if p.endswith(".html"))
        break

    return sorted(p for p in changed if p.is_file())


class MissingImageFileHook(Hook):
    """Catches <img src="..."> entries that point to a file that doesn't exist on disk.

    Resolves each src against the running coder's WORKDIR using a small set of
    plausible candidates (GH-Pages prefix, generated/images/, docs/). Skips remote
    URLs, data: URIs, and anchor links. Zero LLM cost.
    """
    name = "missing-image-file"

    async def check(self, ctx: HookContext) -> str | None:
        html = extract_html_block(ctx.response)
        if not html:
            return None
        try:
            workdir = WORKDIR.get()
        except LookupError:
            return None  # no workdir set — nothing we can check against
        missing: list[str] = []
        for m in _IMG_SRC_RE.finditer(html):
            src = m.group(1).strip()
            local_src = _normalise_local_img_src(src)
            if not local_src:
                continue
            if any(_candidate_exists(p, workdir) for p in _resolve_img_candidates(local_src, workdir)):
                continue
            missing.append(src)
            if len(missing) >= 5:  # cap — agent only needs a few examples
                break
        if not missing:
            return None
        bullets = "\n".join(f"  - `{s}`" for s in missing)
        return (
            "One or more <img src=\"...\"> values in your HTML point to files that don't exist:\n"
            f"{bullets}\n\n"
            "Either generate the image via `generate_image(prompt)` and use the returned path, "
            "or copy an existing file into the expected location, or remove the <img> tag. "
            "Do not invent filenames — every src must resolve to an actual file."
        )


class DocsStaticImageHook(Hook):
    """Checks committed docs HTML uses static image paths GitHub Pages can serve."""
    name = "docs-static-image"

    async def check(self, ctx: HookContext) -> str | None:
        try:
            workdir = WORKDIR.get()
        except LookupError:
            return None

        docs_dir = workdir / "docs"
        if not docs_dir.is_dir():
            return None

        html_files = await _docs_html_files_changed_in_task(workdir)
        if not html_files:
            return None

        bad: list[str] = []
        for html_file in html_files:
            try:
                html = html_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs = [m.group(1).strip() for m in _IMG_SRC_RE.finditer(html)]
            refs.extend(m.group(2).strip() for m in _CSS_URL_RE.finditer(html))
            for ref in refs:
                local_ref = _normalise_local_img_src(ref)
                if not local_ref:
                    continue
                if _docs_asset_exists(ref, html_file, workdir):
                    continue
                rel_file = html_file.relative_to(workdir)
                bad.append(f"{rel_file}: `{ref}`")
                if len(bad) >= 5:
                    break
            if len(bad) >= 5:
                break

        if not bad:
            return None
        bullets = "\n".join(f"  - {item}" for item in bad)
        return (
            "One or more images in docs/*.html use paths that GitHub Pages cannot serve:\n"
            f"{bullets}\n\n"
            "For committed website pages, copy generated image files into `docs/images/` "
            "and reference them as `/one/images/<filename>` (or another existing file under `docs/`). "
            "Do not use `/images/<task_id>/...` in docs pages; that path is only served by the local task preview gateway."
        )


# Registered hooks run in this order on every loop-end. Override via coder.run(hooks=...).
DEFAULT_HOOKS: list[Hook] = [
    MissingInlineHtmlHook(),  # cheapest first — runs before HtmlLintHook so the
    HtmlLintHook(),           # lint can actually see content
    BrokenImageHook(),
    MissingImageFileHook(),
    DocsStaticImageHook(),
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
