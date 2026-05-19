"""Graders: discovery + frontmatter parsing + judge inheritance + suggestion + auto-attach."""

from pathlib import Path

import pytest

from core.agents import graders
from core.agents.grader import Criterion, GraderHook, MAX_SCORE
from core.agents.hooks import HookContext
from core.agents.task_ctx import TASK_CTX, TASK_IMAGES_CTX, TaskContext


def test_discover_parses_article_voice_with_inherited_judge():
    entries = {g.path: g for g in graders.discover()}
    assert "general/article-voice.md" in entries
    g = entries["general/article-voice.md"]
    # No `judge:` frontmatter → inherits the global default in tiers.json._grader_judge.
    assert g.judge_model.startswith("gemini-3")
    assert g.judge_provider.value == "gemini"
    assert g.summary.lower().startswith("grades")
    names = [c.name for c in g.criteria]
    assert names == ["follows_skill", "tone_and_voice", "intellectual_depth"]
    assert g.criteria[0].weight == 2
    assert "general/article-writer/SKILL.md" in g.suggested_for_skills


def test_suggest_for_skills_matches_attached_skill():
    matches = graders.suggest_for_skills(["general/article-writer/SKILL.md"])
    assert any(g.path == "general/article-voice.md" for g in matches)
    assert graders.suggest_for_skills(["nonsense/fake.md"]) == []


def test_max_score_is_5_for_optimal_check():
    # MAX_SCORE drives the rubric range; lifting it should not need code changes elsewhere.
    assert MAX_SCORE == 5


def test_instantiate_unknown_grader_raises():
    with pytest.raises(ValueError, match="unknown grader"):
        graders.instantiate("does/not/exist.md")


def test_manager_appends_auto_attach_when_user_attached_a_grader(monkeypatch):
    """User attaches one grader → manager auto-adds prompt-fidelity alongside it.
    No user graders → no auto-attach (trivial tasks like 'weather' stay cheap)."""
    from core.agents import manager
    from core.agents.task_ctx import TASK_GRADERS_CTX

    instantiated: list[str] = []
    def _fake_instantiate(p):
        instantiated.append(p)
        class _Hook: pass
        return _Hook()
    monkeypatch.setattr(graders, "instantiate", _fake_instantiate)

    # Case 1: user attached a grader → prompt-fidelity rides along.
    tok = TASK_GRADERS_CTX.set(["general/website-quality.md"])
    try:
        manager._build_extra_hooks()
    finally:
        TASK_GRADERS_CTX.reset(tok)
    assert "general/website-quality.md" in instantiated
    assert "general/prompt-fidelity.md" in instantiated

    # Case 2: no user graders → nothing instantiated.
    instantiated.clear()
    tok = TASK_GRADERS_CTX.set([])
    try:
        manager._build_extra_hooks()
    finally:
        TASK_GRADERS_CTX.reset(tok)
    assert instantiated == []


def test_prompt_fidelity_is_auto_attach_and_needs_images():
    """The shipped prompt-fidelity grader must opt into both flags or auto-attach won't fire."""
    entries = {g.path: g for g in graders.discover()}
    assert "general/prompt-fidelity.md" in entries
    g = entries["general/prompt-fidelity.md"]
    assert g.auto_attach is True
    assert g.needs_images is True
    assert "general/prompt-fidelity.md" in graders.auto_attach_paths()
    # Other graders must NOT auto-attach — that's the universal-vs-opt-in trade-off.
    assert "general/article-voice.md" not in graders.auto_attach_paths()


async def test_grader_hook_with_needs_images_injects_user_prompt_and_passes_images():
    """needs_images=True → judge sees the original user prompt in the prompt + receives images."""
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            captured["images"] = images
            # Return a dummy 5/5 response so the hook returns None
            from core.agents.grader import _CriterionScore, _GradeResponse
            return _GradeResponse(
                scores=[_CriterionScore(name="c", score=5, justification="ok")],
                strengths=[], outstanding=[], key_excerpts=[], feedback="",
            )

    sentinel_imgs = [{"fake": "image"}]
    task_token = TASK_CTX.set(TaskContext(task_id="t1", prompt="MAKE A WEBSITE LIKE THIS"))
    img_token = TASK_IMAGES_CTX.set(sentinel_imgs)
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge(), needs_images=True)
        await hook.check(HookContext(response="output", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        TASK_CTX.reset(task_token)
        TASK_IMAGES_CTX.reset(img_token)

    assert "MAKE A WEBSITE LIKE THIS" in captured["prompt"]
    assert captured["images"] == sentinel_imgs


async def test_grader_hook_without_needs_images_omits_prompt_and_images():
    """needs_images=False (default) → no user prompt injection, no images sent."""
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            captured["images"] = images
            from core.agents.grader import _CriterionScore, _GradeResponse
            return _GradeResponse(
                scores=[_CriterionScore(name="c", score=5, justification="ok")],
                strengths=[], outstanding=[], key_excerpts=[], feedback="",
            )

    task_token = TASK_CTX.set(TaskContext(task_id="t1", prompt="SECRET USER PROMPT"))
    img_token = TASK_IMAGES_CTX.set([{"fake": "image"}])
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())  # needs_images=False
        await hook.check(HookContext(response="output", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        TASK_CTX.reset(task_token)
        TASK_IMAGES_CTX.reset(img_token)

    assert "SECRET USER PROMPT" not in captured["prompt"]
    assert captured["images"] is None


def test_frontmatter_parser_handles_list_and_scalar(tmp_path: Path, monkeypatch):
    """Per-grader override of `judge:` wins over the global default; list values are parsed."""
    domain = tmp_path / "test_domain"
    domain.mkdir()
    (domain / "x.md").write_text(
        "---\n"
        "judge: openai:gpt-5.4-nano\n"
        "suggested_for_skills:\n"
        "  - general/python.md\n"
        "  - general/article-writer/SKILL.md\n"
        "---\n\n"
        "> A test grader.\n\n"
        "## Criteria\n\n"
        "### only_criterion (weight: 3)\n"
        "Body text.\n",
        encoding="utf-8",
    )
    # Point discovery at the tmp tree and clear the cache.
    monkeypatch.setattr(graders, "_GRADERS_DIR", tmp_path)
    graders.discover.cache_clear()
    try:
        out = graders.discover()
        assert len(out) == 1
        g = out[0]
        assert g.judge_provider.value == "openai" and g.judge_model == "gpt-5.4-nano"
        assert g.suggested_for_skills == frozenset({"general/python.md", "general/article-writer/SKILL.md"})
        assert g.criteria[0].weight == 3
    finally:
        graders.discover.cache_clear()
