"""generate_image tool — agent calls it to produce a PNG, gets back a URL.

Tier-routed: TIER_CTX selects which ImageGenClient runs (gpt-image-2 for cloud tiers,
x/flux2-klein:4b for ultra_cheap). Output lands at `generated/images/<task_id>/<n>-<slug>.png`
on disk, and is served by the gateway under `/images/<task_id>/<filename>`. The tool returns
the URL form so the agent can drop it straight into `<img src="..."` in HTML artifacts.
"""

from __future__ import annotations

import re

from core.agents.task_ctx import TIER_CTX, current_task_id
from core.ai_client.models import Tool
from core.ai_client.tiers import image_client_for_tier
from core.log import Category
from core.log import log as _log
from core.tools.ctx import WORKDIR
_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}


def _slug(prompt: str) -> str:
    s = prompt.lower().strip().replace(" ", "-")
    s = _SLUG_RE.sub("", s)[:40].strip("-")
    return s or "image"


async def generate_image(prompt: str, size: str = "1024x1024") -> str:
    if size not in _VALID_SIZES:
        return f"FATAL: invalid size {size!r}. Valid: {sorted(_VALID_SIZES)}"
    if not prompt.strip():
        return "FATAL: prompt cannot be empty"

    tier = TIER_CTX.get()
    try:
        client = image_client_for_tier(tier)
    except Exception as e:
        return f"FATAL: image generation unavailable for tier {tier!r}: {e}"

    try:
        img = await client.generate(prompt, size=size)
    except Exception as e:
        return f"RETRYABLE: image generation failed: {e}"

    task_id = current_task_id() or "task"
    out_dir = WORKDIR.get() / "generated" / "images" / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    n = sum(1 for _ in out_dir.glob("*.png")) + 1
    filename = f"{n}-{_slug(prompt)}.png"
    path = out_dir / filename
    path.write_bytes(img.data)

    # URL form: served by the gateway via `app.mount("/images", generated/images)`.
    # Drop straight into <img src="..."> in HTML artifacts; same URL works for the
    # standalone /artifacts/ view since the iframe and that page share the gateway origin.
    url = f"/images/{task_id}/{filename}"
    # Log only the URL (the path is derivable: `generated/images/<task>/<file>` ↔
    # `/images/<task>/<file>`). Was duplicating both — noisy in the trace bar.
    _log(
        Category.TOOL, "generate_image",
        provider=client.provider, model=client.model_name,
        size=size, bytes=len(img.data), url=url, prompt=prompt[:120],
    )
    return url


GENERATE_IMAGE_TOOL = Tool(
    name="generate_image",
    description=(
        "Generate a PNG image from a text prompt. Returns a URL string like "
        "`/images/<task_id>/<n>-<slug>.png` that you MUST embed in your response so "
        "the user sees it: inside an HTML block use `<img src='...'>`; in a plain markdown "
        "response use `![alt](url)`. NEVER paste the bare URL as text — it renders as a "
        "literal string and the user sees nothing. The gateway serves these paths automatically. "
        "Use for hero images in articles, atmospheric photography in artifacts, or any "
        "visual asset that genuinely strengthens the artifact (don't sprinkle them just "
        "because you can). Tier-routed automatically: cheap/default/pro use gpt-image-2, "
        "ultra_cheap uses local flux2-klein. is_concurrency_safe — safe to fan out multiple "
        "calls in one turn for an article with several images."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "What to draw. Be specific: subject, mood, composition, color palette, style. "
                    "Match the artifact's design language — see general/artifact-design/SKILL.md "
                    "(default light/warm-cream + one earthy accent; Modal-style isometric "
                    "geometry for technical artifacts; atmospheric photography for storytelling)."
                ),
            },
            "size": {
                "type": "string",
                "enum": sorted(_VALID_SIZES),
                "description": "Output dimensions. Default 1024x1024. Use 1536x1024 for hero/banner, 1024x1536 for portrait.",
            },
        },
        "required": ["prompt"],
    },
    fn=generate_image,
    is_read_only=False,
    is_concurrency_safe=True,
)
