"""Tier-based client factory + DispatchRouter config + image-gen routing.

Reads tiers.json. Three things live here, all keyed on the same `(provider, model)` cache:

1. `get_or_create_client(provider, model)` — cached AiClient factory (chat / completion).
2. `get_or_create_image_client(provider, model)` — cached ImageGenClient factory.
3. `load_tier(name)`, `load_tier_options(name)`, `load_router_config()`,
   `image_client_for_tier(name)` — config-driven lookups that resolve to the above.

Generic `_cached_factory` deduplicates the cache mechanism — one dict, one cache lifecycle.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.ai_client.interface import AiClient
from core.ai_client.models import ModelProvider

_TIERS_FILE = Path(__file__).parent / "tiers.json"
_DEFAULT_TIER = "ultra_cheap"


# ---------------------------------------------------------------------------
# Generic cached factory — used for both AiClient and ImageGenClient.
# ---------------------------------------------------------------------------

# Keyed by (kind, provider, model). `kind` is just a string label so the same
# (provider, model) tuple can hold both an AiClient and an ImageGenClient.
_CACHE: dict[tuple[str, ModelProvider, str], Any] = {}


def _cached_factory(kind: str, provider: ModelProvider, model: str, build: Callable[[], Any]) -> Any:
    key = (kind, provider, model)
    if key not in _CACHE:
        _CACHE[key] = build()
    return _CACHE[key]


def _read_tiers() -> dict[str, Any]:
    return json.loads(_TIERS_FILE.read_text())


def _resolve_tier(raw: dict, name: str | None) -> tuple[str, dict]:
    tier = (name or _DEFAULT_TIER).lower()
    if tier not in raw or tier.startswith("_"):
        available = [k for k in raw if not k.startswith("_")]
        raise ValueError(f"Unknown tier {tier!r}. Available: {available}")
    return tier, raw[tier]


# ---------------------------------------------------------------------------
# AiClient (chat / completion)
# ---------------------------------------------------------------------------

def get_or_create_client(provider: ModelProvider, model_name: str) -> AiClient:
    """Cached AiClient factory — one instance per (provider, model) for the process."""
    return _cached_factory("ai", provider, model_name, lambda: _build_ai_client(provider, model_name))


def _env(var: str, provider: ModelProvider) -> str:
    v = os.environ.get(var, "")
    if not v:
        raise RuntimeError(f"{var!r} is required for provider {provider.value!r}")
    return v


def _build_ai_client(provider: ModelProvider, model_name: str) -> AiClient:
    """Per-provider construction. Lazy SDK imports keep startup cheap when only a subset is used."""
    match provider:
        case ModelProvider.OPENAI:
            from core.ai_client.gpt_client import GptClient
            return GptClient(api_key=_env("OPENAI_API_KEY", provider), model_name=model_name)
        case ModelProvider.GEMINI:
            from core.ai_client.gemini_client import GeminiClient
            return GeminiClient(api_key=_env("GOOGLE_API_KEY", provider), model_name=model_name)
        case ModelProvider.CLAUDE:
            from core.ai_client.claude_client import ClaudeClient
            return ClaudeClient(api_key=_env("ANTHROPIC_API_KEY", provider), model_name=model_name)
        case ModelProvider.OLLAMA:
            from core.ai_client.ollama_client import OllamaClient
            return OllamaClient(model_name=model_name)
        case _:
            raise ValueError(f"Unsupported provider: {provider}")


# ---------------------------------------------------------------------------
# Tier configuration: manager/coder static clients + fallback static clients
# ---------------------------------------------------------------------------

@dataclass
class TierClients:
    tier: str
    manager: AiClient
    coder: AiClient
    fallback: "TierClients | None" = None



def _make_from_entry(entry: dict) -> AiClient:
    return get_or_create_client(ModelProvider(entry["provider"]), entry["model"])


def load_tier(name: str | None = None) -> TierClients:
    """Load AiClient instances for the given tier name (defaults to ultra_cheap).

    Static manager + coder + optional fallback come from tiers.json. The DispatchRouter
    overrides the coder choice at runtime per delegation seam — these are mainly used as
    last-resort defaults and for the manager's mode-classification call.
    """
    raw = _read_tiers()
    tier, config = _resolve_tier(raw, name)
    fallback = None
    if "fallback" in config:
        fb = config["fallback"]
        fallback = TierClients(
            tier=f"{tier}:fallback",
            manager=_make_from_entry(fb["manager"]),
            coder=_make_from_entry(fb["coder"]),
        )
    return TierClients(
        tier=tier,
        manager=_make_from_entry(config["manager"]),
        coder=_make_from_entry(config["coder"]),
        fallback=fallback,
    )


# ---------------------------------------------------------------------------
# DispatchRouter — band-restricted options + picker config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FallbackTarget:
    provider: ModelProvider
    model: str


@dataclass(frozen=True)
class TierOption:
    """One model the DispatchRouter may pick from, scoped to a single tier."""
    provider: ModelProvider
    model: str
    desc: str
    fallback: FallbackTarget | None = None  # Quietly swapped in if primary returns 503/UNAVAILABLE.


@dataclass(frozen=True)
class RouterConfig:
    provider: ModelProvider
    model: str


def _parse_fallback(entry: dict | None) -> FallbackTarget | None:
    if not entry:
        return None
    return FallbackTarget(ModelProvider(entry["provider"]), entry["model"])


def load_tier_options(name: str) -> list[TierOption]:
    """Menu of models the DispatchRouter may pick from for this tier."""
    raw = _read_tiers()
    _, config = _resolve_tier(raw, name)
    return [
        TierOption(
            provider=ModelProvider(o["provider"]),
            model=o["model"],
            desc=o.get("desc", ""),
            fallback=_parse_fallback(o.get("fallback")),
        )
        for o in config.get("options") or []
    ]


def load_router_config() -> RouterConfig:
    """Picker-model config for the DispatchRouter (defaults to gpt-5.4-nano)."""
    raw = _read_tiers()
    cfg = raw.get("_router") or {"provider": "openai", "model": "gpt-5.4-nano"}
    return RouterConfig(ModelProvider(cfg["provider"]), cfg["model"])


@dataclass(frozen=True)
class GraderJudgeConfig:
    provider: ModelProvider
    model: str
    fallback: "FallbackTarget | None" = None


def load_grader_judge_config() -> GraderJudgeConfig:
    """Default judge model for every GraderHook. Single source of truth — bump the
    flash model name here once and every grader without an explicit override inherits."""
    raw = _read_tiers()
    cfg = raw.get("_grader_judge") or {"provider": "gemini", "model": "gemini-3-flash-preview"}
    return GraderJudgeConfig(
        ModelProvider(cfg["provider"]),
        cfg["model"],
        fallback=_parse_fallback(cfg.get("fallback")),
    )


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

def get_or_create_image_client(provider: ModelProvider, model: str):
    """Cached ImageGenClient factory — one instance per (provider, model)."""
    return _cached_factory("img", provider, model, lambda: _build_image_client(provider, model))


def _build_image_client(provider: ModelProvider, model: str):
    # Lazy import so consumers that never call image gen don't pay the cost.
    from core.ai_client.image_gen import GptImageClient, OllamaImageClient
    match provider:
        case ModelProvider.OPENAI:
            return GptImageClient(api_key=_env("OPENAI_API_KEY", provider), model_name=model)
        case ModelProvider.OLLAMA:
            return OllamaImageClient(model_name=model)
        case _:
            raise ValueError(f"image_gen not implemented for provider {provider.value!r}")


def image_client_for_tier(tier_name: str):
    """Read the tier's `image_gen` config and return the cached ImageGenClient.

    Falls back to the default tier's image_gen if the requested tier doesn't define one."""
    raw = _read_tiers()
    tier = (tier_name or _DEFAULT_TIER).lower()
    cfg = raw.get(tier, {}).get("image_gen") or raw.get(_DEFAULT_TIER, {}).get("image_gen")
    if not cfg:
        raise ValueError(f"No image_gen configured for tier {tier!r} (or default)")
    return get_or_create_image_client(ModelProvider(cfg["provider"]), cfg["model"])
