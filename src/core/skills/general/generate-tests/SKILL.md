> Conventions for writing pytest tests in this repo. Pulled in for any task that adds, edits, or reviews tests.

# Test conventions

## Keywords
test, tests, pytest, testing, unit test, regression, fixture

## Agent hints
- **Output:** new or edited files under `tests/` at the repo root.
- **Preferred thinking:** `low` for adding a single test, `medium` for new test files / new fixtures.
- **Run:** `uv run pytest` (auto-async mode is on; no decorators needed).

---

## Philosophy

Few sharp tests beat many shallow ones. **One test per distinct failure mode the user would care about.** If two tests would catch the same bug, delete one. If a test only checks "what would never break in practice", delete it.

The bar for adding a test is: *would removing this test let a real regression slip through?* If no, don't write it.

## Conventions

**Location & naming**
- All tests under `tests/` at repo root. One file per module / concern: `tests/test_<concern>.py`.
- Test functions: `test_<subject>_<expected_behavior>`. The name describes the behavior; no docstring needed.
- Module docstring: one line — what this file covers.

**Style**
- Zero verbosity. No "Arrange / Act / Assert" comments. No docstrings on test functions. The test body IS the documentation.
- Combine related positive + negative checks in one test when they share setup. Don't split a "matches" and "doesn't match" check into two near-identical tests if they share a single fixture and the comparison is the point.
- Use `pytest.raises(ExcType, match="...")` — keeps the assertion's intent visible.
- Async tests: just `async def test_...` — `asyncio_mode = "auto"` in `pyproject.toml` handles the rest.

**Mocking**
- Prefer simple stub classes (10-line `class _Stub: ...`) over `unittest.mock`. The stub's interface IS the contract being tested.
- Mock at the boundary, not deep internals. For `router.pick`, mock `router._PICKER` (the picker LLM client). Don't mock individual SDK calls.
- Use `monkeypatch` for env vars and module-level attribute swaps. Auto-undo on test exit.

**No-no list**
- No tests that hit real LLM/Exa/external APIs in CI. If you need one for manual verification, gate behind an env flag and skip by default.
- No assertions on log strings or formatting. Log content is implementation detail.
- No "exhaustive" tests: 5 variants of an enum, every error message, every edge of a parser. Pick the 1-2 that actually matter.
- No `setUp`/`tearDown` patterns. Use `@pytest.fixture` only when ≥2 tests share non-trivial setup.

**File layout template**

```python
"""<one-line: what this file covers>."""

import pytest
from core.<module> import <thing>


class _Stub:  # if needed
    ...


def _helper():  # if needed
    ...


def test_<subject>_<behavior>():
    assert ...


async def test_<async_subject>_<behavior>():
    assert ...
```

## Running

```bash
uv run pytest                  # all tests, quiet (addopts = "-q")
uv run pytest tests/test_skills.py            # one file
uv run pytest -k "fallback"                   # by name match
uv run pytest -x                              # stop on first failure
```

Test discovery: `pyproject.toml → [tool.pytest.ini_options]` sets `testpaths = ["tests"]` and `python_files = ["test_*.py"]`.

## When NOT to write a test

- Trivial getters / one-liners with no logic.
- Configuration loading where a typo would fail loudly the first time the app boots.
- UI rendering — gets stale fast, low value.
- "Integration" with external services — flaky and slow; cover with a smoke test in a separate manual flow.

## Example: the test files in this repo (May 2026)

| File | Tests | Concern |
|---|---|---|
| `tests/test_skills.py` | 3 | discovery (flat + folder), keyword matching with word boundary, image loading |
| `tests/test_router.py` | 3 | ROUTER_FORCE override, valid pick, invalid-pick fallback |
| `tests/test_fallback.py` | 2 | swap on 503, propagate non-503 |
| `tests/test_gateway.py` | 3 | data URI parse (valid + invalid), skill-path validation |

11 tests total. Each one fails on a real regression, none duplicate another's coverage.
