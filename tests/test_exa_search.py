from types import SimpleNamespace

from core.tools.exa_search import _format_results
from core.text import tokens


def test_format_results_preserves_sources_and_full_highlights_when_under_budget():
    results = [
        SimpleNamespace(
            title="A",
            url="https://example.com/a",
            highlights=["x" * 2_000, "short", "third", "fourth"],
        ),
        SimpleNamespace(
            title="B",
            url="https://example.com/b",
            highlights=[],
        ),
    ]

    out = _format_results(results)

    assert [r["url"] for r in out] == ["https://example.com/a", "https://example.com/b"]
    assert out[0]["highlights"] == ["x" * 2_000, "short", "third", "fourth"]
    assert out[1]["highlights"] == []


def test_format_results_trims_highlights_only_when_total_output_is_too_large():
    results = [
        SimpleNamespace(title="A", url="https://example.com/a", highlights=["alpha " * 2_000]),
        SimpleNamespace(title="B", url="https://example.com/b", highlights=["beta " * 2_000]),
    ]

    out = _format_results(results, max_output_tokens=500)
    text = str(out)

    assert [r["url"] for r in out] == ["https://example.com/a", "https://example.com/b"]
    assert tokens(text) <= 500
    assert all("chars truncated" in r["highlights"][0] for r in out)
    assert all("highlights_truncated" not in r for r in out)
    assert all("highlight_char_limit" not in r for r in out)
