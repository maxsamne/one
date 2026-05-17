"""DispatchRouter: ROUTER_FORCE override, valid pick, fallback on invalid."""

import os

from pydantic import BaseModel

from core.agents import router
from core.agents.router import RoutingRequest, _force_choice, pick


class _StubPicker:
    """Returns a canned RouterChoice — bypasses real LLM."""
    def __init__(self, choice): self._choice = choice
    async def complete(self, *a, response_model=None, **kw):
        if response_model is None:
            return ""
        return response_model.model_validate(self._choice)


def test_router_force_parses_model_with_colons(monkeypatch):
    # qwen3.5:9b contains a colon — parser must split provider/model/thinking correctly.
    monkeypatch.setenv("ROUTER_FORCE", "ollama:qwen3.5:9b:medium")
    choice = _force_choice()
    assert (choice.provider, choice.model, choice.thinking) == ("ollama", "qwen3.5:9b", "medium")


async def test_pick_returns_valid_choice_from_band(monkeypatch):
    # Picker returns a valid (provider, model) from ultra_cheap's options menu.
    monkeypatch.setattr(router, "_PICKER", _StubPicker(
        {"provider": "ollama", "model": "qwen3.5:9b", "thinking": "medium"}
    ))
    choice = await pick(RoutingRequest(task="x", tier="ultra_cheap", seam="manager"))
    assert (choice.provider, choice.model) == ("ollama", "qwen3.5:9b")


async def test_pick_falls_back_on_invalid_choice(monkeypatch):
    # Picker insists on a model NOT in the band — router falls back to options[0] + medium.
    monkeypatch.setattr(router, "_PICKER", _StubPicker(
        {"provider": "openai", "model": "not-in-band", "thinking": "low"}
    ))
    choice = await pick(RoutingRequest(task="x", tier="ultra_cheap", seam="manager"))
    assert choice.provider == "ollama" and choice.thinking == "medium"  # fallback signature
