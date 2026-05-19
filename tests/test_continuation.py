"""Task continuation: parent transcript persists + replays into child loop."""

import pytest
from fastapi.testclient import TestClient

from core.agents.compact import ConversationHistory
from core.ai_client.models import ImageContent
from core.gateway.server import app
from core.log import transcript_load, transcript_save


def test_transcript_save_and_load_roundtrip():
    snap = ConversationHistory(goal="research X").snapshot()
    snap["turns"].append({"role": "assistant", "content": "found X is 42", "ts": 0.0})
    transcript_save("task_abc", snap)
    loaded = transcript_load("task_abc")
    assert loaded is not None
    assert loaded["goal"] == "research X"
    assert loaded["turns"][-1]["content"] == "found X is 42"


def test_history_load_restores_turns_and_summary():
    h = ConversationHistory(goal="g")
    h.add("assistant", "did stuff")
    snap = h.snapshot()
    snap["summary"] = "earlier we did stuff"

    h2 = ConversationHistory(goal="g")
    h2.load(snap)
    h2.add("user", "now do more")
    prompt = h2.build_prompt()
    assert "earlier we did stuff" in prompt
    assert "did stuff" in prompt
    assert "USER: now do more" in prompt


def test_snapshot_roundtrips_images():
    h = ConversationHistory(goal="g")
    h.images = [ImageContent(mime="image/png", data=b"\x89PNG\r\n\x1a\nfake")]
    h.add("assistant", "looked at the image")

    h2 = ConversationHistory(goal="g")
    h2.load(h.snapshot())
    assert len(h2.images) == 1
    assert h2.images[0].mime == "image/png"
    assert h2.images[0].data == b"\x89PNG\r\n\x1a\nfake"


def test_post_task_rejects_unknown_parent():
    client = TestClient(app)
    r = client.post("/task", json={
        "task": "follow up", "tier": "cheap", "parent_task_id": "task_does_not_exist",
    })
    assert r.status_code == 400 and "not found" in r.json()["detail"]
