"""Grader discovery, suggestion, and instantiation.

Graders live under `src/core/graders/<domain>/<name>.md`. Each file is markdown with
optional YAML frontmatter:

    ---
    judge: gemini:gemini-3-flash-preview
    suggested_for_skills:
      - general/article-writer/SKILL.md
    ---

    > One-line summary (mirrors the skills convention).

    ## Criteria

    ### follows_skill (weight: 2)
    Free-form prose describing what this criterion looks for.

    ### tone_and_voice
    Another criterion (weight defaults to 1).

Discovery is cached. `instantiate(path)` returns a wired `GraderHook` with a judge
client. The judge defaults to gemini-3-flash-preview when frontmatter omits it.

Graders are attached per task via `TASK_GRADERS_CTX` (set by the gateway). The
manager calls `instantiate` for each attached path and prepends the resulting
hooks to `DEFAULT_HOOKS` on `coder.run`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from core.agents.grader import Criterion, GraderHook
from core.ai_client import ModelProvider
from core.ai_client.tiers import get_or_create_client, load_grader_judge_config

_GRADERS_DIR = Path(__file__).parents[1] / "graders"


@dataclass(frozen=True)
class GraderEntry:
    path: str                                 # e.g. "general/article-voice.md"
    summary: str                              # the leading "> ..." line
    judge_provider: ModelProvider
    judge_model: str
    suggested_for_skills: frozenset[str]      # skill paths this grader fits
    criteria: tuple[Criterion, ...]
    domain: str


# --- Parsing ---------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CRITERION_HEADER_RE = re.compile(
    r"^###\s+(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(weight:\s*(?P<weight>\d+)\s*\))?\s*$",
    re.MULTILINE,
)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML-ish frontmatter parser — handles flat `key: value` and `key:\\n  - item` lists.

    We don't pull in a YAML dependency for this small surface. Anything beyond list-of-strings
    + scalar strings is intentionally unsupported; keeps the file format predictable.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end():]
    out: dict = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        s = line.rstrip()
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if s.startswith(" ") or s.startswith("\t"):
            item = s.strip().lstrip("-").strip()
            if current_list_key is not None and item:
                out[current_list_key].append(item)
            continue
        if ":" not in s:
            continue
        key, _, value = s.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            out[key] = []
            current_list_key = key
        else:
            out[key] = value
            current_list_key = None
    return out, body


def _parse_summary(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("> "):
            return s[2:].strip()
        if s and not s.startswith("#"):
            break
    return ""


def _parse_criteria(body: str) -> tuple[Criterion, ...]:
    matches = list(_CRITERION_HEADER_RE.finditer(body))
    if not matches:
        return tuple()
    out: list[Criterion] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        desc = body[start:end].strip()
        weight = int(m.group("weight") or "1")
        out.append(Criterion(name=m.group("name"), description=desc, weight=weight))
    return tuple(out)


def _parse_judge(raw: str | None) -> tuple[ModelProvider, str]:
    """Resolve a `judge:` frontmatter value. None → fall back to the global config
    in `tiers.json._grader_judge` so renaming the flash model bumps every grader at once."""
    if not raw:
        cfg = load_grader_judge_config()
        return cfg.provider, cfg.model
    if ":" not in raw:
        raise ValueError(f"judge must be 'provider:model', got {raw!r}")
    provider_str, _, model = raw.partition(":")
    try:
        provider = ModelProvider(provider_str.strip())
    except ValueError as e:
        raise ValueError(f"unknown provider {provider_str!r}: {e}")
    return provider, model.strip()


def _file_to_entry(domain: str, path: Path) -> GraderEntry | None:
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    summary = _parse_summary(body)
    criteria = _parse_criteria(body)
    if not criteria:
        return None  # no criteria → not a usable grader; skip silently
    provider, model = _parse_judge(fm.get("judge") if isinstance(fm.get("judge"), str) else None)
    suggested = fm.get("suggested_for_skills") or []
    if isinstance(suggested, str):
        suggested = [suggested]
    return GraderEntry(
        path=f"{domain}/{path.name}",
        summary=summary,
        judge_provider=provider,
        judge_model=model,
        suggested_for_skills=frozenset(suggested),
        criteria=criteria,
        domain=domain,
    )


# --- Public API ------------------------------------------------------------

@cache
def discover() -> tuple[GraderEntry, ...]:
    """Walk the graders tree once, cached for the process lifetime."""
    out: list[GraderEntry] = []
    if not _GRADERS_DIR.is_dir():
        return tuple(out)
    for domain_dir in sorted(_GRADERS_DIR.iterdir()):
        if not domain_dir.is_dir():
            continue
        for p in sorted(domain_dir.glob("*.md")):
            entry = _file_to_entry(domain_dir.name, p)
            if entry is not None:
                out.append(entry)
    return tuple(out)


def get(grader_path: str) -> GraderEntry | None:
    for g in discover():
        if g.path == grader_path:
            return g
    return None


def valid_paths() -> set[str]:
    return {g.path for g in discover()}


def suggest_for_skills(skill_paths: list[str]) -> list[GraderEntry]:
    """Return graders that declare any of the given skill paths as suggested."""
    wanted = set(skill_paths)
    return [g for g in discover() if g.suggested_for_skills & wanted]


def instantiate(grader_path: str) -> GraderHook:
    """Build a wired `GraderHook` for the given grader path. FATAL on unknown path."""
    entry = get(grader_path)
    if entry is None:
        raise ValueError(f"unknown grader: {grader_path!r}")
    cfg = load_grader_judge_config()
    judge = get_or_create_client(entry.judge_provider, entry.judge_model)
    if cfg.fallback:
        from core.ai_client.fallback_client import FallbackClient
        fallback_client = get_or_create_client(cfg.fallback.provider, cfg.fallback.model)
        judge = FallbackClient(judge, fallback_client)
    return GraderHook(criteria=list(entry.criteria), judge=judge)
