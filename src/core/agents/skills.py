"""Skill discovery, UI suggestions, and load_skill body fetch.

Skills live under `src/core/skills/<domain>/`. Two layouts are supported:
- Flat:   `<domain>/<name>.md`               (e.g. general/python.md)
- Folder: `<domain>/<name>/SKILL.md`         (e.g. general/artifact-design/SKILL.md)
          plus optional `assets/`, `inspiration/`, etc.

Each skill body may declare a `## Keywords` section with comma- or newline-separated
words/phrases. Keywords are NEVER auto-loaded — they're hints the gateway UI uses
to suggest skills as the user types. The user explicitly attaches skills via the
UI (chips / `/skill` command). Pre-loaded skills come from `TASK_SKILLS_CTX`,
which the gateway populates from the request body.

Inside the coder loop, anything not pre-loaded is reachable via the always-injected
skills index + the `load_skill` tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from core.ai_client.models import ImageContent

_SKILLS_DIR = Path(__file__).parents[1] / "skills"

_IMAGE_MIMES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}


@dataclass(frozen=True)
class SkillEntry:
    path: str                  # e.g. "general/artifact-design/SKILL.md"
    summary: str               # the leading "> ..." line
    keywords: frozenset[str]   # lowercased substrings for UI suggestion only
    domain: str                # top-level dir, e.g. "general"


def _parse_summary(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("> "):
            return s[2:].strip()
        if s and not s.startswith("#"):
            break
    return ""


# Accept "## Keywords" or legacy "## Triggers" (transitional — log a warning if seen).
_KEYWORDS_RE = re.compile(r"^##\s+(?:Keywords|Triggers)\s*\n(.+?)(?=\n##\s+|\Z)", re.MULTILINE | re.DOTALL)


def _parse_keywords(text: str) -> frozenset[str]:
    m = _KEYWORDS_RE.search(text)
    if not m:
        return frozenset()
    raw = m.group(1).strip()
    # Strip HTML comments so the explanatory <!-- ... --> note doesn't leak in.
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
    parts = re.split(r"[,\n]", raw)
    return frozenset(p.strip().lower() for p in parts if p.strip())


@cache
def discover() -> tuple[SkillEntry, ...]:
    """Walk the skills tree once, cached for the process lifetime."""
    out: list[SkillEntry] = []
    if not _SKILLS_DIR.is_dir():
        return tuple(out)
    for domain_dir in sorted(_SKILLS_DIR.iterdir()):
        if not domain_dir.is_dir():
            continue
        # Flat .md skills (excluding DOMAIN.md)
        for p in sorted(domain_dir.glob("*.md")):
            if p.name == "DOMAIN.md":
                continue
            text = p.read_text(encoding="utf-8")
            out.append(SkillEntry(
                path=f"{domain_dir.name}/{p.name}",
                summary=_parse_summary(text),
                keywords=_parse_keywords(text),
                domain=domain_dir.name,
            ))
        # Folder skills (must contain SKILL.md)
        for d in sorted(domain_dir.iterdir()):
            if not d.is_dir():
                continue
            skill_md = d / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text(encoding="utf-8")
            out.append(SkillEntry(
                path=f"{domain_dir.name}/{d.name}/SKILL.md",
                summary=_parse_summary(text),
                keywords=_parse_keywords(text),
                domain=domain_dir.name,
            ))
    return tuple(out)


def _matches(text_l: str, keyword: str) -> bool:
    """Word-boundary match so 'graph' doesn't fire on 'graphql'. Multi-word/dashed
    keywords fall back to substring match (low false-positive risk)."""
    if " " in keyword or "-" in keyword:
        return keyword in text_l
    return re.search(rf"\b{re.escape(keyword)}\b", text_l) is not None


def suggest_for(text: str) -> list[SkillEntry]:
    """UI hint: which skills' keywords match the given text?

    Returns matching SkillEntry objects, ordered by discovery. The gateway UI
    surfaces these as 'do you want to add skill X?' suggestions while the user
    types. NEVER used for auto-loading — only suggestions."""
    text_l = text.lower()
    return [s for s in discover() if any(_matches(text_l, k) for k in s.keywords)]


def index_for_prompt(pre_loaded: list[str] | None = None) -> str:
    """Always-injected list of skill name + one-line summary. Coder uses load_skill to fetch bodies.

    Pre-loaded skills are marked [already in context] so the coder doesn't re-fetch them."""
    skills = discover()
    if not skills:
        return ""
    loaded = set(pre_loaded or [])
    lines = ["## Available skills (call `load_skill(name)` to fetch the full body)"]
    for s in sorted(skills, key=lambda x: x.path):
        tag = " [already in context]" if s.path in loaded else ""
        lines.append(f"- `{s.path}` — {s.summary}{tag}")
    return "\n".join(lines)


def read_body(skill_path: str, include_spec: bool = True) -> str:
    """Read the full markdown body of a skill. Returns FATAL on missing file.

    For folder-format skills, appends DESIGN_SPEC.md when include_spec=True (the
    default for on-demand load_skill calls). Pre-load via join_bodies passes
    include_spec=False to keep context lean for local models.
    """
    p = _SKILLS_DIR / skill_path
    if not p.is_file():
        return f"FATAL: skill not found: {skill_path!r}"
    body = p.read_text(encoding="utf-8")
    if include_spec and p.name == "SKILL.md":
        spec = p.parent / "DESIGN_SPEC.md"
        if spec.is_file():
            body += "\n\n---\n\n" + spec.read_text(encoding="utf-8")
    return body


def join_bodies(skill_paths: list[str]) -> str:
    """Concatenate skill bodies with separators for inlining in instructions.

    Excludes DESIGN_SPEC.md — keeps pre-load context lean. The coder can pull
    the full spec on demand via load_skill if it needs the detailed patterns.
    """
    chunks = [read_body(p, include_spec=False) for p in skill_paths if (_SKILLS_DIR / p).is_file()]
    return "\n\n---\n\n".join(chunks)


def images_for(skill_path: str) -> list[ImageContent]:
    """Return all images in `<skill folder>/inspiration/` for a folder-format skill.

    Only folder skills (e.g. `general/artifact-design/SKILL.md`) can carry images. Flat
    `.md` skills return []. The model receives these on turn 0 of the coder loop.
    """
    p = _SKILLS_DIR / skill_path
    if not p.is_file() or p.name != "SKILL.md":
        return []
    insp_dir = p.parent / "inspiration"
    if not insp_dir.is_dir():
        return []
    out: list[ImageContent] = []
    for img_path in sorted(insp_dir.iterdir()):
        mime = _IMAGE_MIMES.get(img_path.suffix.lower())
        if not mime:
            continue
        out.append(ImageContent(mime=mime, data=img_path.read_bytes()))
    return out


def collect_images(skill_paths: list[str]) -> list[ImageContent]:
    """Flatten images across all pre-loaded skills.

    Currently disabled — inspiration images are replaced by DESIGN_SPEC.md text so
    text-only local models (qwen, gemma) benefit too. Re-enable by uncommenting the
    loop when vision-capable models are the default or for specific cloud-only flows.
    """
    return []
    # out: list[ImageContent] = []
    # for p in skill_paths:
    #     out.extend(images_for(p))
    # return out
