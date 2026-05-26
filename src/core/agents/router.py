"""DispatchRouter — auto-runs at every delegation seam to pick (provider, model, thinking).

The router is *not* a tool the model calls. It's a hook the runtime invokes:
- Manager → top-level coder seam (gateway): picks the coder's model from the tier's `options`.
- Coder → sub-agent seam (spawn_subagent): picks the sub-agent's model from the same band.

Picker model is configured in tiers.json `_router`. Defaults to gpt-5.4-nano.
Override per call with ROUTER_FORCE=provider:model[:thinking].
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.ai_client.interface import AiClient
from core.ai_client.models import ModelProvider, ThinkingLevel
from core.ai_client.tiers import (
    TierOption,
    get_or_create_client,
    load_router_config,
    load_tier_options,
)
from core.log import Category
from core.log import log as _log


@dataclass(frozen=True)
class RoutingRequest:
    """Inputs to the router. Both seams populate the relevant fields; rest stay defaults."""
    task: str
    tier: str
    seam: Literal["manager", "subagent"]
    skills: list[str] = field(default_factory=list)         # manager seam: resolved skill files
    edit_mode: str | None = None                            # subagent seam: read_only|conversational|worktree
    parent_intent: str | None = None                        # subagent seam: parent's spawn `description`
    parent_role: str | None = None                          # subagent seam: parent's ROLE_CTX


class RouterChoice(BaseModel):
    provider: str
    model: str
    thinking: str = Field(default="none", description="One of: none, minimal, low, medium, high")

    @field_validator("thinking", mode="before")
    @classmethod
    def _norm_thinking(cls, v: object) -> str:
        if v is None:
            return "none"
        v = str(v).lower().strip()
        if v not in ("none", "minimal", "low", "medium", "high"):
            raise ValueError(f"thinking must be one of none/minimal/low/medium/high, got {v!r}")
        return v

    def thinking_level(self) -> ThinkingLevel | None:
        if self.thinking == "none":
            return None
        return ThinkingLevel(self.thinking)


_PICKER: AiClient | None = None


def _picker() -> AiClient:
    global _PICKER
    if _PICKER is None:
        cfg = load_router_config()
        _PICKER = get_or_create_client(cfg.provider, cfg.model)
    return _PICKER


def _format_options(options: list[TierOption]) -> str:
    """Format unambiguously so the picker doesn't conflate provider+model into one string."""
    lines = []
    for i, o in enumerate(options, 1):
        lines.append(f"{i}. provider={o.provider.value!r}  model={o.model!r}  — {o.desc}")
    return "\n".join(lines)


def _format_request(req: RoutingRequest, options: list[TierOption]) -> str:
    lines = [
        f"Tier: {req.tier}",
        f"Seam: {req.seam}",
    ]
    if req.skills:
        lines.append(f"Skills resolved: {', '.join(req.skills)}")
    if req.parent_intent:
        lines.append(f"Parent's intent (description): {req.parent_intent}")
    if req.edit_mode:
        lines.append(f"Sub-agent edit_mode: {req.edit_mode}")
    if req.parent_role:
        lines.append(f"Parent role: {req.parent_role}")
    lines.append(f"\nTask:\n{req.task[:1500]}")
    lines.append(f"\nAvailable models in band {req.tier!r}:\n{_format_options(options)}")
    return "\n".join(lines)


_INSTRUCTIONS = """\
You pick the model and thinking level for the next agent step.

Output strictly:
- provider: must match one of the listed options exactly (e.g. "openai", "ollama").
- model: must match one of the listed options exactly.
- thinking: none | minimal | low | medium | high. Use none to disable provider reasoning/thinking.

Heuristics:
- Ultra-cheap tier → default to thinking=none. Pick minimal/low only when the task clearly benefits from extra planning, and medium/high only for genuinely deep reasoning or robust multi-step action planning.
- Quick lookups, simple Q&A → none/minimal + the cheapest/fastest option.
- Non-ultra-cheap code generation, refactors, multi-step tool use → medium + a stronger option.
- Non-ultra-cheap complex architecture, hard math, deep analysis → high + the strongest option.
- Sub-agents in read_only mode are usually lookups → bias cheap.
- Sub-agents in worktree mode are usually real coding → bias stronger.
- Default-tier long-form article writing, essays, editorial drafts, and tasks using the article-writer skill → prefer the OpenAI `gpt-5.4` option with medium thinking. Use Gemini for article work only when unusually long-context synthesis or multimodal reference handling is the dominant need.
- Outside ultra-cheap, if the task mentions an "artifact", "report", "dashboard", "page", "infographic", "interactive", or "visualization" — the deliverable is a structured HTML document with multiple compliance rules (HTML wrapping, image embedding, no markdown leaks). Lean to at least `low` thinking (never `minimal`) and prefer a mid-tier model option.

You MUST pick an option from the list verbatim. Do not invent provider/model names.\
"""


def _force_choice() -> RouterChoice | None:
    """Parse ROUTER_FORCE=provider:model[:thinking]. Model may contain colons (e.g. qwen3.5:9b).

    Strategy: provider is the first token; if the last token is a valid thinking level,
    treat it as thinking and join the middle as the model; otherwise the whole rest is the model."""
    raw = os.environ.get("ROUTER_FORCE", "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    provider = parts[0]
    valid_thinking = {"none", "minimal", "low", "medium", "high"}
    if parts[-1].lower() in valid_thinking and len(parts) > 2:
        thinking = parts[-1].lower()
        model = ":".join(parts[1:-1])
    else:
        thinking = "medium"
        model = ":".join(parts[1:])
    return RouterChoice(provider=provider, model=model, thinking=thinking)


async def pick(req: RoutingRequest) -> RouterChoice:
    """Pick (provider, model, thinking) for this delegation seam.

    Falls back to the band's first option with thinking=none on any failure."""
    forced = _force_choice()
    if forced is not None:
        _log(Category.AGENT, "router forced", **forced.model_dump())
        return forced

    options = load_tier_options(req.tier)
    if not options:
        # No options configured — caller should fall back to tier's static `coder` entry.
        raise ValueError(f"No router options configured for tier {req.tier!r}")
    valid_pairs = {(o.provider.value, o.model) for o in options}

    prompt = _format_request(req, options)
    try:
        choice = await _picker().complete(
            prompt,
            instructions=_INSTRUCTIONS,
            thinking=ThinkingLevel.MINIMAL,
            response_model=RouterChoice,
        )
        if (choice.provider, choice.model) not in valid_pairs:
            _log(Category.AGENT, "router invalid pick, retrying",
                 provider=choice.provider, model=choice.model, valid=list(valid_pairs))
            stricter = (
                f"You picked {choice.provider}/{choice.model} which is NOT in the list. "
                f"Pick exactly one of:\n{_format_options(options)}"
            )
            choice = await _picker().complete(
                prompt + "\n\n" + stricter,
                instructions=_INSTRUCTIONS,
                thinking=ThinkingLevel.MINIMAL,
                response_model=RouterChoice,
            )
        if (choice.provider, choice.model) not in valid_pairs:
            raise ValueError(f"router still invalid after retry: {choice.provider}/{choice.model}")
        _log(Category.AGENT, "router picked",
             seam=req.seam, tier=req.tier,
             provider=choice.provider, model=choice.model, thinking=choice.thinking)
        return choice
    except Exception as e:
        first = options[0]
        fallback = RouterChoice(provider=first.provider.value, model=first.model)
        _log(Category.AGENT, "router fallback",
             seam=req.seam, tier=req.tier, error=str(e)[:200], **fallback.model_dump())
        return fallback


def make_client(choice: RouterChoice, tier: str | None = None) -> AiClient:
    """Build (or reuse) an AiClient for the chosen (provider, model).

    If `tier` is given AND the chosen option has a `fallback` configured in tiers.json,
    wraps the client in a FallbackClient that quietly swaps to the fallback model
    on 503/UNAVAILABLE. Pass `tier=None` for picker-only flows that don't need fallback."""
    primary = get_or_create_client(ModelProvider(choice.provider), choice.model)
    if tier is None:
        return primary
    options = load_tier_options(tier)
    fb_target = next(
        (o.fallback for o in options
         if o.provider.value == choice.provider and o.model == choice.model),
        None,
    )
    if fb_target is None:
        return primary
    from core.ai_client.fallback_client import FallbackClient
    fallback = get_or_create_client(fb_target.provider, fb_target.model)
    return FallbackClient(primary, fallback)
