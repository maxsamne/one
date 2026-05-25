"""Shared tool-output budgeting for provider tool loops."""

from core.text import tokens as _count_tokens

MAX_TOOL_RESULT_TOKENS = 8_000
MAX_TOOL_RESULT_BATCH_TOKENS = 12_000


def truncate_middle(text: str, max_tokens: int, *, marker: str) -> str:
    if _count_tokens(text) <= max_tokens:
        return text

    marker_tokens = _count_tokens(marker)
    if max_tokens <= marker_tokens:
        tiny = "[truncated]"
        return tiny if _count_tokens(tiny) <= max_tokens else ""

    keep_chars = max(1, (max_tokens - marker_tokens) * 4)
    half = keep_chars // 2
    truncated = text[:half] + marker + text[-half:]
    while _count_tokens(truncated) > max_tokens and half > 1:
        half = int(half * 0.8)
        truncated = text[:half] + marker + text[-half:]
    return truncated


def truncate_tool_result(result: str, max_tokens: int = MAX_TOOL_RESULT_TOKENS) -> str:
    marker = f"\n\n[tool output truncated to {max_tokens} tokens]\n\n"
    return truncate_middle(result, max_tokens, marker=marker)


def truncate_tool_results(
    results: list[str],
    *,
    max_result_tokens: int = MAX_TOOL_RESULT_TOKENS,
    max_batch_tokens: int = MAX_TOOL_RESULT_BATCH_TOKENS,
) -> list[str]:
    """Cap both individual tool outputs and the whole parallel-call batch."""
    if not results:
        return []

    raw_counts = [_count_tokens(r) for r in results]
    desired = [min(c, max_result_tokens) for c in raw_counts]
    if sum(desired) <= max_batch_tokens:
        return [truncate_tool_result(r, max_result_tokens) for r in results]

    remaining_budget = max_batch_tokens
    remaining = set(range(len(results)))
    allocations = [0] * len(results)

    while remaining:
        fair_share = max(1, remaining_budget // len(remaining))
        small = [i for i in remaining if desired[i] <= fair_share]
        if not small:
            break
        for i in small:
            allocations[i] = desired[i]
            remaining_budget -= desired[i]
            remaining.remove(i)

    if remaining:
        fair_share = max(1, remaining_budget // len(remaining))
        for i in remaining:
            allocations[i] = min(desired[i], fair_share)

    out: list[str] = []
    for result, allocated in zip(results, allocations):
        marker = (
            f"\n\n[tool output truncated to {allocated} tokens "
            f"by shared {max_batch_tokens}-token tool batch budget]\n\n"
        )
        out.append(truncate_middle(result, allocated, marker=marker))
    return out
