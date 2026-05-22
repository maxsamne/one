import base64
import json
from typing import Any

from openai import AsyncOpenAI

from core.ai_client.interface import AiClient, EmbeddingClient, _execute_tools
from core.ai_client.models import ImageContent, ThinkingLevel, Tool
from core.debug import trace as _dtrace
from core.tools.ctx import pop_pending_multimodal
from core import transcripts


def _cached(usage: Any) -> int:
    """Extract cached_tokens from OpenAI Responses usage. Returns 0 if absent."""
    if not usage:
        return 0
    details = getattr(usage, "input_tokens_details", None)
    return int(getattr(details, "cached_tokens", 0) or 0) if details else 0


def _user_input(prompt: str, images: list[ImageContent]) -> Any:
    """Build OpenAI Responses API input. Returns a string when no images, else a multimodal list."""
    if not images:
        return prompt
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for img in images:
        data_uri = f"data:{img.mime};base64,{base64.b64encode(img.data).decode('ascii')}"
        content.append({"type": "input_image", "image_url": data_uri})
    return [{"role": "user", "content": content}]

_MAX_TURNS = 50


class GptClient(AiClient):
    def __init__(self, api_key: str, model_name: str) -> None:
        super().__init__()
        self._client = AsyncOpenAI(api_key=api_key)
        self.model_name = model_name

    def _base_kwargs(self, thinking: ThinkingLevel | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model_name}
        if thinking:
            # gpt-5.4/5.5 family doesn't accept "minimal"; closest supported is "low"
            effort = "low" if thinking == ThinkingLevel.MINIMAL else thinking.value
            kwargs["reasoning"] = {"effort": effort}
        return kwargs

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
        base = self._base_kwargs(thinking)

        oai_tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]
        if native_search:
            oai_tools.append({"type": "web_search", "search_context_size": "medium"})
        if code_execution:
            oai_tools.append({"type": "code_interpreter", "container": {"type": "auto"}})

        if oai_tools:
            base["tools"] = oai_tools

        user_input = _user_input(prompt, list(images))

        resp = await self._client.responses.create(
            **base,
            input=user_input,
            instructions=instructions,
        )
        transcripts.dump(model=self.model_name, iteration=0,
                         instructions=instructions, input_payload=user_input, output=resp.output,
                         usage={"input": resp.usage.input_tokens if resp.usage else 0,
                                "cached": _cached(resp.usage),
                                "output": resp.usage.output_tokens if resp.usage else 0})

        if not tools:
            inp = resp.usage.input_tokens if resp.usage else 0
            out = resp.usage.output_tokens if resp.usage else 0
            cached = _cached(resp.usage)
            _dtrace(
                "gpt.iter",
                model=self.model_name, provider=self.provider,
                prompt_tokens=inp, completion_tokens=out,
                cached_tokens=cached,
                iter=1,
                input_list_len=1,
                tool_calls=[],
                images=len(images),
            )
            return resp.output_text or "", inp, out, cached

        tool_map = {t.name: t for t in tools}
        # For tool loop, input_list seeds with the same multimodal user message.
        input_list: list[Any] = list(user_input) if isinstance(user_input, list) else [{"role": "user", "content": prompt}]
        input_tokens = resp.usage.input_tokens if resp.usage else 0
        completion_tokens = resp.usage.output_tokens if resp.usage else 0
        cached_total = _cached(resp.usage)

        for i in range(_MAX_TURNS):
            fn_calls = [item for item in resp.output if getattr(item, "type", None) == "function_call"]
            _dtrace(
                "gpt.iter",
                model=self.model_name, provider=self.provider,
                prompt_tokens=resp.usage.input_tokens if resp.usage else 0,
                completion_tokens=resp.usage.output_tokens if resp.usage else 0,
                cached_tokens=_cached(resp.usage),
                iter=i + 1,
                input_list_len=len(input_list),
                tool_calls=[fc.name for fc in fn_calls],
                images=len(images) if i == 0 else 0,
            )
            if not fn_calls:
                _dtrace(
                    "gpt.loop_done",
                    model=self.model_name,
                    provider=self.provider,
                    iterations=i + 1,
                    input_tokens=input_tokens,
                    cached_tokens=cached_total,
                    output_tokens=completion_tokens,
                    cache_hit_pct=round(100 * cached_total / input_tokens, 1) if input_tokens else 0.0,
                )
                return resp.output_text or "", input_tokens, completion_tokens, cached_total

            input_list.extend(resp.output)
            calls = [(fc.name, json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments) for fc in fn_calls]
            results = await _execute_tools(tool_map, calls)
            for fc, result in zip(fn_calls, results):
                input_list.append({"type": "function_call_output", "call_id": fc.call_id, "output": result})
            pending_images = pop_pending_multimodal()
            if pending_images:
                input_list.extend(_user_input("Use these loaded website images as visual references for the next step.", pending_images))

            resp = await self._client.responses.create(**base, input=input_list, instructions=instructions)
            iter_input = resp.usage.input_tokens if resp.usage else 0
            iter_output = resp.usage.output_tokens if resp.usage else 0
            iter_cached = _cached(resp.usage)
            input_tokens += iter_input
            completion_tokens += iter_output
            cached_total += iter_cached
            transcripts.dump(model=self.model_name, iteration=i + 1,
                             instructions=instructions, input_payload=input_list, output=resp.output,
                             usage={"input": iter_input, "cached": iter_cached, "output": iter_output})

        raise RuntimeError(f"Tool loop exceeded {_MAX_TURNS} turns")

    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any:
        resp = await self._client.responses.parse(
            **self._base_kwargs(thinking),
            input=prompt,
            instructions=instructions,
            text_format=response_model,
        )
        if resp.output_parsed is None:
            raise ValueError("Failed to parse structured response")
        return resp.output_parsed


class GptEmbeddingClient(EmbeddingClient):
    _MODEL = "text-embedding-3-small"

    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def embed(self, *texts: str) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._MODEL, input=list(texts))
        return [e.embedding for e in response.data]
