"""Model pricing registry — USD per 1M tokens.

Add new models here when onboarding them. Local models have zero cost.
Prices sourced May 2026 from each provider's official pricing page.
"""

# (input_per_1m, output_per_1m, cached_input_per_1m)
# cached_input is the cache-read/hit rate, NOT cache-write/storage.
_COSTS: dict[str, tuple[float, float, float]] = {
    # OpenAI (standard short-context tier)
    "gpt-5.4-nano":  (0.20,  1.25, 0.02),
    "gpt-5.4-mini":  (0.75,  4.50, 0.075),
    "gpt-5.4":       (2.50, 15.00, 0.25),
    "gpt-5.5":       (5.00, 30.00, 0.50),
    # Google Gemini (standard tier; pro tiers price 2x past 200K prompts)
    "gemini-2.5-flash-lite":         (0.10,  0.40, 0.01),
    "gemini-2.5-flash":              (0.30,  2.50, 0.03),
    "gemini-2.5-pro":                (1.25, 10.00, 0.125),
    "gemini-3.1-flash-lite-preview": (0.25,  1.50, 0.025),
    "gemini-3.5-flash":              (1.50,  9.00, 0.15),
    "gemini-3.1-pro-preview":        (2.00, 12.00, 0.20),
    # Anthropic Claude
    "claude-haiku-4-5":  (1.00,  5.00, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-opus-4-7":   (5.00, 25.00, 0.50),
    # Local — free
    "gemma4:e4b":  (0.0, 0.0, 0.0),
    "qwen3.5:9b":  (0.0, 0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """USD cost for a call. `cached_tokens` is the subset of `input_tokens` that hit cache."""
    inp, out, cached = _COSTS.get(model, (0.0, 0.0, 0.0))
    uncached_input = max(input_tokens - cached_tokens, 0)
    return (inp * uncached_input + cached * cached_tokens + out * output_tokens) / 1_000_000


def format_cost(usd: float) -> str:
    """Format a USD cost for display."""
    if usd == 0.0:
        return "$0.00"
    if usd < 0.0001:
        return f"<$0.0001"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"
