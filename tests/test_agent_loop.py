from core.agents.loop import run_agent_loop
from core.ai_client.models import Tool


async def _noop_tool() -> str:
    return "ok"


def _parse_done(text: str) -> str:
    if not text.startswith("done:"):
        raise ValueError("not done")
    return text.removeprefix("done:")


async def test_agent_loop_retries_until_parser_succeeds():
    class _Client:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=None, **kw):
            self.calls.append({
                "prompt": prompt,
                "instructions": instructions,
                "tools": [t.name for t in extra_tools or []],
            })
            return "not yet" if len(self.calls) == 1 else "done:evidence"

    tool = Tool(
        name="read_only_probe",
        description="Probe",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_noop_tool,
        is_read_only=True,
    )
    client = _Client()

    result = await run_agent_loop(
        goal="Inspect something",
        client=client,
        instructions="Read only.",
        tools=[tool],
        max_turns=3,
        parse_response=_parse_done,
        retry_parse_exceptions=(ValueError,),
    )

    assert result.completed is True
    assert result.value == "evidence"
    assert result.turns == 2
    assert [call["tools"] for call in client.calls] == [["read_only_probe"], ["read_only_probe"]]
    assert client.calls[0]["instructions"] == "Read only."
    assert "Inspect something" in client.calls[0]["prompt"]
    assert "Continue." in client.calls[1]["prompt"]


async def test_agent_loop_uses_custom_compaction_instructions():
    class _Client:
        def __init__(self) -> None:
            self.compactions = 0
            self.calls = 0

        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=None, **kw):
            if instructions == "custom compact":
                self.compactions += 1
                return "compact summary"
            self.calls += 1
            return "not done" if self.calls < 8 else "done:ok"

    client = _Client()
    result = await run_agent_loop(
        goal="Inspect " + ("x" * 100),
        client=client,
        instructions="loop instructions",
        tools=[],
        max_turns=8,
        context_window=1,
        compact_instructions="custom compact",
        parse_response=_parse_done,
        retry_parse_exceptions=(ValueError,),
    )

    assert result.value == "ok"
    assert client.compactions >= 1
