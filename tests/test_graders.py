"""Graders: discovery + frontmatter parsing + judge inheritance + suggestion + universal user_satisfaction baseline."""

from pathlib import Path
import subprocess

import pytest

from core.agents import graders
from core.agents.grader import Criterion, GraderHook, MAX_SCORE
from core.agents.hooks import HookContext
from core.agents.task_ctx import GRADER_DIFF_BASE_CTX, TASK_CTX, TASK_IMAGES_CTX, TaskContext
from core.tools.ctx import TOOL_LOG, WORKDIR


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


async def test_grader_hook_injects_user_prompt_and_images_on_every_call():
    """Every grader call sees the user prompt + attached images, plus the baked-in
    user_satisfaction criterion. No flag, no opt-in — this is the universal baseline
    that catches 'output follows skill perfectly but ignores what the user asked'."""
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            captured["images"] = images
            from core.agents.grader import _CriterionScore, _GradeResponse
            return _GradeResponse(
                scores=[
                    _CriterionScore(name="user_satisfaction", score=5, justification="ok"),
                    _CriterionScore(name="c", score=5, justification="ok"),
                ],
                strengths=[], outstanding=[], key_excerpts=[], feedback="",
            )

    sentinel_imgs = [{"fake": "image"}]
    task_token = TASK_CTX.set(TaskContext(task_id="t1", prompt="MAKE A WEBSITE LIKE THIS"))
    img_token = TASK_IMAGES_CTX.set(sentinel_imgs)
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())
        # user_satisfaction is prepended to the criteria list automatically.
        assert [c.name for c in hook._criteria] == ["user_satisfaction", "c"]
        await hook.check(HookContext(response="output", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        TASK_CTX.reset(task_token)
        TASK_IMAGES_CTX.reset(img_token)

    assert "MAKE A WEBSITE LIKE THIS" in captured["prompt"]
    assert "user_satisfaction" in captured["prompt"]
    assert "The original user request is the primary scope" in captured["prompt"]
    assert "capability map, not a mandatory checklist" in captured["prompt"]
    assert captured["images"] == sentinel_imgs


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return result.stdout.strip()


async def test_grader_hook_injects_persistent_task_diff(tmp_path: Path):
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            from core.agents.grader import _CriterionScore, _GradeResponse
            return _GradeResponse(
                scores=[
                    _CriterionScore(name="user_satisfaction", score=5, justification="ok"),
                    _CriterionScore(name="c", score=5, justification="ok"),
                ],
                strengths=[], outstanding=[], key_excerpts=[], feedback="",
            )

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "docs" / "yesterday-test.html"
    path.parent.mkdir(parents=True)
    path.write_text("old article", encoding="utf-8")
    _git(tmp_path, "add", "docs/yesterday-test.html")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    path.write_text("new article", encoding="utf-8")
    _git(tmp_path, "add", "docs/yesterday-test.html")
    _git(tmp_path, "commit", "-q", "-m", "change")

    workdir_token = WORKDIR.set(tmp_path)
    diff_token = GRADER_DIFF_BASE_CTX.set(base)
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())
        await hook.check(HookContext(
            response="Done — updated `docs/yesterday-test.html`.",
            turn=1,
            agent_id="t1:gpt",
            role="coder",
        ))
    finally:
        GRADER_DIFF_BASE_CTX.reset(diff_token)
        WORKDIR.reset(workdir_token)

    assert "Changed-file context" in captured["prompt"]
    assert "diff --git a/docs/yesterday-test.html b/docs/yesterday-test.html" in captured["prompt"]
    assert "+new article" in captured["prompt"]
    assert "Do not ask the author to paste or recreate full files" in captured["prompt"]


async def test_grader_hook_falls_back_to_touched_files_without_git(tmp_path: Path):
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            from core.agents.grader import _CriterionScore, _GradeResponse
            return _GradeResponse(
                scores=[
                    _CriterionScore(name="user_satisfaction", score=5, justification="ok"),
                    _CriterionScore(name="c", score=5, justification="ok"),
                ],
                strengths=[], outstanding=[], key_excerpts=[], feedback="",
            )

    path = tmp_path / "report.html"
    path.write_text("<html>scratch artifact</html>", encoding="utf-8")

    workdir_token = WORKDIR.set(tmp_path)
    log_token = TOOL_LOG.set([{"tool": "write_file", "args": {"path": "report.html"}, "result": "Created"}])
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())
        await hook.check(HookContext(
            response="Done.",
            turn=1,
            agent_id="t1:gpt",
            role="coder",
        ))
    finally:
        TOOL_LOG.reset(log_token)
        WORKDIR.reset(workdir_token)

    assert "Changed-file context" in captured["prompt"]
    assert "scratch artifact" in captured["prompt"]


def test_grader_with_own_user_satisfaction_criterion_is_not_double_added():
    """If a grader file ships its own user_satisfaction criterion, the baseline is skipped —
    no duplicate criteria in the rubric."""
    class _Stub: pass
    hook = GraderHook(
        [Criterion(name="user_satisfaction", description="custom"), Criterion(name="c", description="d")],
        _Stub(),
    )
    names = [c.name for c in hook._criteria]
    assert names == ["user_satisfaction", "c"]  # not ["user_satisfaction", "user_satisfaction", "c"]


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
