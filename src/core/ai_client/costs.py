"""Model pricing registry — USD per 1M tokens.

Add new models here when onboarding them. Local models have zero cost.
Prices sourced April 2026 from provider pricing pages.
"""

# (input_per_1m_usd, output_per_1m_usd)
_COSTS: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-5.4-nano":  (0.20,  1.25),
    "gpt-5.4-mini":  (0.40,  1.60),
    "gpt-5.4":       (2.00,  8.00),
    "gpt-5.5":       (5.00, 20.00),
    # Gemini
    "gemini-2.5-flash-lite":         (0.10,  0.40),
    "gemini-2.5-flash":              (0.30,  2.50),
    "gemini-2.5-pro":                (1.25, 10.00),
    "gemini-3.1-flash-lite-preview": (0.25,  1.50),
    "gemini-3-flash-preview":        (0.50,  3.00),
    "gemini-3.1-pro-preview":        (2.00, 12.00),
    # Local — free
    "gemma4:e4b":  (0.0, 0.0),
    "qwen3.5:9b":  (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost for a given number of input and output tokens."""
    inp, out = _COSTS.get(model, (0.0, 0.0))
    return (inp * input_tokens + out * output_tokens) / 1_000_000


def format_cost(usd: float) -> str:
    """Format a USD cost for display."""
    if usd == 0.0:
        return "$0.00"
    if usd < 0.0001:
        return f"<$0.0001"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"
