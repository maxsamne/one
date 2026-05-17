"""Project presets: discovery + sample article-writing preset wiring."""

from core import presets


def test_discover_finds_article_writing_preset():
    by_name = {p.name: p for p in presets.discover()}
    assert "article-writing" in by_name
    p = by_name["article-writing"]
    assert p.tier == "cheap"
    assert "general/article-writer/SKILL.md" in p.skills
    assert "general/article-design/SKILL.md" in p.skills
    assert "general/article-voice.md" in p.graders


def test_get_returns_none_for_unknown():
    assert presets.get("definitely-not-a-real-preset") is None
