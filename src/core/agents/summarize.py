"""Prepend a one-line summary to a skill file using local Gemma4."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from core.ai_client.models import ThinkingLevel
from core.ai_client.ollama_client import OllamaClient

_INSTRUCTIONS = (
    "Summarise the following skill file in one line, maximum 15 words. "
    "Focus on what domain and task it covers. No punctuation at the end."
)

_client = OllamaClient()


async def summarize(path: Path) -> None:
    content = path.read_text(encoding="utf-8")

    # Strip existing summary line if present
    lines = content.splitlines()
    if lines and lines[0].startswith("> "):
        content = "\n".join(lines[1:]).lstrip("\n")

    summary = await _client.complete(
        content,
        instructions=_INSTRUCTIONS,
        thinking=ThinkingLevel.MINIMAL,
    )
    summary = summary.strip().lstrip("> ")
    path.write_text(f"> {summary}\n\n{content}", encoding="utf-8")
    print(f"✓ {path.name}: {summary}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: summarize <skill-file-or-dir>")
        sys.exit(1)

    target = Path(sys.argv[1])
    paths = sorted(target.rglob("*.md")) if target.is_dir() else [target]
    for p in paths:
        await summarize(p)


asyncio.run(main())
