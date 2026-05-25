"""Graders: discovery + frontmatter parsing + judge inheritance + suggestion + universal user_satisfaction baseline."""

from pathlib import Path
import subprocess

import pytest

from core.agents import graders
from core.agents.grader import Criterion, GraderHook
from core.agents.grader_inspector import InspectorEvidence, run_grader_inspection
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
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
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
    assert "Do not produce numeric scores" in captured["prompt"]
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
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
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


async def test_small_diff_does_not_invoke_grader_inspector(tmp_path: Path, monkeypatch):
    captured: dict = {}

    async def _fail_inspector(**kwargs):
        raise AssertionError("inspector should not run for a small untruncated diff")

    monkeypatch.setattr("core.agents.grader.run_grader_inspection", _fail_inspector)

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
            )

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "one.txt"
    path.write_text("old", encoding="utf-8")
    _git(tmp_path, "add", "one.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    path.write_text("new", encoding="utf-8")
    _git(tmp_path, "add", "one.txt")
    _git(tmp_path, "commit", "-q", "-m", "change")

    workdir_token = WORKDIR.set(tmp_path)
    diff_token = GRADER_DIFF_BASE_CTX.set(base)
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())
        await hook.check(HookContext(response="Done.", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        GRADER_DIFF_BASE_CTX.reset(diff_token)
        WORKDIR.reset(workdir_token)

    assert "Read-only grader inspection evidence" not in captured["prompt"]


async def test_truncated_diff_invokes_grader_inspector(tmp_path: Path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("core.agents.grader_context.CHANGE_CONTEXT_MAX_BYTES", 80)

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, extra_tools=None, **kw):
            if response_model is None:
                names = {t.name for t in extra_tools or []}
                assert "read_file" in names and "changed_files" in names
                assert "write_file" not in names and "git_commit" not in names
                return (
                    '{"inspected_files":["large.txt"],'
                    '"subagent_reports":[],'
                    '"evidence":["large.txt changed after the capped diff"],'
                    '"open_questions":[]}'
                )
            captured["prompt"] = prompt
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
            )

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "large.txt"
    path.write_text("old\n", encoding="utf-8")
    _git(tmp_path, "add", "large.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    path.write_text("new\n" + ("x" * 1000), encoding="utf-8")
    _git(tmp_path, "add", "large.txt")
    _git(tmp_path, "commit", "-q", "-m", "change")

    workdir_token = WORKDIR.set(tmp_path)
    diff_token = GRADER_DIFF_BASE_CTX.set(base)
    try:
        hook = GraderHook([Criterion(name="c", description="d")], _StubJudge())
        await hook.check(HookContext(response="Done.", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        GRADER_DIFF_BASE_CTX.reset(diff_token)
        WORKDIR.reset(workdir_token)

    assert "Read-only grader inspection evidence" in captured["prompt"]
    assert "large.txt changed after the capped diff" in captured["prompt"]


async def test_grader_hook_falls_back_to_touched_files_without_git(tmp_path: Path):
    captured: dict = {}

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
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


async def test_grader_hook_returns_required_changes_when_not_optimal():
    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=False,
                reason="The new node is present but visually bolted on.",
                required_changes=["Integrate the new node more intentionally into the diagram."],
                evidence=["docs/index.html adds a small Yesterday Test node."],
            )

    hook = GraderHook([Criterion(name="craft", description="Has a considered craft detail.")], _StubJudge())
    feedback = await hook.check(HookContext(response="Done.", turn=1, agent_id="t1:gpt", role="coder"))

    assert feedback is not None
    assert "did not accept the work yet" in feedback
    assert "The new node is present but visually bolted on." in feedback
    assert "Integrate the new node more intentionally into the diagram." in feedback
    assert "docs/index.html adds a small Yesterday Test node." in feedback


async def test_grader_hook_handles_missing_required_changes_when_not_optimal():
    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=False,
                reason="The work misses the requested article link.",
                required_changes=[],
                evidence=[],
            )

    hook = GraderHook([Criterion(name="links", description="Links are correct.")], _StubJudge())
    feedback = await hook.check(HookContext(response="Done.", turn=1, agent_id="t1:gpt", role="coder"))

    assert feedback is not None
    assert "The work misses the requested article link." in feedback
    assert "make a concrete fix" in feedback


async def test_grader_inspector_tools_are_read_only():
    calls: list[list[str]] = []

    class _InspectorClient:
        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=None, **kw):
            calls.append([t.name for t in extra_tools or []])
            return (
                '{"inspected_files":[],"subagent_reports":[],'
                '"evidence":["ok"],"open_questions":[]}'
            )

    evidence = await run_grader_inspection(
        client=_InspectorClient(),
        user_prompt="inspect",
        criteria=[Criterion(name="c", description="d")],
        response="Done.",
        change_context=None,
    )

    assert evidence is not None
    names = set(calls[0])
    assert {"read_file", "grep_file", "list_dir", "git_diff", "git_status", "git_log", "changed_files"} <= names
    assert "spawn_readonly_subagent" in names
    assert not (names & {"write_file", "edit_file", "delete_file", "git_add", "git_commit", "git_push", "generate_image", "run_command"})


async def test_grader_inspector_subagents_are_read_only_and_reported():
    calls: list[list[str]] = []
    spawned = False

    class _InspectorClient:
        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=None, **kw):
            nonlocal spawned
            names = [t.name for t in extra_tools or []]
            calls.append(names)
            if "spawn_readonly_subagent" in names and not spawned:
                spawned = True
                tool = next(t for t in extra_tools if t.name == "spawn_readonly_subagent")
                await tool.fn(scope="CSS/layout", question="Check CSS changes only.")
            return (
                '{"inspected_files":["docs/page.html"],'
                '"subagent_reports":[],'
                '"evidence":["parent evidence"],'
                '"open_questions":[]}'
            )

    evidence = await run_grader_inspection(
        client=_InspectorClient(),
        user_prompt="inspect page",
        criteria=[Criterion(name="layout", description="inspect CSS layout")],
        response="Done.",
        change_context=None,
    )

    assert evidence is not None
    assert any(r.scope == "CSS/layout" for r in evidence.subagent_reports)
    assert "spawn_readonly_subagent" in calls[0]
    assert "spawn_readonly_subagent" not in calls[1]
    for names in calls:
        assert not (set(names) & {"write_file", "edit_file", "delete_file", "git_add", "git_commit", "git_push", "generate_image", "run_command"})


async def test_subagent_evidence_is_included_in_final_grader_prompt(tmp_path: Path, monkeypatch):
    captured: dict = {}

    async def _fake_inspector(**kwargs):
        return InspectorEvidence(
            inspected_files=["docs/page.html"],
            subagent_reports=[{"scope": "CSS/layout", "summary": "Only .leadline changed."}],
            evidence=["docs/page.html:12 changed leadline text"],
            open_questions=[],
        )

    monkeypatch.setattr("core.agents.grader.run_grader_inspection", _fake_inspector)
    monkeypatch.setattr("core.agents.grader_context.CHANGE_CONTEXT_MAX_BYTES", 80)

    class _StubJudge:
        async def complete(self, prompt, images=None, response_model=None, **kw):
            captured["prompt"] = prompt
            from core.agents.grader import _GradeResponse
            return _GradeResponse(
                optimal=True,
                reason="ok",
                required_changes=[],
                evidence=[],
            )

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "docs" / "page.html"
    path.parent.mkdir()
    path.write_text("old\n", encoding="utf-8")
    _git(tmp_path, "add", "docs/page.html")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    path.write_text("new\n" + ("x" * 1000), encoding="utf-8")
    _git(tmp_path, "add", "docs/page.html")
    _git(tmp_path, "commit", "-q", "-m", "change")

    workdir_token = WORKDIR.set(tmp_path)
    diff_token = GRADER_DIFF_BASE_CTX.set(base)
    try:
        hook = GraderHook([Criterion(name="layout", description="inspect CSS layout")], _StubJudge())
        await hook.check(HookContext(response="Done.", turn=1, agent_id="t1:gpt", role="coder"))
    finally:
        GRADER_DIFF_BASE_CTX.reset(diff_token)
        WORKDIR.reset(workdir_token)

    assert "Read-only grader inspection evidence" in captured["prompt"]
    assert "Only .leadline changed." in captured["prompt"]
    assert "docs/page.html:12 changed leadline text" in captured["prompt"]


async def test_grader_inspector_auto_compacts_when_context_crosses_threshold():
    class _CompactingClient:
        def __init__(self) -> None:
            self.inspect_calls = 0
            self.compactions = 0

        async def complete(self, prompt, *, instructions=None, thinking=None, extra_tools=None, **kw):
            if instructions and "compacting a read-only grader inspection loop" in instructions:
                self.compactions += 1
                return "files inspected: none yet"
            self.inspect_calls += 1
            if self.inspect_calls < 8:
                return "not json " + ("x" * 100)
            return (
                '{"inspected_files":[],"subagent_reports":[],'
                '"evidence":["done"],"open_questions":[]}'
            )

    client = _CompactingClient()
    evidence = await run_grader_inspection(
        client=client,
        user_prompt="inspect",
        criteria=[Criterion(name="c", description="d")],
        response="Done.",
        change_context=None,
        context_window=1,
        max_turns=8,
    )

    assert evidence is not None
    assert client.compactions >= 1


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
