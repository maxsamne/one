"""Image preprocessing for vision-LLM inputs.

Caps longest side and re-encodes as JPEG. Reference screenshots are typically
retina (3000+ px); raw they cost ~180K tokens/image on GPT-5.x patch tokenisation
and dilute the model's attention. Downsampling to ~1280 keeps gist intact while
cutting tokens ~6×.
"""

import io
from dataclasses import dataclass

MAX_PX = 1280
QUALITY = 88


@dataclass(frozen=True)
class ResizedImage:
    data: bytes
    mime: str  # always "image/jpeg" after re-encode
    original_size: tuple[int, int]
    new_size: tuple[int, int]
    original_bytes: int
    new_bytes: int


def shrink(data: bytes, max_px: int = MAX_PX, quality: int = QUALITY) -> ResizedImage:
    from PIL import Image as PILImage

    original_bytes = len(data)
    img = PILImage.open(io.BytesIO(data)).convert("RGB")
    original_size = img.size
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    out = buf.getvalue()
    return ResizedImage(
        data=out,
        mime="image/jpeg",
        original_size=original_size,
        new_size=img.size,
        original_bytes=original_bytes,
        new_bytes=len(out),
    )
