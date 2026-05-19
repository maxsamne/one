from typing import Any

from google import genai
from google.genai import types

from core.ai_client.interface import AiClient, EmbeddingClient, _execute_tools
from core.ai_client.models import ImageContent, ThinkingLevel, Tool
from core import transcripts


def _user_contents(prompt: str, images: list[ImageContent]) -> Any:
    """Build Gemini contents. Returns the prompt string when no images, else list of Parts."""
    if not images:
        return prompt
    parts: list[types.Part] = [types.Part.from_text(text=prompt)]
    for img in images:
        parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime))
    return [types.Content(parts=parts, role="user")]


_JSON_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}

_MAX_TURNS = 50

# Pro model doesn't support MINIMAL thinking — clamp to LOW.
_NO_MINIMAL_THINKING = {"gemini-3.1-pro-preview"}


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema to Gemini's uppercase-type format (for function declarations only)."""
    result: dict[str, Any] = {}
    if t := schema.get("type"):
        result["type"] = _JSON_TYPE_MAP.get(t, t.upper())
    if d := schema.get("description"):
        result["description"] = d
    if props := schema.get("properties"):
        result["properties"] = {k: _to_gemini_schema(v) for k, v in props.items()}
    if req := schema.get("required"):
        result["required"] = req
    if items := schema.get("items"):
        result["items"] = _to_gemini_schema(items)
    return result


class GeminiClient(AiClient):
    def __init__(self, api_key: str, model_name: str) -> None:
        super().__init__()
        self._client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def _build_config(
        self,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,
        code_execution: bool,
    ) -> types.GenerateContentConfig:
        gemini_tools: list[Any] = []
        if tools:
            gemini_tools.append(types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=_to_gemini_schema(t.parameters),
                )
                for t in tools
            ]))
        if native_search:
            gemini_tools.append(types.Tool(google_search=types.GoogleSearch()))
        if code_execution:
            gemini_tools.append(types.Tool(code_execution=types.ToolCodeExecution()))

        kwargs: dict[str, Any] = {}
        if instructions:
            kwargs["system_instruction"] = instructions
        if thinking:
            effective = ThinkingLevel.LOW if (thinking == ThinkingLevel.MINIMAL and self.model_name in _NO_MINIMAL_THINKING) else thinking
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=effective.value)
        if gemini_tools:
            kwargs["tools"] = gemini_tools
        return types.GenerateContentConfig(**kwargs)

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
    ) -> tuple[str, int, int]:
        config = self._build_config(instructions, thinking, tools, native_search, code_execution)

        user_contents = _user_contents(prompt, list(images))

        if not tools:
            response = await self._client.aio.models.generate_content(
                model=self.model_name, contents=user_contents, config=config
            )
            meta = response.usage_metadata
            inp = (meta.prompt_token_count or 0) if meta else 0
            out = (meta.candidates_token_count or 0) if meta else 0
            cached = (getattr(meta, "cached_content_token_count", 0) or 0) if meta else 0
            transcripts.dump(model=self.model_name, iteration=0, instructions=instructions,
                             input_payload=user_contents, output=response.text,
                             usage={"input": inp, "output": out, "cached": cached})
            return response.text or "", inp, out, cached

        tool_map = {t.name: t for t in tools}
        contents: list[Any] = list(user_contents) if isinstance(user_contents, list) else [user_contents]
        input_tokens = 0
        completion_tokens = 0
        cached_tokens = 0

        for i in range(_MAX_TURNS):
            response = await self._client.aio.models.generate_content(
                model=self.model_name, contents=contents, config=config
            )
            meta = response.usage_metadata
            iter_in = (meta.prompt_token_count or 0) if meta else 0
            iter_out = (meta.candidates_token_count or 0) if meta else 0
            iter_cached = (getattr(meta, "cached_content_token_count", 0) or 0) if meta else 0
            input_tokens += iter_in
            completion_tokens += iter_out
            cached_tokens += iter_cached
            transcripts.dump(model=self.model_name, iteration=i, instructions=instructions,
                             input_payload=contents, output=response.candidates[0].content if response.candidates else None,
                             usage={"input": iter_in, "output": iter_out, "cached": iter_cached})
            candidate = response.candidates[0]
            fn_calls = [
                part.function_call
                for part in candidate.content.parts
                if getattr(part, "function_call", None)
            ]
            if not fn_calls:
                return response.text or "", input_tokens, completion_tokens, cached_tokens

            calls = [(fc.name, dict(fc.args)) for fc in fn_calls]
            results = await _execute_tools(tool_map, calls)
            fn_response_parts = [
                types.Part(function_response=types.FunctionResponse(name=fc.name, response={"result": r}))
                for fc, r in zip(fn_calls, results)
                if fc.name in tool_map
            ]
            contents = [*contents, candidate.content, types.Content(parts=fn_response_parts, role="user")]

        raise RuntimeError(f"Tool loop exceeded {_MAX_TURNS} turns")

    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any:
        kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": response_model.model_json_schema(),
        }
        if instructions:
            kwargs["system_instruction"] = instructions
        if thinking:
            effective = ThinkingLevel.LOW if (thinking == ThinkingLevel.MINIMAL and self.model_name in _NO_MINIMAL_THINKING) else thinking
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=effective.value)

        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(**kwargs),
        )
        return response_model.model_validate_json(response.text)


class GeminiEmbeddingClient(EmbeddingClient):
    _MODEL = "gemini-embedding-2-preview"

    def __init__(self, api_key: str, dimensions: int = 1536) -> None:
        self._client = genai.Client(api_key=api_key)
        self._config = types.EmbedContentConfig(output_dimensionality=dimensions)

    async def embed(self, *texts: str) -> list[list[float]]:
        responses = await self._client.aio.models.embed_content(
            model=self._MODEL,
            contents=list(texts),
            config=self._config,
        )
        return [e.values for e in responses.embeddings]
