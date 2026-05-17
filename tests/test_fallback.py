"""FallbackClient: swap on 503/UNAVAILABLE, propagate everything else."""

import pytest

from core.ai_client.fallback_client import FallbackClient


class _Stub:
    def __init__(self, name, raise_on_call=None, response="ok"):
        self.model_name = name
        self.provider = "stub"
        self._raise = raise_on_call
        self._response = response

    async def complete(self, *a, **kw):
        if self._raise:
            raise self._raise
        return self._response


def _wrap(primary, fallback):
    fc = FallbackClient.__new__(FallbackClient)  # bypass AiClient.__init__ for fakes
    fc.primary, fc.fallback = primary, fallback
    fc.model_name, fc.total_input_tokens, fc.total_output_tokens = primary.model_name, 0, 0
    return fc


async def test_fallback_swaps_on_503():
    fc = _wrap(_Stub("primary", raise_on_call=RuntimeError("503 UNAVAILABLE")),
               _Stub("fallback", response="from-fallback"))
    assert await fc.complete("anything") == "from-fallback"


async def test_fallback_propagates_non_503_errors():
    boom = ValueError("schema validation failed: missing required field")
    fc = _wrap(_Stub("primary", raise_on_call=boom), _Stub("fallback"))
    with pytest.raises(ValueError, match="schema validation"):
        await fc.complete("anything")
