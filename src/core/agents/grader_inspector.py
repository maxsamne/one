"""Read-only evidence inspection loop for grader hooks."""

from __future__ import annotations

import json
import re
from contextvars import ContextVar

from pydantic import BaseModel, Field, ValidationError

from core.agents.compact import ConversationHistory
from core.agents.grader_context import ChangeContext, changed_files_tool
from core.ai_client.interface import AiClient
from core.ai_client.models import ThinkingLevel, Tool
from core.log import Category
from core.log import log as _log
from core.tools.fs import FS_TOOLS
from core.tools.git import GIT_TOOLS

_INSPECTOR_MAX_TURNS = 8
_INSPECTOR_DEPTH: ContextVar[int] = ContextVar("grader_inspector_depth", default=0)
_INSPECTOR_CLIENT: ContextVar[AiClient | None] = ContextVar("grader_inspector_client", default=None)
_SUBAGENT_REPORTS: ContextVar[list["SubagentReport"]] = ContextVar("grader_inspector_subagent_reports", default=[])


class SubagentReport(BaseModel):
    scope: str
    summary: str


class InspectorEvidence(BaseModel):
    inspected_files: list[str] = Field(default_factory=list)
    subagent_reports: list[SubagentReport] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


_INSPECTOR_INSTRUCTIONS = """\
You are a read-only grader inspector. You gather evidence; you do not grade, edit,
delete, commit, push, generate images, or do feature work.

Focus on the original user request and the grader criteria. Prefer exact file, diff,
and selector evidence over the author's final summary. Do not ask the coder to paste
full HTML or recreate files for inspection.

Use tools only when needed. If the task is large, spawn read-only sub-agents for
bounded questions and incorporate their findings. Return only JSON matching:
{
  "inspected_files": ["path"],
  "subagent_reports": [{"scope": "bounded area", "summary": "concise finding"}],
  "evidence": ["path:line or diff evidence"],
  "open_questions": ["remaining uncertainty"]
}
"""

_COMPACT_INSTRUCTIONS = """\
You are compacting a read-only grader inspection loop. Summarize only durable
inspection state: files inspected, relevant evidence found, sub-agent reports,
user-requested requirements checked, what remains uncertain, and files or sections
still needing inspection. Output only the summary.
"""


def should_run_inspector(change_context: ChangeContext | None, criteria: list, response: str) -> bool:
    if change_context is None:
        return False
    if change_context.truncated or change_context.omitted_files:
        return True
    if len(change_context.changed_files) >= 8:
        return True
    if len(change_context.changed_files) >= 3 and _criteria_require_file_inspection(criteria):
        return True
    mentioned = set(_mentioned_paths(response))
    return bool(change_context.changed_files and mentioned and not mentioned.intersection(change_context.changed_files))


def _criteria_require_file_inspection(criteria: list) -> bool:
    haystack = " ".join(
        f"{getattr(c, 'name', '')} {getattr(c, 'description', '')}"
        for c in criteria
    ).lower()
    needles = ("file", "html", "css", "layout", "image", "link", "citation", "source", "code", "implementation")
    return any(n in haystack for n in needles)


def _mentioned_paths(text: str) -> list[str]:
    return re.findall(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|css|html|md|json|yaml|yml)", text)


def _parse_evidence(text: str) -> InspectorEvidence:
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    payload = match.group(1) if match else text.strip()
    return InspectorEvidence.model_validate_json(payload)


def _read_only_tools(allow_subagents: bool) -> list[Tool]:
    allowed = {"read_file", "grep_file", "list_dir", "git_status", "git_diff", "git_log"}
    tools = [t for t in [*FS_TOOLS, *GIT_TOOLS] if t.name in allowed and t.is_read_only]
    tools.append(CHANGED_FILES_TOOL)
    if allow_subagents:
        tools.append(SPAWN_READONLY_SUBAGENT_TOOL)
    return tools


def _format_goal(
    *,
    user_prompt: str,
    criteria: list,
    response: str,
    change_context: ChangeContext | None,
) -> str:
    criteria_text = "\n".join(
        f"- {getattr(c, 'name', 'criterion')}: {getattr(c, 'description', '')}"
        for c in criteria
    )
    changed = change_context.text if change_context else "(no deterministic changed-file context available)"
    files = ", ".join(change_context.changed_files) if change_context and change_context.changed_files else "(unknown)"
    return (
        "Inspect the task output and return structured evidence for the final grader.\n\n"
        f"## Original user request\n{user_prompt or '(none)'}\n\n"
        f"## Criteria\n{criteria_text}\n\n"
        f"## Changed files\n{files}\n\n"
        "## Capped deterministic changed-file context\n"
        f"{changed}\n\n"
        "## Agent final answer\n"
        f"{response}"
    )


async def run_grader_inspection(
    *,
    client: AiClient,
    user_prompt: str,
    criteria: list,
    response: str,
    change_context: ChangeContext | None,
    context_window: int = 128_000,
    max_turns: int = _INSPECTOR_MAX_TURNS,
    allow_subagents: bool = True,
) -> InspectorEvidence | None:
    goal = _format_goal(
        user_prompt=user_prompt,
        criteria=criteria,
        response=response,
        change_context=change_context,
    )
    history = ConversationHistory(
        goal=goal,
        window=context_window,
        compact_instructions=_COMPACT_INSTRUCTIONS,
    )
    tools = _read_only_tools(allow_subagents and _INSPECTOR_DEPTH.get() == 0)
    depth_token = _INSPECTOR_DEPTH.set(_INSPECTOR_DEPTH.get())
    client_token = _INSPECTOR_CLIENT.set(client)
    reports: list[SubagentReport] = []
    reports_token = _SUBAGENT_REPORTS.set(reports)
    last_text = ""
    try:
        for turn in range(max_turns):
            request = goal if turn == 0 else "Continue read-only inspection. Return valid JSON when evidence is sufficient."
            history.add("user", request)
            prompt = await history.next_prompt(client)
            last_text = await client.complete(
                prompt,
                instructions=_INSPECTOR_INSTRUCTIONS,
                thinking=ThinkingLevel.LOW,
                extra_tools=tools,
            )
            history.add("assistant", last_text)
            try:
                evidence = _parse_evidence(last_text)
            except (ValidationError, json.JSONDecodeError, ValueError):
                continue
            if reports:
                existing = {(r.scope, r.summary) for r in evidence.subagent_reports}
                for report in reports:
                    if (report.scope, report.summary) not in existing:
                        evidence.subagent_reports.append(report)
            _log(Category.AGENT, "grader inspector evidence", files=len(evidence.inspected_files), evidence=len(evidence.evidence))
            return evidence
    except Exception as e:
        _log(Category.AGENT, "grader inspector error", error=str(e)[:200])
        return None
    finally:
        _SUBAGENT_REPORTS.reset(reports_token)
        _INSPECTOR_CLIENT.reset(client_token)
        _INSPECTOR_DEPTH.reset(depth_token)

    try:
        evidence = _parse_evidence(last_text)
        reports = _SUBAGENT_REPORTS.get([])
        if reports:
            existing = {(r.scope, r.summary) for r in evidence.subagent_reports}
            for report in reports:
                if (report.scope, report.summary) not in existing:
                    evidence.subagent_reports.append(report)
        return evidence
    except Exception:
        return None


async def _spawn_readonly_subagent(scope: str, question: str) -> str:
    depth = _INSPECTOR_DEPTH.get()
    if depth >= 1:
        return "FATAL: grader inspector sub-agents cannot spawn nested sub-agents"
    client = _INSPECTOR_CLIENT.get()
    if client is None:
        return "FATAL: spawn_readonly_subagent called outside grader inspection"

    token = _INSPECTOR_DEPTH.set(depth + 1)
    try:
        evidence = await run_grader_inspection(
            client=client,
            user_prompt=f"Read-only sub-agent scope: {scope}",
            criteria=[],
            response=question,
            change_context=None,
            max_turns=4,
            allow_subagents=False,
        )
    finally:
        _INSPECTOR_DEPTH.reset(token)

    if evidence is None:
        summary = "Sub-agent could not produce structured evidence."
        payload = {"scope": scope, "summary": summary, "evidence": []}
    else:
        summary = "; ".join(evidence.evidence[:4]) or "; ".join(evidence.open_questions[:2]) or "No specific evidence found."
        payload = evidence.model_dump()
    report = SubagentReport(scope=scope, summary=summary)
    _SUBAGENT_REPORTS.get().append(report)
    return json.dumps(payload, indent=2)


CHANGED_FILES_TOOL = Tool(
    name="changed_files",
    description="List files changed by the task using the grader diff base, or touched files for scratch workdirs.",
    parameters={"type": "object", "properties": {}, "required": []},
    fn=changed_files_tool,
    is_read_only=True,
    is_concurrency_safe=True,
)

SPAWN_READONLY_SUBAGENT_TOOL = Tool(
    name="spawn_readonly_subagent",
    description="Spawn a bounded read-only grader-inspection sub-agent. It cannot edit, delete, commit, push, or spawn nested agents.",
    parameters={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "Short scope name for the delegated inspection."},
            "question": {"type": "string", "description": "The bounded evidence question to answer."},
        },
        "required": ["scope", "question"],
    },
    fn=_spawn_readonly_subagent,
    is_read_only=True,
)
