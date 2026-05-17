"""Local Ollama image-gen smoke. Skipped by default (slow + needs local Ollama).

Set RUN_LOCAL_IMAGE_GEN=1 and have `x/flux2-klein:4b` pulled locally to run.
First call after model load typically takes 60-180 s on M-series; subsequent
calls under 30 s. The test uses 512x512 to stay on the fast end.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LOCAL_IMAGE_GEN") != "1",
    reason="Set RUN_LOCAL_IMAGE_GEN=1 to run (needs Ollama + x/flux2-klein:4b)",
)


async def test_ollama_flux_generates_valid_png():
    from core.ai_client.image_gen import OllamaImageClient
    img = await OllamaImageClient().generate("a tiny green dot on white background", size="512x512")
    assert img.mime == "image/png"
    assert img.data[:8] == bytes.fromhex("89504e470d0a1a0a")  # PNG signature
    assert len(img.data) > 5000  # not an empty / corrupt placeholder
