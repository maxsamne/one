"""load_skill tool — coder pulls a skill's full body mid-loop on demand.

The pre-loaded skill bodies are deterministic (trigger-matched on task text). For
anything the triggers missed, the coder reads the always-injected skills index and
calls `load_skill` to fetch a body when the task drifts into that area.
"""

from core.agents import skills
from core.ai_client.models import Tool
from core.log import Category
from core.log import log as _log


async def load_skill(name: str) -> str:
    body = skills.read_body(name)
    _log(
        Category.AGENT, "load_skill",
        skill=name, ok=not body.startswith("FATAL"), bytes=len(body),
    )
    return body


LOAD_SKILL_TOOL = Tool(
    name="load_skill",
    description=(
        "Fetch the full body of a skill file by its path. The skill paths and one-line "
        "summaries are listed in your system prompt under 'Available skills'. Use this when "
        "the task drifts into a new area not covered by your pre-loaded skills (e.g. you "
        "started a Python script and now realise the user wants an interactive HTML chart — "
        "load `general/artifact-design/SKILL.md`). Returns the markdown body as text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact skill path, e.g. 'general/python.md' or 'general/artifact-design/SKILL.md'.",
            },
        },
        "required": ["name"],
    },
    fn=load_skill,
    is_read_only=True,
    is_concurrency_safe=True,
)
