import json
import logging
from typing import Any

from ollama import AsyncClient

from core.ai_client.interface import AiClient, EmbeddingClient, _execute_tools
from core.ai_client.models import EmbeddingModel, ImageContent, ThinkingLevel, Tool
from core.debug import trace as _dtrace
from core import transcripts

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemma4:e4b"
# qwen3.5:9b is an alternative — better reasoning but slower and needs nudge fix for empty responses

# Maps EmbeddingModel → (ollama model name, native max dimensions)
# All three models use Matryoshka Representation Learning (MRL) — prefix truncation
# (e[:N]) produces a valid embedding at any N ≤ native dims. Only add models here
# that are confirmed MRL-trained; standard models produce poor results when sliced.
_EMBED_MODELS: dict[EmbeddingModel, tuple[str, int]] = {
    EmbeddingModel.NOMIC: ("nomic-embed-text-v2-moe", 768),
    EmbeddingModel.QWEN:  ("qwen3-embedding:0.6b",    1024),
    EmbeddingModel.GEMMA: ("embeddinggemma",           768),
}

_MAX_TURNS = 50


class OllamaEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        model: EmbeddingModel = EmbeddingModel.NOMIC,
        host: str = "http://localhost:11434",
        dimensions: int | None = None,
    ) -> None:
        self._client = AsyncClient(host=host)
        ollama_name, native_dims = _EMBED_MODELS[model]
        self._model = ollama_name
        self._dimensions = dimensions or native_dims

    async def embed(self, *texts: str) -> list[list[float]]:
        response = await self._client.embed(model=self._model, input=list(texts))
        return [e[: self._dimensions] for e in response.embeddings]


class OllamaClient(AiClient):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        num_ctx: int = 32_768,
        model_name: str | None = None,
    ) -> None:
        super().__init__()
        self._client = AsyncClient(host=host)
        self._num_ctx = num_ctx
        self.model_name = model_name or _DEFAULT_MODEL

    def _options(self) -> dict[str, Any]:
        return {"num_ctx": self._num_ctx}

    def _tool_defs(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def _text_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,  # not supported locally — ignored
        code_execution: bool,  # not supported locally — ignored
        images: list[ImageContent] = (),
    ) -> str:
        messages: list[dict[str, Any]] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        # Ollama chat takes images as base64 strings on the user message.
        # Only vision-capable models (qwen3-vl, llava, etc.) will use them — text-only models silently ignore.
        user_msg: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            import base64 as _b64
            user_msg["images"] = [_b64.b64encode(img.data).decode("ascii") for img in images]
        messages.append(user_msg)

        tool_map = {t.name: t for t in tools}
        kwargs: dict[str, Any] = {"model": self.model_name, "options": self._options()}
        if tools:
            kwargs["tools"] = self._tool_defs(tools)
        # Ollama maps ThinkingLevel to a binary toggle (no budget concept).
        # Must pass explicitly — Qwen3 thinks by default if omitted.
        kwargs["think"] = thinking is not None

        _dtrace("ollama.call", model=self.model_name, think=kwargs["think"], tools=[t.name for t in tools])
        _dtrace("ollama.system", content=instructions or "(none)")
        _dtrace("ollama.user", content=prompt)

        completion_tokens = 0
        for inner_turn in range(_MAX_TURNS):
            response = await self._client.chat(messages=messages, **kwargs)
            msg = response.message
            completion_tokens += response.eval_count or 0
            transcripts.dump(model=self.model_name, iteration=inner_turn, instructions=instructions,
                             input_payload=messages, output=msg,
                             usage={"input": response.prompt_eval_count or 0, "output": response.eval_count or 0})

            if not msg.tool_calls:
                if msg.content:
                    _dtrace("ollama.response", turn=inner_turn, content=msg.content)
                    input_tokens = response.prompt_eval_count or 0
                    return msg.content, input_tokens, completion_tokens, 0
                # Qwen3 sometimes returns empty after tool use — nudge for final answer
                _dtrace("ollama.response", turn=inner_turn, content="<empty> — nudging")
                messages.append({"role": "assistant", "content": ""})
                messages.append({"role": "user", "content": "Please provide your final answer."})
                continue

            _dtrace("ollama.tool_calls", turn=inner_turn, calls=[
                f"{tc.function.name}({tc.function.arguments})" for tc in msg.tool_calls
            ])
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})
            calls = [
                (tc.function.name, tc.function.arguments if isinstance(tc.function.arguments, dict) else json.loads(tc.function.arguments))
                for tc in msg.tool_calls
            ]
            for result in await _execute_tools(tool_map, calls):
                _dtrace("ollama.tool_result", result=result)
                messages.append({"role": "tool", "content": result})

        raise RuntimeError(f"Tool loop exceeded {_MAX_TURNS} turns")  # pragma: no cover

    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any:
        messages: list[dict[str, Any]] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "format": response_model.model_json_schema(),
            "options": self._options(),
        }
        kwargs["think"] = thinking is not None

        response = await self._client.chat(**kwargs)
        return response_model.model_validate_json(response.message.content)
