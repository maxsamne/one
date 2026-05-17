"""Public AiClient/EmbeddingClient factory.

Thin wrapper around `tiers.get_or_create_client` so there's a single dispatch path:
factory → tiers cache → per-provider builder. Cloud providers require model_name;
Ollama falls back to the OllamaClient default if omitted.
"""

from core.ai_client.interface import AiClient, EmbeddingClient
from core.ai_client.models import EmbeddingModel, ModelProvider
from core.ai_client.tiers import get_or_create_client


def create_client(provider: ModelProvider, *, model_name: str | None = None) -> AiClient:
    """Return the cached AiClient for (provider, model_name).

    For cloud providers, `model_name` is required. For Ollama, omitting it uses
    the OllamaClient default model.
    """
    if provider is ModelProvider.OLLAMA and not model_name:
        from core.ai_client.ollama_client import _DEFAULT_MODEL
        model_name = _DEFAULT_MODEL
    if not model_name:
        raise ValueError(f"model_name is required for provider {provider.value!r}")
    return get_or_create_client(provider, model_name)


def create_embedding_client(
    model: EmbeddingModel = EmbeddingModel.QWEN,
    dimensions: int | None = None,
) -> EmbeddingClient:
    """Create an EmbeddingClient — all current models run locally via Ollama."""
    from core.ai_client.ollama_client import OllamaEmbeddingClient
    return OllamaEmbeddingClient(model=model, dimensions=dimensions)
