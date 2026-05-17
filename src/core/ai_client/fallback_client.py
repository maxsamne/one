"""FallbackClient — try primary, swap to fallback on 503/UNAVAILABLE.

The wrapped clients accumulate their own token counts. Each LLM call is
independent: a successful primary call does not "remember" a previous failure;
a previous successful fallback does not bias the next call away from primary.
Per-call only — keep it simple.
"""

from __future__ import annotations

from typing import Any

from core.ai_client.interface import AiClient
from core.log import Category
from core.log import log as _log


def is_unavailable(exc: BaseException) -> bool:
    s = str(exc)
    return "503" in s or "UNAVAILABLE" in s or "unavailable" in s.lower() or "overloaded" in s.lower()


class FallbackClient(AiClient):
    """Wraps two AiClients. complete() tries primary, falls through to fallback on 503."""

    def __init__(self, primary: AiClient, fallback: AiClient) -> None:
        super().__init__()
        self.primary = primary
        self.fallback = fallback
        # model_name shown as "primary" so logs read naturally; cost accounting reads
        # from the underlying clients' counters which land where work actually happened.
        self.model_name = primary.model_name

    @property
    def provider(self) -> str:
        return self.primary.provider

    async def complete(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        try:
            return await self.primary.complete(*args, **kwargs)
        except Exception as e:
            if not is_unavailable(e):
                raise
            _log(
                Category.AGENT, "fallback model swap",
                primary=f"{self.primary.provider}/{self.primary.model_name}",
                fallback=f"{self.fallback.provider}/{self.fallback.model_name}",
                error=str(e)[:160],
            )
            return await self.fallback.complete(*args, **kwargs)

    # Abstract-method stubs — never called because we override complete() above.
    async def _text_complete(self, *args: Any, **kwargs: Any) -> tuple[str, int, int]:  # type: ignore[override]
        raise NotImplementedError("FallbackClient delegates via complete()")

    async def _structured_complete(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("FallbackClient delegates via complete()")
