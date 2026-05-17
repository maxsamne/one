"""Project presets — small JSON files bundling a default tier, skills, and graders.

A preset is a convenience layer: the UI hydrates the composer (tier picker +
skill chips + grader chips) from a preset's defaults. The user can override
anything before submitting. There is no runtime concept of "the task ran under
preset X" — presets exist only at composition time.

File shape (`src/core/presets/<name>.json`):

    {
      "name": "article-writer",
      "description": "Long-form article writing in your voice.",
      "tier": "default",
      "skills": ["general/article-writer/SKILL.md"],
      "graders": ["general/article-voice.md"]
    }

Discovery is cached. The gateway exposes `GET /presets`; the UI handles hydration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_PRESETS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class PresetEntry:
    name: str
    description: str
    tier: str
    skills: tuple[str, ...]
    graders: tuple[str, ...]


def _parse(path: Path) -> PresetEntry | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    name = raw.get("name") or path.stem
    return PresetEntry(
        name=str(name),
        description=str(raw.get("description") or ""),
        tier=str(raw.get("tier") or "ultra_cheap"),
        skills=tuple(raw.get("skills") or []),
        graders=tuple(raw.get("graders") or []),
    )


@cache
def discover() -> tuple[PresetEntry, ...]:
    """Walk `*.json` files in src/core/presets/, cached for the process lifetime."""
    out: list[PresetEntry] = []
    if not _PRESETS_DIR.is_dir():
        return tuple(out)
    for p in sorted(_PRESETS_DIR.glob("*.json")):
        entry = _parse(p)
        if entry is not None:
            out.append(entry)
    return tuple(out)


def get(name: str) -> PresetEntry | None:
    for p in discover():
        if p.name == name:
            return p
    return None
