"""Skill creator — generates a SKILL.md by imitating example text and images.

Analyses the style, structure, tone, and visual language of the provided examples
and produces a ready-to-use SKILL.md that a coder agent can follow to reproduce
that style on new tasks.

Usage:
    uv run scripts/skill_creator.py \\
        --text article-example.md \\
        --image ~/Desktop/screenshot.png \\
        --out src/core/skills/general/article-writer/SKILL.md \\
        --name "article-writer"

Multiple --text and --image flags are accepted. --audio is reserved for future use.

Example texts for the article-writer skill live in:
    src/core/skills/general/article-writer/examples/
  - mechanical-slavery.md   — "The Mechanical Slavery of Knowledge Work"
  - machines-of-loving-grace.md — "Machines of Loving Grace"
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from core.ai_client import ModelProvider, ThinkingLevel, create_client
from core.ai_client.models import ImageContent

def _load_image(path: Path) -> ImageContent:
    from core.images import shrink
    r = shrink(path.read_bytes())
    return ImageContent(mime=r.mime, data=r.data)


_IMITATE_PROMPT = """\
You are a senior editor and design systems thinker. I'm giving you one or more example
texts and optionally visual references (screenshots of designs, charts, or layouts I like).

Your job is to deeply analyse what makes these examples work — their voice, structure,
rhythm, visual grammar, recurring patterns — and then produce a complete SKILL.md file
that a language model agent can follow to produce new work in the same style.

The SKILL.md must be immediately actionable. No vague adjectives. Every rule should be
concrete enough that an agent reading it cold can make decisions without ambiguity.

---

## SKILL.md format (output exactly this structure):

```
> <one-sentence summary — used in the skills index shown to every agent>

# <Skill name>

## Keywords
<comma-separated trigger words — used by UI autocomplete and suggest>

## Agent hints
- **Output:** <format of the deliverable — HTML, markdown, plain text, etc.>
- **Preferred thinking:** <minimal / low / medium / high>
- **Always also load:** <companion skills, if any — e.g. `general/artifact-design/SKILL.md`>

## How to read the request
<How should the agent interpret the user's prompt? What counts as in-scope vs out-of-scope?>

## Style and voice
<The specific stylistic rules derived from the examples. Concrete, not vague.
Each rule should finish with a brief "Why:" clause that captures the intent.>

## Structure
<Layout / sectioning conventions — how to open, how to sequence, how to close.
What the hierarchy looks like. What never appears.>

## Visual language (if applicable)
<Typography, color, diagram/chart conventions derived from the visual references.
If no visual references were provided, omit this section.>

## Worked example
<A short skeleton or template that shows the style in action. Should be copy-paste
ready — an agent can use this as a starting point for any task in this domain.>

## What NOT to do
<A tight list of anti-patterns extracted directly from the examples or implied by
the style. Concrete failures, not generic warnings.>
```

---

Now analyse the provided examples and produce the SKILL.md.

Be ruthlessly specific. Every rule should point back to something observable in the
examples. If you reference a design pattern from a visual, describe what it looks like
in enough detail that a text-only model understands it.

Output ONLY the raw SKILL.md content — no surrounding prose, no code fences around the
whole file, just the skill starting with the `>` summary line.
"""


async def imitate(
    texts: list[Path],
    images: list[Path],
    out: Path,
    model_name: str = "gpt-5.4",
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM,
) -> None:
    """Analyse examples and write a SKILL.md to `out`."""
    parts: list[str] = []
    for t in texts:
        content = t.read_text(encoding="utf-8")
        parts.append(f"=== TEXT EXAMPLE: {t.name} ===\n\n{content}")

    combined_text = "\n\n---\n\n".join(parts) if parts else ""
    prompt = f"{_IMITATE_PROMPT}\n\n---\n\n{combined_text}" if combined_text else _IMITATE_PROMPT

    loaded_images: list[ImageContent] = []
    for img_path in images:
        ic = _load_image(img_path)
        loaded_images.append(ic)
        print(f"  image: {img_path.name} → {len(ic.data):,} bytes")

    client = create_client(ModelProvider.OPENAI, model_name=model_name)
    print(f"Sending to {model_name} (thinking={thinking.value}) with {len(texts)} text(s), {len(loaded_images)} image(s)…")

    skill_md = await client.complete(
        prompt,
        thinking=thinking,
        images=loaded_images or None,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(skill_md, encoding="utf-8")
    print(f"Written → {out}")
    print(f"  {len(skill_md):,} chars  ({len(skill_md.splitlines())} lines)")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a SKILL.md by imitating examples.")
    p.add_argument("--text",  action="append", type=Path, default=[], metavar="FILE",
                   help="Text example file (can repeat)")
    p.add_argument("--image", action="append", type=Path, default=[], metavar="FILE",
                   help="Image reference file (can repeat)")
    p.add_argument("--out",   required=True, type=Path, metavar="PATH",
                   help="Output path for the generated SKILL.md")
    p.add_argument("--model", default="gpt-5.4", metavar="MODEL",
                   help="Model to use (default: gpt-5.4)")
    p.add_argument("--thinking", default="medium",
                   choices=["minimal", "low", "medium", "high"],
                   help="Thinking level (default: medium)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(imitate(
        texts=args.text,
        images=args.image,
        out=args.out,
        model_name=args.model,
        thinking=ThinkingLevel(args.thinking),
    ))
