"""
Unit tests for the API layer — FastAPI test client, no real LLM calls.
Run:  pytest tests/test_agent.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("BROWSERBASE_API_KEY", "bb_live_test")
os.environ.setdefault("BROWSERBASE_PROJECT_ID", "test-project")
os.environ.setdefault("OPENAI_API_KEY", "test-openai")


def _make_mock_agent(content: str = "Test response"):
    """Return a mock agent whose astream_events yields one token then ends."""

    async def fake_astream(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": MagicMock(content=content)},
        }

    state = MagicMock()
    state.tasks = []
    state.values = {"messages": [MagicMock(type="ai", content=content)]}

    mock = MagicMock()
    mock.astream_events = fake_astream
    mock.get_state.return_value = state
    return mock


# ── Health ────────────────────────────────────────────────────────────────────


def test_health_endpoint():
    from api.main import app

    with patch("api.main.agent", _make_mock_agent()):
        client = TestClient(app)
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Chat ──────────────────────────────────────────────────────────────────────


def test_chat_returns_sse_stream():
    from api.main import app

    with patch("api.main.agent", _make_mock_agent("Hello from agent")):
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "hi", "thread_id": "t1"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data:" in resp.text


def test_chat_rejects_empty_message():
    from api.main import app

    client = TestClient(app)
    resp = client.post("/api/chat", json={"message": "   ", "thread_id": "t1"})
    assert resp.status_code == 422


def test_chat_rejects_oversized_message():
    from api.main import app

    client = TestClient(app)
    resp = client.post("/api/chat", json={"message": "x" * 10_001, "thread_id": "t1"})
    assert resp.status_code == 422


def test_chat_rejects_invalid_thread_id():
    from api.main import app

    client = TestClient(app)
    resp = client.post("/api/chat", json={"message": "hello", "thread_id": "bad/id!"})
    assert resp.status_code == 422


# ── Approve ───────────────────────────────────────────────────────────────────


def test_approve_rejects_invalid_decision():
    from api.main import app

    client = TestClient(app)
    resp = client.post("/api/approve/t1", json={"decision": "maybe"})
    assert resp.status_code == 422


def test_approve_valid_reject():
    from api.main import app

    with patch("api.main.agent", _make_mock_agent()):
        client = TestClient(app)
        resp = client.post("/api/approve/t1", json={"decision": "reject"})
    assert resp.status_code == 200


# ── Security headers ──────────────────────────────────────────────────────────


def test_security_headers_present():
    from api.main import app

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
