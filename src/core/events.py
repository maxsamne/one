"""In-process pub/sub bus keyed by task_id.

log() publishes every event here. SSE endpoints subscribe to receive them
in real time. Multiple subscribers per task are supported (e.g. two open
browser tabs watching the same task).

Slow consumers silently drop events beyond the queue high-water mark — this
is a streaming log, not a reliable message bus.
"""

import asyncio
from collections import defaultdict

_HWM = 512  # max queued events per subscriber before dropping

_subs: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(task_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_HWM)
    _subs[task_id].append(q)
    return q


def unsubscribe(task_id: str, q: asyncio.Queue) -> None:
    try:
        _subs[task_id].remove(q)
    except ValueError:
        pass
    if not _subs[task_id]:
        _subs.pop(task_id, None)


def publish(task_id: str, event: dict) -> None:
    for q in _subs.get(task_id, []):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow consumer — drop oldest would be nicer but this is fine
