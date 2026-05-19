"""Generate a detailed design spec from artifact-design inspiration images.

Reads all images from src/core/skills/general/artifact-design/inspiration/,
sends them to GPT-5.4 with medium thinking, and writes a comprehensive
DESIGN_SPEC.md into the same skill folder. The spec captures color palette,
typography, spacing, layout patterns, and component styles as detailed text
+ example HTML/CSS — so text-only models (qwen, gemma) can follow the design
language without needing the images at all.

Run whenever new inspiration images are added:
    uv run python scripts/generate_artifact_design_spec.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from core.ai_client import ModelProvider, ThinkingLevel, create_client
from core.ai_client.models import ImageContent
from core.images import shrink

SKILL_DIR = Path(__file__).resolve().parent.parent / "src/core/skills/general/artifact-design"
INSPO_DIR = SKILL_DIR / "inspiration"
OUT_FILE  = SKILL_DIR / "DESIGN_SPEC.md"

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

PROMPT = """\
You are a senior product designer. I'm giving you design inspiration screenshots that
together form a loose visual vocabulary — not a single rigid system. Your job is to
distil them into 5 DISTINCT named presets, each a complete and self-consistent aesthetic
the agent can pick between based on the topic. The presets should genuinely differ in
mood — different palettes, different type pairings, different energy. No two presets
should feel like minor variations of each other.

The goal is creative range with internal coherence: any single artifact should be
unmistakably ON-brand for one preset, and any two artifacts using DIFFERENT presets
should look meaningfully different.

Be ruthlessly concise — under 350 lines total. No padding. Every line actionable.

## Top of file: preset menu

A short table or list naming all presets with one-line "vibe" + "when to use it".
The agent reads this first to pick a preset.

## For EACH of the 5 presets, in this exact structure:

### Preset N — <NAME>

**Vibe (1–2 sentences)** — the mood, the reference points, the emotional register.
Name specific cultural anchors if relevant (e.g. "editorial broadsheet", "terminal
brutalism", "Y2K magazine glossy", "Scandi minimal", "1990s zine").

**When to use it** — concrete topic types this preset fits best. 2–3 examples.

**Typography** — exact combos for: display headline, section heading, body, caption,
eyebrow label, mono tag. Include the full Google Fonts @import URL. The five presets
MUST use five genuinely different type systems — don't keep recycling Inter/Fraunces/
JetBrains. Pull from across the Google Fonts catalogue: serifs, sans, mono, display,
slab, condensed, geometric, humanist — match the type to the vibe.

**Colour tokens** — CSS custom property block, no prose. Every role: --bg, --surface,
--ink, --ink-muted, --accent, --border, --tag-bg. Derive palettes FROM THE INSPIRATION,
not from any preset background. Some presets should have warm/cream backgrounds, others
should be cool/dark/saturated/desaturated/high-contrast/etc. — give the agent real range.

**Layout & spacing** — key values: max-width, page padding, card padding, gap. One line each.

**Signature components (2–3)** — the components most characteristic of this preset.
Each gets a one-line description + minimal HTML+CSS snippet (copy-paste ready).

**Skeleton** — one complete minimal `<!DOCTYPE html>…</html>` page using this preset's
tokens. Inline `<style>`, Google Fonts import, placeholder content showing hierarchy.
This is the starting template when the agent picks this preset.

## After all presets: cross-preset principles

A short closing section (under 20 lines) covering what's CONSTANT across all presets —
generous whitespace, no decorative noise, sharp focus rings, accessible contrast,
restraint over decoration. Things that hold no matter which preset is chosen.

A model reading this spec should be able to (a) pick the right preset for a topic,
(b) produce a fully on-brand artifact in one shot, (c) feel like the artifacts have
genuine variety across runs without ever feeling chaotic.
"""


async def main() -> None:
    images = []
    for f in sorted(INSPO_DIR.iterdir()):
        if f.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        r = shrink(f.read_bytes())
        print(f"  {f.name}: {r.original_bytes:,} → {r.new_bytes:,} bytes")
        images.append(ImageContent(mime=r.mime, data=r.data))
    if not images:
        print("No inspiration images found.")
        return

    print(f"Loaded {len(images)} inspiration images — sending to GPT-5.4 (thinking=medium)…")

    client = create_client(ModelProvider.OPENAI, model_name="gpt-5.4")
    spec = await client.complete(PROMPT, thinking=ThinkingLevel.MEDIUM, images=images)

    OUT_FILE.write_text(spec, encoding="utf-8")
    print(f"Written → {OUT_FILE.relative_to(Path.cwd())}")
    print(f"  {len(spec):,} chars  ({len(spec.splitlines())} lines)")


if __name__ == "__main__":
    asyncio.run(main())
