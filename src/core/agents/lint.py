"""Post-render lint — deterministic checks on the agent's final output.

Runs in `coder.run` after the model returns a text-only response (loop-end signal).
If issues are found, the loop continues with the lint output fed back as the next
user message — the agent gets up to N retries to fix and re-emit.

Pattern: "reflexion loop" / "validator-in-the-loop". Cheap — pure regex, no extra
LLM calls when output is clean. Designed to grow into a checks framework: add new
rules to `_HTML_RULES` (or new domain files for python lint, image lint, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class LintIssue:
    rule: str           # short identifier, e.g. "markdown-link"
    detail: str         # human-readable description (shown to the agent)
    excerpt: str = ""   # offending snippet for context


# Each rule: (id, regex applied to body, detail message, excerpt extractor or None)
# Rules only fire on content INSIDE <body>...</body> when present, else on the whole string.

_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.DOTALL | re.IGNORECASE)
_HREF_OR_SRC_RE = re.compile(r'(?:href|src)\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")  # crude tag stripper for "visible text" extraction


def _body_text(html: str) -> str:
    """Return the part inside <body> if present, else the whole html."""
    m = _BODY_RE.search(html)
    return m.group(1) if m else html


def _visible_text(html: str) -> str:
    """Strip tags + remove href/src attribute values so we can scan visible text only."""
    no_attrs = _HREF_OR_SRC_RE.sub("", html)
    return _TAG_RE.sub(" ", no_attrs)


# --- Individual rules ------------------------------------------------------

def _check_markdown_link(html: str) -> list[LintIssue]:
    """Detect `[text](url)` inside the body — markdown link in HTML overflows cards."""
    body = _body_text(html)
    out = []
    for m in re.finditer(r"\[([^\]\n]{1,80})\]\((https?://[^\s)]{1,300})\)", body):
        out.append(LintIssue(
            rule="markdown-link",
            detail=(
                "Found markdown link syntax `[text](url)` inside HTML. Browsers render "
                "this as literal text, exposing the URL and overflowing narrow cards. "
                "Replace every occurrence with a real `<a href=\"url\">text</a>` tag."
            ),
            excerpt=m.group(0)[:160],
        ))
        if len(out) >= 5:  # cap repeats — agent only needs to see a few examples
            break
    return out


def _check_markdown_bold(html: str) -> list[LintIssue]:
    """Detect `**text**` or `__text__` inside the body — markdown bold leaks."""
    body = _body_text(html)
    out = []
    for m in re.finditer(r"(\*\*|__)(?!\s)([^*_\n]{1,80}?)\1", body):
        out.append(LintIssue(
            rule="markdown-bold",
            detail="Markdown bold syntax (`**text**` or `__text__`) leaked into HTML. Use `<strong>text</strong>` instead.",
            excerpt=m.group(0)[:120],
        ))
        if len(out) >= 3:
            break
    return out


def _check_bare_url(html: str) -> list[LintIssue]:
    """Detect bare http(s) URLs in visible text — not inside href/src — they overflow cards."""
    visible = _visible_text(_body_text(html))
    out = []
    for m in re.finditer(r"https?://[^\s<>\"'()]{15,300}", visible):
        out.append(LintIssue(
            rule="bare-url",
            detail=(
                "Bare URL appears as visible text — long unbreakable strings overflow "
                "narrow containers. Wrap it in `<a href=\"...\">SourceName</a>` with "
                "concise visible text, never the URL itself."
            ),
            excerpt=m.group(0)[:160],
        ))
        if len(out) >= 5:
            break
    return out


_HTML_RULES: list[Callable[[str], list[LintIssue]]] = [
    _check_markdown_link,
    _check_markdown_bold,
    _check_bare_url,
]


# --- Public API ------------------------------------------------------------

def lint_html(html: str) -> list[LintIssue]:
    """Run every HTML rule, return all issues. Empty list = clean."""
    issues: list[LintIssue] = []
    for rule in _HTML_RULES:
        issues.extend(rule(html))
    return issues


_HTML_BLOCK_RE = re.compile(r"```html\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_html_block(response: str) -> str | None:
    """Return the contents of the first ```html block in `response`, or None."""
    m = _HTML_BLOCK_RE.search(response)
    return m.group(1) if m else None


def format_feedback(issues: list[LintIssue]) -> str:
    """Build the user-message string we feed back to the coder for a fix-up turn."""
    lines = [
        "Your HTML artifact has issues that need fixing. Re-emit the artifact with these resolved:",
        "",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. **{issue.rule}** — {issue.detail}")
        if issue.excerpt:
            lines.append(f"   Example found: `{issue.excerpt}`")
    lines.append("")
    lines.append("Output the corrected complete HTML inside a ```html``` block. Do not narrate the fix.")
    return "\n".join(lines)
