"""board_post tool — append entries to the shared session board."""

from core.agents.agent_ctx import ROLE_CTX
from core.agents.board import get_board
from core.agents.task_ctx import current_task_id
from core.ai_client.models import Tool


async def board_post(
    kind: str,
    payload: str,
    target_role: str | None = None,
    responded_to_seq: int | None = None,
) -> str:
    task_id = current_task_id()
    if not task_id:
        return "FATAL: no task context — board_post called outside a task"
    role = ROLE_CTX.get()
    try:
        seq = get_board().post(
            task_id, role, kind, payload,
            target_role=target_role,
            responded_to_seq=responded_to_seq,
        )
    except ValueError as e:
        return f"RETRYABLE: {e}"
    return f"OK seq={seq}"


BOARD_POST_TOOL = Tool(
    name="board_post",
    description=(
        "Append an entry to the shared session board so other parallel loops can see it. "
        "Use 'progress' to share what you just did. Use 'request' (with target_role) to ask another loop for help. "
        "Use 'response' (with target_role + responded_to_seq) to answer a request addressed to you. "
        "Keep payloads short and concrete — one or two sentences."
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind":             {"type": "string", "enum": ["progress", "request", "response"]},
            "payload":          {"type": "string"},
            "target_role":      {"type": "string", "description": "Required for request/response. The role you're addressing."},
            "responded_to_seq": {"type": "integer", "description": "Required for response. The seq of the request you're answering."},
        },
        "required": ["kind", "payload"],
    },
    fn=board_post,
    is_read_only=False,
    is_concurrency_safe=False,
)
