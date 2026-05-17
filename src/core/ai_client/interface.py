import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel, ValidationError

from core.ai_client.models import CodeExecution, ImageContent, ThinkingLevel, Tool, WebSearch

T = TypeVar("T", bound=BaseModel)

_RETRY_DELAYS = (0.0, 1.0, 2.0, 4.0)


class EmbeddingClient(ABC):
    @abstractmethod
    async def embed(self, *texts: str) -> list[list[float]]: ...


class AiClient(ABC):
    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        # Subclasses set this to the fixed model name from tiers.json.
        self.model_name: str = ""

    @property
    def provider(self) -> str:
        """Short provider name for logging — e.g. 'ollama', 'openai', 'claude', 'gemini'."""
        name = type(self).__name__.lower()
        return name.replace("client", "")  # OllamaClient → ollama, OpenAiClient → openai

    @overload
    async def complete(
        self,
        prompt: str,
        *,
        instructions: str | None = None,
        response_model: None = None,
        web_search: WebSearch | None = None,
        thinking: ThinkingLevel | None = None,
        extra_tools: list[Tool] | None = None,
        code_execution: CodeExecution | None = None,
        images: list[ImageContent] | None = None,
    ) -> str: ...

    @overload
    async def complete(
        self,
        prompt: str,
        *,
        instructions: str | None = None,
        response_model: type[T],
        web_search: WebSearch | None = None,
        thinking: ThinkingLevel | None = None,
        extra_tools: list[Tool] | None = None,
        code_execution: CodeExecution | None = None,
        images: list[ImageContent] | None = None,
    ) -> T: ...

    async def complete(  # type: ignore[override]
        self,
        prompt: str,
        *,
        instructions: str | None = None,
        response_model: type[T] | None = None,
        web_search: WebSearch | None = None,
        thinking: ThinkingLevel | None = None,
        extra_tools: list[Tool] | None = None,
        code_execution: CodeExecution | None = None,
        images: list[ImageContent] | None = None,
    ) -> str | T:
        tools: list[Tool] = list(extra_tools) if extra_tools else []
        native_search = web_search == WebSearch.NATIVE

        run_code = code_execution is not None
        has_active_tools = bool(tools) or run_code
        imgs = images or []

        if response_model is None:
            text, _ = await self._timed_text_complete(
                prompt, instructions=instructions, thinking=thinking,
                tools=tools, native_search=native_search, code_execution=run_code,
                images=imgs,
            )
            return text

        if not has_active_tools and not native_search:
            from core.log import Category
            from core.log import log as _log
            start = time.monotonic()
            result = await _with_retry(
                lambda: self._structured_complete(
                    prompt,
                    instructions=instructions,
                    thinking=thinking,
                    response_model=response_model,
                ),
                (ValidationError,),
            )
            _log(Category.AGENT, "llm call", ui=False, model=self.model_name, provider=self.provider,
                 thinking=str(thinking) if thinking else None,
                 elapsed_s=round(time.monotonic() - start, 3))
            return result

        # Two-step: tool loop → parse JSON from final text
        schema_str = json.dumps(response_model.model_json_schema(), indent=2)
        effective_instructions = (
            (instructions or "")
            + f"\n\nReturn your final answer as a JSON object matching this exact schema:\n"
            f"{schema_str}\n\nOutput only the JSON object, no surrounding text."
        )

        async def _attempt() -> T:
            text, _ = await self._timed_text_complete(
                prompt, instructions=effective_instructions, thinking=thinking,
                tools=tools, native_search=native_search, code_execution=run_code,
                images=imgs,
            )
            return _parse_json(text, response_model)

        return await _with_retry(_attempt, (ValidationError, json.JSONDecodeError, ValueError))

    async def _timed_text_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,
        code_execution: bool,
        images: list[ImageContent] | None = None,
    ) -> tuple[str, int]:
        """Wraps _text_complete with timing, usage logging, and token accumulation."""
        from core.log import Category
        from core.log import log as _log
        start = time.monotonic()
        text, input_tokens, completion_tokens = await self._text_complete(
            prompt, instructions=instructions, thinking=thinking,
            tools=tools, native_search=native_search, code_execution=code_execution,
            images=images or [],
        )
        elapsed = round(time.monotonic() - start, 3)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += completion_tokens
        try:
            from core.agents.task_ctx import TASK_USAGE_LOG
            TASK_USAGE_LOG.get().append((self.model_name or "", input_tokens, completion_tokens))
        except LookupError:
            pass
        _log(
            Category.AGENT, "llm call", ui=False,
            model=self.model_name, provider=self.provider,
            thinking=str(thinking) if thinking else None,
            input_tokens=input_tokens, completion_tokens=completion_tokens, elapsed_s=elapsed,
            images=len(images) if images else 0,
        )
        return text, completion_tokens

    @abstractmethod
    async def _text_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,
        code_execution: bool,
        images: list[ImageContent] = ...,
    ) -> tuple[str, int, int]: ...  # (text, input_tokens, output_tokens)

    @abstractmethod
    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any: ...


async def _execute_tools(
    tool_map: dict[str, Tool],
    calls: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Execute tool calls with safe-first parallelization.

    Phase 1: concurrency-safe tools (reads, status checks) run in parallel.
    Phase 2: unsafe tools (writes, commits) run serially in emitted order.
    Results are returned in original call order so callers can zip with IDs.
    """
    results: list[str] = [""] * len(calls)
    safe_idx = [
        i for i, (name, _) in enumerate(calls)
        if tool_map.get(name) and tool_map[name].is_concurrency_safe
    ]
    unsafe_idx = [i for i in range(len(calls)) if i not in set(safe_idx)]

    async def _run(i: int) -> tuple[int, str]:
        name, args = calls[i]
        res = await tool_map[name].fn(**args) if name in tool_map else f"Unknown tool: {name}"
        return i, res

    for idx, result in await asyncio.gather(*[_run(i) for i in safe_idx]):
        results[idx] = result

    for i in unsafe_idx:
        _, result = await _run(i)
        results[i] = result

    return results


async def _with_retry(
    fn: Any,
    exceptions: tuple[type[Exception], ...],
) -> Any:
    last_err: Exception | None = None
    for i, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await fn()
        except exceptions as e:
            last_err = e
            if i == len(_RETRY_DELAYS) - 1:
                raise
    raise last_err  # type: ignore[misc]


def _parse_json(text: str, model: type[T]) -> T:
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        return model.model_validate_json(m.group(1))
    return model.model_validate_json(text.strip())
