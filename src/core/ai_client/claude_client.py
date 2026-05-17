import base64
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from core.ai_client.interface import AiClient, _execute_tools
from core.ai_client.models import THINKING_BUDGETS, ImageContent, ThinkingLevel, Tool


def _user_content(prompt: str, images: list[ImageContent]) -> Any:
    """Build Claude user-message content. Returns a string when no images, list of blocks otherwise."""
    if not images:
        return prompt
    blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img in images:
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img.mime, "data": base64.b64encode(img.data).decode("ascii")},
        })
    return blocks

logger = logging.getLogger(__name__)

_OUTPUT_BUFFER = 8_192
_MAX_NUDGES = 10


class ClaudeClient(AiClient):
    def __init__(self, api_key: str, model_name: str) -> None:
        super().__init__()
        self._client = AsyncAnthropic(api_key=api_key)
        self.model_name = model_name

    def _base_params(self, thinking: ThinkingLevel | None) -> dict[str, Any]:
        params: dict[str, Any] = {"max_tokens": _OUTPUT_BUFFER}
        if thinking:
            budget = THINKING_BUDGETS[thinking]
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["max_tokens"] = budget + _OUTPUT_BUFFER
        return params

    async def _text_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,
        code_execution: bool,
        images: list[ImageContent] = (),
    ) -> str:
        params = self._base_params(thinking)

        claude_tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        if native_search:
            claude_tools.insert(0, {"type": "web_search_20250305", "name": "web_search", "max_uses": 100})
        if code_execution:
            claude_tools.append({"type": "code_execution_20250825", "name": "code_execution"})

        if claude_tools:
            params["tools"] = claude_tools

        messages: list[dict[str, Any]] = [{"role": "user", "content": _user_content(prompt, list(images))}]
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages, **params}
        if instructions:
            kwargs["system"] = instructions

        if not tools:
            resp = await self._client.messages.create(**kwargs)
            text_blocks = [b for b in resp.content if b.type == "text"]
            return text_blocks[0].text if text_blocks else "", resp.usage.input_tokens, resp.usage.output_tokens

        tool_map = {t.name: t for t in tools}
        input_tokens = 0
        completion_tokens = 0
        while True:
            resp = await self._client.messages.create(**kwargs)
            input_tokens += resp.usage.input_tokens
            completion_tokens += resp.usage.output_tokens

            if resp.stop_reason == "tool_use":
                use_blocks = [b for b in resp.content if b.type == "tool_use"]
                results = await _execute_tools(tool_map, [(b.name, dict(b.input)) for b in use_blocks])
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": r}
                    for b, r in zip(use_blocks, results)
                ]})
            else:
                text_blocks = [b for b in resp.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else "", input_tokens, completion_tokens

    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any:
        params = self._base_params(thinking)
        schema = {k: v for k, v in response_model.model_json_schema().items() if k != "title"}

        params["tools"] = [{"name": "respond", "description": "Provide the structured response.", "input_schema": schema}]
        # tool_choice "tool" is incompatible with extended thinking — use auto in that case
        params["tool_choice"] = {"type": "auto"} if thinking else {"type": "tool", "name": "respond"}

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages, **params}
        if instructions:
            kwargs["system"] = instructions

        for _ in range(_MAX_NUDGES):
            resp = await self._client.messages.create(**kwargs)
            messages.append({"role": "assistant", "content": resp.content})

            for block in resp.content:
                if block.type == "tool_use" and block.name == "respond":
                    try:
                        return response_model.model_validate(block.input)
                    except ValidationError as e:
                        logger.warning("Claude structured: validation failed, nudging: %s", e)
                        messages.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Incomplete — retry respond with all required fields. Error: {e}",
                                "is_error": True,
                            }],
                        })
                        break
            else:
                raise ValueError("No respond tool_use block in Claude response")

        raise ValueError("Claude structured: max nudges reached")
