from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable


class ModelProvider(StrEnum):
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Used by Claude only — maps thinking level to budget_tokens
THINKING_BUDGETS: dict[ThinkingLevel, int] = {
    ThinkingLevel.MINIMAL: 512,
    ThinkingLevel.LOW: 1_024,
    ThinkingLevel.MEDIUM: 8_000,
    ThinkingLevel.HIGH: 32_000,
}


class EmbeddingModel(StrEnum):
    NOMIC = "nomic"   # nomic-embed-text-v2-moe — 768 dims, general text
    QWEN  = "qwen"    # qwen3-embedding:0.6b    — 1024 dims, code + multilingual
    GEMMA = "gemma"   # embeddinggemma          — 768 dims, Google-tuned


class WebSearch(StrEnum):
    NATIVE = "native"


class CodeExecution(StrEnum):
    NATIVE = "native"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    fn: Callable[..., Awaitable[str]]
    is_read_only: bool = False        # true → no filesystem/state side effects
    is_concurrency_safe: bool = False # true → safe to run in parallel with other tools


@dataclass(frozen=True)
class ImageContent:
    """Raw image bytes + MIME type. Each AiClient encodes for its provider's wire format.

    Pass to `complete()` via the `images` parameter — they're attached to the user message
    of the call. Use sparingly: each image typically costs 1-3K tokens. The coder loop only
    passes images on turn 0 to keep recurring cost flat."""
    mime: str    # "image/png", "image/jpeg", "image/webp", "image/gif"
    data: bytes  # raw bytes, NOT base64
