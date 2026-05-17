"""Graders: discovery + frontmatter parsing + judge inheritance + suggestion."""

from pathlib import Path

import pytest

from core.agents import graders
from core.agents.grader import GraderHook, MAX_SCORE


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
