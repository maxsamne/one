"""Grader hook — LLM-as-judge post-response hook that optimises output toward MAX_SCORE on every criterion.

Not a pass/fail gate. Drives the coder toward the highest possible quality by:
  1. Scoring each criterion 0–MAX_SCORE (integer, no decimals).
  2. Injecting the actual bodies of all attached skills so the judge checks real rules.
  3. Accumulating a compact GradeSnapshot per round — scores + 3–5 verbatim excerpts
     the judge selected — so history is trackable without storing full prior drafts.
  4. Detecting plateau (identical scores to the previous round) and issuing different
     feedback: "you haven't moved on X — try a fundamentally different approach."
  5. Returning None only when all criteria reach MAX_SCORE.

Instances are stateful — one per `coder.run()` call. The registry in
`core.agents.graders` builds them from markdown files; the manager wires them
into `coder.run(extra_hooks=...)` automatically when the task has graders attached,
so DEFAULT_HOOKS (lint, inline-html) still run alongside.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from core.agents.hooks import Hook, HookContext
from core.ai_client.interface import AiClient
from core.log import Category
from core.log import log as _log

GRADER_HOOK_RETRIES = 4
MAX_SCORE = 5  # Score range is 0..MAX_SCORE inclusive. Bump here to widen the rubric.

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Criterion:
    """A single grading dimension."""
    name: str          # snake_case identifier
    description: str   # what the grader looks for — shown verbatim to the judge
    weight: int = 1    # relative importance; used only for logging/display, not scoring


# Universal baseline criterion baked into every grader. Catches the failure mode where the
# output follows the skill rules perfectly but ignores what the user actually asked for or
# the reference images they attached. The judge sees the user prompt + images on every call,
# so it can grade this in the same pass as the grader's own criteria.
_USER_SATISFACTION = Criterion(
    name="user_satisfaction",
    weight=3,
    description=(
        "Does the output address what the user actually asked for in the original prompt "
        "above, and — if reference images were attached — take real inspiration from them? "
        "Check every concrete ask in the prompt has a corresponding piece in the output; "
        "negative constraints ('don't add features', 'same text') are honoured; the output is "
        "a substantive response, not a thin gesture. When references are attached, the output's "
        "composition, density, palette and type voice must be visibly inspired by them — "
        "translated through the design system, not copied, but the family resemblance must be "
        "obvious at a glance. A response that follows the skill rules perfectly but ignores "
        "the user's literal request or attached references is a low score. Cite the specific "
        "part of the prompt or the specific reference element that was missed."
    ),
)


def _with_baseline(criteria: list[Criterion]) -> list[Criterion]:
    """Prepend the universal user_satisfaction criterion unless the grader already declares one."""
    if any(c.name == _USER_SATISFACTION.name for c in criteria):
        return list(criteria)
    return [_USER_SATISFACTION, *criteria]


@dataclass
class GradeSnapshot:
    """Compact record of one grader run — passed as history to subsequent runs."""
    version: int
    scores: dict[str, int]    # criterion.name → 0..MAX_SCORE
    strengths: list[str]      # 2–3 bullets of what's working
    outstanding: list[str]    # what still needs improvement
    excerpts: list[str]       # short representative quotes the judge pulled from the draft

    def is_optimal(self, criteria: list[Criterion]) -> bool:
        return all(self.scores.get(c.name, 0) == MAX_SCORE for c in criteria)

    def plateau_vs(self, prev: GradeSnapshot) -> bool:
        return self.scores == prev.scores

    def summary(self, criteria: list[Criterion]) -> str:
        lines = [f"--- Version {self.version} ---"]
        for c in criteria:
            lines.append(f"  {c.name}: {self.scores.get(c.name, '?')}/{MAX_SCORE}")
        if self.strengths:
            lines.append("  Strengths: " + "; ".join(self.strengths))
        if self.outstanding:
            lines.append("  Outstanding: " + "; ".join(self.outstanding))
        if self.excerpts:
            lines.append("  Key excerpts from this draft:")
            for ex in self.excerpts:
                lines.append(f"    > {ex}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal Pydantic response model for the judge call
# ---------------------------------------------------------------------------

class _CriterionScore(BaseModel):
    name: str
    score: int        # 0..MAX_SCORE
    justification: str


class _GradeResponse(BaseModel):
    scores: list[_CriterionScore]
    strengths: list[str]
    outstanding: list[str]
    key_excerpts: list[str] = Field(
        description=(
            "3–5 short verbatim quotes from the current draft that are most diagnostic — "
            "a passage that exemplifies a strength, one that exemplifies a weakness, "
            "the opening sentence, or any excerpt that captures the current state well. "
            "Each under 80 words. These travel in the snapshot history so future grader "
            "rounds can see how the writing evolved without re-reading full old drafts."
        )
    )
    feedback: str     # actionable improvement instructions returned to the coder


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

_RUBRIC_PREAMBLE = f"""\
You are a rigorous editor grading a piece of work against the injected skill rules and
the explicit criteria below. Score each criterion on a 0–{MAX_SCORE} integer scale —
no decimals, no half-points:

  0 = fails criterion entirely
  1 = barely present — token attempt at best
  2 = partially meets — present but weak or inconsistent
  3 = mostly meets — solid with one notable gap
  4 = strongly meets — minor polish remaining
  5 = fully meets — nothing meaningful to improve on this dimension

Scoring rules:
- Length does NOT affect scores. A concise piece can score {MAX_SCORE}/{MAX_SCORE}.
- Treat the criteria and skill rules as a capability map, not a mandatory checklist.
  First infer the scope requested by the user: writing/voice, argument/content,
  research/sourcing, design/layout, functionality, code, or another concrete area.
  Apply criteria strongly only when they are relevant to that requested scope. Use
  unrelated criteria only as guardrails for severe regressions that directly break
  the requested output.
- The original user request is the primary scope. Skill rules are supporting context,
  not permission to ask for unrelated changes. If a skill contains guidance for
  design, formatting, research depth, tooling, or structure that the user did not
  ask to change, do not lower scores or request revisions for that area unless it
  directly breaks the requested output.
- Inline HTML blocks may be preview/transport for files the agent wrote. Their presence
  does not expand the assignment. Do not grade or request broad page/design/content
  changes merely because a full HTML document is visible; focus on the user-requested
  change and any directly related defects.
- For `follows_skill`: check the output line-by-line against the actual rules in the
  injected skills above. Name specific rules that were broken or followed.
- Grade each criterion independently against its definition only.
- Do not let your general preferences or aesthetic opinions override the criteria.
- Be calibrated: a {MAX_SCORE} should be genuinely hard to earn.

After scoring:
- List 2–3 concrete strengths with specific references.
- List up to 3 outstanding issues with specific references.
- Select 3–5 key_excerpts: short verbatim quotes from the draft that are most
  diagnostic of the current state (openings, weak passages, strong passages).
- Write `feedback`: specific, actionable instructions the author should follow in the
  next draft. Reference exact passages. No vague encouragements.
"""


class GraderHook(Hook):
    """Optimising LLM-as-judge hook. Drives scores toward 3/3 on every criterion.

    Reads attached skill bodies from TASK_SKILLS_CTX so the judge checks actual
    injected rules, not general knowledge. Drives scores toward 5/5.
    """
    name = "grader"

    def __init__(self, criteria: list[Criterion], judge: AiClient) -> None:
        self._criteria = _with_baseline(criteria)
        self._judge = judge
        self._history: list[GradeSnapshot] = []

    async def check(self, ctx: HookContext) -> str | None:
        version = len(self._history) + 1
        prompt = self._build_prompt(ctx.response)
        images = self._collect_images()

        try:
            grade: _GradeResponse = await self._judge.complete(
                prompt,
                images=images,
                response_model=_GradeResponse,
            )
        except Exception as e:
            _log(Category.AGENT, "grader error", error=str(e)[:200], agent=ctx.agent_id)
            return None  # don't block on judge failure

        scores = {s.name: max(0, min(MAX_SCORE, s.score)) for s in grade.scores}
        snapshot = GradeSnapshot(
            version=version,
            scores=scores,
            strengths=grade.strengths[:3],
            outstanding=grade.outstanding[:3],
            excerpts=grade.key_excerpts[:5],
        )
        self._history.append(snapshot)

        _log(Category.AGENT, "grader scored",
             version=version, scores=scores, agent=ctx.agent_id,
             optimal=snapshot.is_optimal(self._criteria))

        if snapshot.is_optimal(self._criteria):
            return None

        # Plateau: same scores as previous round — in-place editing isn't working
        if len(self._history) >= 2 and snapshot.plateau_vs(self._history[-2]):
            stuck = [c.name for c in self._criteria if scores.get(c.name, 0) < MAX_SCORE]
            plateau_note = (
                f"\n\n**Plateau detected** — scores on {', '.join(stuck)} are unchanged "
                f"from the previous draft. Incremental editing is not working. "
                f"Try a fundamentally different approach: restructure the argument, "
                f"rewrite the opening from scratch, or reframe the section entirely."
            )
            return grade.feedback + plateau_note

        return grade.feedback

    def _build_prompt(self, response: str) -> str:
        from core.agents import skills as _skills
        from core.agents.task_ctx import TASK_CTX, TASK_SKILLS_CTX

        parts: list[str] = []

        # Always inject the original user prompt — the baked-in user_satisfaction criterion
        # grades against it, and the other criteria benefit from the context too.
        ctx = TASK_CTX.get()
        user_prompt = (ctx.prompt if ctx else "") or ""
        if user_prompt:
            parts.append(
                "## User context — the original request (and any reference images travel on this call)\n\n"
                "For reference only. Grade the output against the criteria below; do not invent "
                "criteria from this context.\n\n"
                f"> {user_prompt}"
            )

        # Inject actual skill bodies so the judge checks real rules
        skill_paths = list(TASK_SKILLS_CTX.get() or [])
        if skill_paths:
            bodies = _skills.join_bodies(skill_paths)
            if bodies:
                parts.append(f"## Injected skills — grade compliance against these rules\n\n{bodies}")

        parts.append(_RUBRIC_PREAMBLE)

        parts.append("## Criteria\n")
        for c in self._criteria:
            parts.append(f"**{c.name}** — {c.description}")

        if self._history:
            parts.append("\n## History of previous drafts\n")
            for snap in self._history:
                parts.append(snap.summary(self._criteria))

        parts.append("\n## Current draft to grade\n")
        parts.append(response)

        return "\n\n".join(parts)

    def _collect_images(self) -> list:
        """Pull user-attached images from the task context. None/empty → judge runs text-only."""
        from core.agents.task_ctx import TASK_IMAGES_CTX
        imgs = list(TASK_IMAGES_CTX.get() or [])
        return imgs or None
