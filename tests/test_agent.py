"""
Unit tests for the API layer — FastAPI test client, no real LLM calls.
Run:  pytest tests/test_agent.py
"""

import sys
import os

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("BROWSERBASE_API_KEY", "test-key")
os.environ.setdefault("BROWSERBASE_PROJECT_ID", "test-project")
os.environ.setdefault("OPENAI_API_KEY", "test-openai")


def _make_mock_agent(content="Test response"):
    """Return a mock agent that streams a single 'done' SSE event."""
    async def fake_astream(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": MagicMock(content=content)},
        }

    state = MagicMock()
    state.tasks = []
    state.values = {
        "messages": [MagicMock(type="ai", content=content)]
    }

    mock_agent = MagicMock()
    mock_agent.astream_events = fake_astream
    mock_agent.get_state.return_value = state
    return mock_agent


def test_health_endpoint():
    with patch("browser_agent.agent.agent", _make_mock_agent()):
        from api.main import app
        client = TestClient(app)
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_returns_sse_stream():
    mock_agent = _make_mock_agent("Hello from agent")

    with patch("api.main.agent", mock_agent):
        from api.main import app
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": "hi", "thread_id": "t1"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data:" in resp.text
