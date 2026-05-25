"""Grader hook — LLM-as-judge post-response hook that gates output quality.

The grader is a pass/fail reviewer, not a numeric scorer. It:
  1. Inspects the response against the original request, attached skills, criteria,
     and deterministic changed-file context.
  2. Returns one boolean verdict: `optimal`.
  3. If `optimal=false`, returns concrete `required_changes` for the next coder turn.
  4. Accumulates compact verdict history so follow-up grader rounds can see what was
     previously accepted or blocked without replaying full old drafts.

Instances are stateful — one per `coder.run()` call. The registry in
`core.agents.graders` builds them from markdown files; the manager wires them
into `coder.run(extra_hooks=...)` automatically when the task has graders attached,
so DEFAULT_HOOKS (lint, inline-html) still run alongside.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from core.agents.grader_context import ChangeContext, collect_change_context
from core.agents.grader_inspector import InspectorEvidence, run_grader_inspection, should_run_inspector
from core.agents.hooks import Hook, HookContext
from core.ai_client.interface import AiClient
from core.log import Category
from core.log import log as _log

GRADER_HOOK_RETRIES = 4

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
        "the user's literal request or attached references is not optimal. Cite the specific "
        "part of the prompt or the specific reference element that was missed."
    ),
)


def _with_baseline(criteria: list[Criterion]) -> list[Criterion]:
    """Prepend the universal user_satisfaction criterion unless the grader already declares one."""
    if any(c.name == _USER_SATISFACTION.name for c in criteria):
        return list(criteria)
    return [_USER_SATISFACTION, *criteria]


@dataclass
class VerdictSnapshot:
    """Compact record of one grader run — passed as history to subsequent runs."""
    version: int
    optimal: bool
    reason: str
    required_changes: list[str]
    evidence: list[str]

    def summary(self) -> str:
        lines = [f"--- Version {self.version} ---", f"  optimal: {self.optimal}", f"  Reason: {self.reason}"]
        if self.required_changes:
            lines.append("  Required changes: " + "; ".join(self.required_changes))
        if self.evidence:
            lines.append("  Evidence:")
            for item in self.evidence:
                lines.append(f"    - {item}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal Pydantic response model for the judge call
# ---------------------------------------------------------------------------

class _GradeResponse(BaseModel):
    optimal: bool = Field(
        description=(
            "True only when the work is good enough to ship for the original request, "
            "attached skills, criteria, and changed-file evidence. False means the coder "
            "should get another turn if retry budget remains."
        )
    )
    reason: str = Field(description="Concise explanation of the verdict.")
    required_changes: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete changes the coder must make before the work is acceptable. "
            "Must be non-empty when optimal=false; should be empty when optimal=true."
        ),
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Brief factual notes, with file paths or excerpts when useful, supporting the verdict.",
    )


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

_RUBRIC_PREAMBLE = """\
You are a rigorous reviewer judging whether a piece of work is good enough to ship.
Return one boolean verdict: `optimal`.

Verdict rules:
- `optimal=true` means there is nothing meaningful left to fix for the user's actual
  request. Small subjective preferences are not enough to block.
- `optimal=false` means at least one concrete issue remains that the coder can and
  should fix in another turn.
- Do not produce numeric scores.
- Treat the criteria and skill rules as a capability map, not a mandatory checklist.
  First infer the scope requested by the user: writing/voice, argument/content,
  research/sourcing, design/layout, functionality, code, or another concrete area.
  Apply criteria strongly only when they are relevant to that requested scope. Use
  unrelated criteria only as guardrails for severe regressions that directly break
  the requested output.
- The original user request is the primary scope. Skill rules are supporting context,
  not permission to ask for unrelated changes. If a skill contains guidance for
  design, formatting, research depth, tooling, or structure that the user did not
  ask to change, do not block or request revisions for that area unless it
  directly breaks the requested output.
- Inline HTML blocks may be preview/transport for files the agent wrote. Their presence
  does not expand the assignment. Do not grade or request broad page/design/content
  changes merely because a full HTML document is visible; focus on the user-requested
  change and any directly related defects.
- When a diff or changed-file context is supplied below, treat it as the ground truth
  for what changed. Do not ask the author to paste or recreate full files merely so
  you can inspect them.
- For `follows_skill`: check the output line-by-line against the actual rules in the
  injected skills above. Name specific rules that were broken or followed.
- Do not let your general preferences or aesthetic opinions override the criteria.

After judging:
- Set `optimal`.
- Write `reason`: concise, specific, and grounded in the request and evidence.
- If `optimal=false`, list concrete `required_changes` the coder must make. These
  are the retry instructions, so they must be actionable and bounded.
- If `optimal=true`, `required_changes` should be empty.
- List brief `evidence` notes with file paths, changed-file facts, or short excerpts
  when useful. Prefer exact evidence over the author's summary.
"""


class GraderHook(Hook):
    """LLM-as-judge hook that retries until the grader accepts the work or budget ends.

    Reads attached skill bodies from TASK_SKILLS_CTX so the judge checks actual
    injected rules, not general knowledge.
    """
    name = "grader"

    def __init__(self, criteria: list[Criterion], judge: AiClient) -> None:
        self._criteria = _with_baseline(criteria)
        self._judge = judge
        self._history: list[VerdictSnapshot] = []

    async def check(self, ctx: HookContext) -> str | None:
        version = len(self._history) + 1
        prompt = await self._build_prompt(ctx.response)
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

        snapshot = VerdictSnapshot(
            version=version,
            optimal=grade.optimal,
            reason=grade.reason.strip(),
            required_changes=[c.strip() for c in grade.required_changes[:5] if c.strip()],
            evidence=[e.strip() for e in grade.evidence[:5] if e.strip()],
        )
        self._history.append(snapshot)

        _log(
            Category.AGENT, "grader verdict",
            version=version,
            optimal=snapshot.optimal,
            required_changes=len(snapshot.required_changes),
            agent=ctx.agent_id,
        )

        if snapshot.optimal:
            return None

        return self._retry_feedback(snapshot)

    def _retry_feedback(self, snapshot: VerdictSnapshot) -> str:
        lines = [
            "The grader did not accept the work yet. Revise the actual task output before responding.",
            "",
            f"Reason: {snapshot.reason or 'The grader marked the work as not optimal.'}",
        ]
        if snapshot.required_changes:
            lines.extend(["", "Required changes:"])
            lines.extend(f"- {change}" for change in snapshot.required_changes)
        else:
            lines.extend([
                "",
                "Required changes:",
                "- Re-inspect the original request, changed-file context, and grader criteria; make a concrete fix for the issue described in the reason.",
            ])
        if snapshot.evidence:
            lines.extend(["", "Evidence:"])
            lines.extend(f"- {item}" for item in snapshot.evidence)
        return "\n".join(lines)

    async def _build_prompt(self, response: str) -> str:
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
            parts.append("\n## History of previous grader verdicts\n")
            for snap in self._history:
                parts.append(snap.summary())

        change_context = await collect_change_context()
        if change_context:
            parts.append(
                "\n## Changed-file context\n\n"
                "This is deterministic context from the task workdir. Prefer it over "
                "the author's summary when judging what changed.\n\n"
                f"{change_context.text}"
            )

        if should_run_inspector(change_context, self._criteria, response):
            evidence = await self._inspect(response, user_prompt, change_context)
            if evidence:
                parts.append(
                    "\n## Read-only grader inspection evidence\n\n"
                    "A read-only inspector gathered this evidence from the task workdir. "
                    "Use it as factual input; it is not a grade.\n\n"
                    f"```json\n{evidence.model_dump_json(indent=2)}\n```"
                )

        parts.append("\n## Current draft to grade\n")
        parts.append(response)

        return "\n\n".join(parts)

    async def _inspect(
        self,
        response: str,
        user_prompt: str,
        change_context: ChangeContext | None,
    ) -> InspectorEvidence | None:
        return await run_grader_inspection(
            client=self._judge,
            user_prompt=user_prompt,
            criteria=self._criteria,
            response=response,
            change_context=change_context,
        )

    def _collect_images(self) -> list:
        """Pull user-attached images from the task context. None/empty → judge runs text-only."""
        from core.agents.task_ctx import TASK_IMAGES_CTX
        imgs = list(TASK_IMAGES_CTX.get() or [])
        return imgs or None
