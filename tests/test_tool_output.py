from core.ai_client.interface import _execute_tools
from core.ai_client.models import Tool
from core.ai_client.tool_output import truncate_tool_result, truncate_tool_results
from core.text import tokens


def test_truncate_tool_result_preserves_head_tail_and_caps_tokens():
    content = "HEAD " + ("middle " * 20_000) + " TAIL"

    out = truncate_tool_result(content, max_tokens=1_000)

    assert tokens(out) <= 1_000
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert "tool output truncated to 1000 tokens" in out


def test_truncate_tool_result_leaves_small_results_unchanged():
    assert truncate_tool_result("small", max_tokens=1_000) == "small"


def test_truncate_tool_results_caps_batch_not_just_each_result():
    results = [
        "A " + ("one " * 10_000),
        "B " + ("two " * 10_000),
        "tiny",
    ]

    out = truncate_tool_results(results, max_result_tokens=2_000, max_batch_tokens=2_500)

    assert sum(tokens(item) for item in out) <= 2_500
    assert out[2] == "tiny"
    assert "shared 2500-token tool batch budget" in out[0]
    assert "shared 2500-token tool batch budget" in out[1]


async def test_execute_tools_applies_shared_batch_cap():
    async def big(label: str) -> str:
        return label + " " + ("chunk " * 10_000)

    tool = Tool(
        name="big",
        description="large output",
        parameters={
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
        },
        fn=big,
        is_read_only=True,
        is_concurrency_safe=True,
    )

    out = await _execute_tools({"big": tool}, [("big", {"label": "A"}), ("big", {"label": "B"})])

    assert sum(tokens(item) for item in out) <= 12_000
    assert all("shared 12000-token tool batch budget" in item for item in out)
