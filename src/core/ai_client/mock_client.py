from typing import Any

from pydantic import BaseModel

from core.ai_client.interface import AiClient, EmbeddingClient
from core.ai_client.models import ImageContent, ThinkingLevel, Tool


class MockClient(AiClient):
    """Drop-in replacement for tests. Configure with canned responses."""

    def __init__(
        self,
        text: str = "mock response",
        structured: BaseModel | None = None,
        model_name: str = "mock",
    ) -> None:
        super().__init__()
        self._text = text
        self._structured = structured
        self.model_name = model_name
        self.calls: list[dict[str, Any]] = []

    async def _text_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        tools: list[Tool],
        native_search: bool,
        code_execution: bool,  # bool here since interface converts CodeExecution enum to bool before calling
        images: list[ImageContent] = (),
    ) -> str:
        self.calls.append({"prompt": prompt, "model": self.model_name, "thinking": thinking, "type": "text", "images": len(images)})
        return self._text

    async def _structured_complete(
        self,
        prompt: str,
        *,
        instructions: str | None,
        thinking: ThinkingLevel | None,
        response_model: type[Any],
    ) -> Any:
        self.calls.append({"prompt": prompt, "model": self.model_name, "thinking": thinking, "type": "structured"})
        if self._structured is not None:
            return self._structured
        raise NotImplementedError("Configure MockClient(structured=...) to return structured data")


class MockEmbeddingClient(EmbeddingClient):
    """Returns zero vectors for testing."""

    def __init__(self, dim: int = 1536) -> None:
        self._dim = dim

    async def embed(self, *texts: str) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]
