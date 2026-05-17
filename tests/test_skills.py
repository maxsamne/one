"""Skills: discovery + suggestion + image loading."""

from core.agents import skills


def test_discover_finds_flat_and_folder_skills():
    paths = {s.path for s in skills.discover()}
    assert "general/python.md" in paths                          # flat .md
    assert "general/artifact-design/SKILL.md" in paths           # folder/SKILL.md
    assert not any(p.endswith("DOMAIN.md") for p in paths)       # DOMAIN.md ignored


def test_suggest_for_matches_keywords_with_word_boundary():
    # Positive: "dashboard" matches; Negative: "graphql" must not match "graph".
    assert "general/artifact-design/SKILL.md" in {s.path for s in skills.suggest_for("build me a dashboard")}
    assert skills.suggest_for("what is graphql?") == []


# Disabled: skills.collect_images is intentionally a no-op (returns []) since
# inspiration images were replaced by DESIGN_SPEC.md text so text-only local
# models benefit too. Re-enable when vision-capable models become the default.
# def test_collect_images_reads_inspiration_from_folder_skills_only():
#     assert skills.images_for("general/python.md") == []
#     imgs = skills.collect_images(["general/artifact-design/SKILL.md"])
#     assert imgs and imgs[0].mime.startswith("image/")
