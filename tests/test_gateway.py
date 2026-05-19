"""Gateway: data URI parsing + skill validation on POST /task."""

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.gateway.server import _parse_data_uri, app


def _png_data_uri():
    # 1x1 transparent PNG
    raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def test_parse_data_uri_accepts_and_reencodes_to_jpeg():
    # All accepted inputs are downsampled + re-encoded to JPEG at the gateway,
    # so the resulting ImageContent is always image/jpeg regardless of source mime.
    img = _parse_data_uri(_png_data_uri())
    assert img.mime == "image/jpeg" and isinstance(img.data, bytes) and len(img.data) > 0


def test_parse_data_uri_rejects_garbage():
    with pytest.raises(ValueError):
        _parse_data_uri("not a data uri at all")


def test_post_task_rejects_unknown_skill_path():
    client = TestClient(app)
    r = client.post("/task", json={"task": "hi", "tier": "cheap", "skills": ["nonsense/fake.md"]})
    assert r.status_code == 400 and "unknown skill" in r.json()["detail"]


def test_post_task_rejects_unknown_grader_path():
    client = TestClient(app)
    r = client.post("/task", json={"task": "hi", "tier": "cheap", "graders": ["nonsense/fake.md"]})
    assert r.status_code == 400 and "unknown grader" in r.json()["detail"]


def test_graders_and_presets_endpoints():
    client = TestClient(app)
    g = client.get("/graders").json()
    assert any(x["path"] == "general/article-voice.md" for x in g)
    # /graders/suggest matches the article-writer skill to the article-voice grader.
    sug = client.get("/graders/suggest?skills=general/article-writer/SKILL.md").json()
    assert any(x["path"] == "general/article-voice.md" for x in sug)
    # /presets returns the article-writing preset with both skill + grader bundled.
    p = client.get("/presets").json()
    article = next((x for x in p if x["name"] == "article-writing"), None)
    assert article is not None
    assert "general/article-writer/SKILL.md" in article["skills"]
    assert "general/article-voice.md" in article["graders"]
