"""Image generation clients — provider-agnostic interface, two backends.

Pattern mirrors AiClient: small abstract base, concrete subclasses per provider, factory
constructed lazily by tier. Returns raw PNG bytes — caller (the `generate_image` tool)
decides where to store them.

Backends:
- GptImageClient   → OpenAI Images API, model `gpt-image-2` (cheap/default/pro tiers)
- OllamaImageClient → local ollama, model `x/flux2-klein:4b` (ultra_cheap tier)
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes        # raw PNG bytes
    mime: str          # always "image/png" for v1
    prompt: str        # what was asked (for logging)
    model: str         # which model produced it


class ImageGenClient(ABC):
    model_name: str = ""
    provider: str = ""  # set by each subclass

    @abstractmethod
    async def generate(self, prompt: str, *, size: str = "1024x1024") -> GeneratedImage: ...


class GptImageClient(ImageGenClient):
    """OpenAI Images API. gpt-image-2 returns base64 in `data[0].b64_json`."""

    provider = "openai"

    def __init__(self, api_key: str, model_name: str = "gpt-image-2") -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self.model_name = model_name

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> GeneratedImage:
        resp = await self._client.images.generate(
            model=self.model_name,
            prompt=prompt,
            size=size,
        )
        b64 = resp.data[0].b64_json
        if not b64:
            raise RuntimeError(f"GptImageClient: no b64_json in response for prompt {prompt[:60]!r}")
        return GeneratedImage(
            data=base64.b64decode(b64), mime="image/png", prompt=prompt, model=self.model_name,
        )


class OllamaImageClient(ImageGenClient):
    """Local Ollama image-gen via raw HTTP.

    Why bypass the official `ollama` Python SDK: its `GenerateResponse` Pydantic
    model has no `image` field, so it silently drops the base64 PNG that Ollama
    returns. Confirmed against ollama-python (May 2026) — no PR yet to add it.
    The OpenAI-compat endpoint at `/v1/images/generations` is the alternative
    but Ollama marks it experimental; the raw `/api/generate` path is the most
    stable surface as of today.

    Field name gotcha: Ollama returns `image` (SINGULAR, single base64 string)
    in the response — not `images` (plural list). Plural `images` is the INPUT
    parameter for vision models (llava, qwen3-vl). Two different fields.
    """

    provider = "ollama"

    def __init__(self, model_name: str = "x/flux2-klein:4b", host: str = "http://localhost:11434") -> None:
        self._host = host.rstrip("/")
        self.model_name = model_name

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> GeneratedImage:
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except ValueError:
            w = h = 1024
        import httpx
        # 5-min timeout — flux2-klein:4b on local hardware (M-series) commonly takes
        # 60-180 s per image, sometimes longer on first call after model load.
        async with httpx.AsyncClient(timeout=300.0) as http:
            r = await http.post(
                f"{self._host}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"width": w, "height": h},
                },
            )
            r.raise_for_status()
            data = r.json()
        b64 = data.get("image")
        if not b64:
            raise RuntimeError(
                f"OllamaImageClient: no `image` field in response for prompt {prompt[:60]!r} "
                f"(keys: {list(data.keys())})"
            )
        return GeneratedImage(
            data=base64.b64decode(b64), mime="image/png", prompt=prompt, model=self.model_name,
        )
