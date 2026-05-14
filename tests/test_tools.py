"""
Unit tests for browser tools — all Browserbase/Stagehand clients are mocked.
Run:  pytest tests/test_tools.py
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("BROWSERBASE_API_KEY", "test-key")
os.environ.setdefault("BROWSERBASE_PROJECT_ID", "test-project")
os.environ.setdefault("OPENAI_API_KEY", "test-openai")


# ── browserbase_search ────────────────────────────────────────────────────────

def test_search_returns_formatted_results():
    mock_result = MagicMock()
    mock_result.title = "LangChain Docs"
    mock_result.url   = "https://docs.langchain.com"

    mock_response = MagicMock()
    mock_response.results = [mock_result]

    with patch("browser_agent.tools._bb") as mock_bb:
        mock_bb.search.web.return_value = mock_response
        from browser_agent.tools import browserbase_search
        result = browserbase_search.invoke({"query": "LangChain", "num_results": 1})

    assert "LangChain Docs" in result
    assert "https://docs.langchain.com" in result
    mock_bb.search.web.assert_called_once_with(query="LangChain", num_results=1)


def test_search_clamps_num_results():
    mock_response = MagicMock()
    mock_response.results = []

    with patch("browser_agent.tools._bb") as mock_bb:
        mock_bb.search.web.return_value = mock_response
        from browser_agent.tools import browserbase_search
        browserbase_search.invoke({"query": "test", "num_results": 99})
        _, kwargs = mock_bb.search.web.call_args
        assert kwargs["num_results"] <= 10


def test_search_empty_returns_message():
    mock_response = MagicMock()
    mock_response.results = []

    with patch("browser_agent.tools._bb") as mock_bb:
        mock_bb.search.web.return_value = mock_response
        from browser_agent.tools import browserbase_search
        result = browserbase_search.invoke({"query": "nothing"})

    assert "No results" in result


# ── browserbase_fetch ─────────────────────────────────────────────────────────

def test_fetch_strips_scripts_and_returns_text():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = "<html><body><script>alert(1)</script><p>Hello world</p></body></html>"

    with patch("browser_agent.tools._bb") as mock_bb:
        mock_bb.fetch_api.create.return_value = mock_resp
        from browser_agent.tools import browserbase_fetch
        result = browserbase_fetch.invoke({"url": "https://example.com"})

    assert "[HTTP 200]" in result
    assert "Hello world" in result
    assert "alert" not in result


def test_fetch_truncates_at_max_chars():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = f"<p>{'x' * 20_000}</p>"

    with patch("browser_agent.tools._bb") as mock_bb:
        mock_bb.fetch_api.create.return_value = mock_resp
        from browser_agent.tools import browserbase_fetch
        result = browserbase_fetch.invoke({"url": "https://example.com", "max_chars": 500})

    content = result.split("\n\n", 1)[-1]
    assert len(content) <= 500


# ── browserbase_rendered_extract ─────────────────────────────────────────────

def test_rendered_extract_calls_stagehand_and_releases_session():
    bb_session = MagicMock(); bb_session.id = "bb-123"
    sh_resp    = MagicMock(); sh_resp.data.session_id = "sh-456"
    extract    = MagicMock(); extract.data.result = "Extracted content"

    with patch("browser_agent.tools._bb") as mock_bb, \
         patch("browser_agent.tools._new_stagehand") as mock_sh_factory:

        mock_bb.sessions.create.return_value = bb_session
        sh = MagicMock()
        sh.sessions.start.return_value    = sh_resp
        sh.sessions.extract.return_value  = extract
        mock_sh_factory.return_value = sh

        from browser_agent.tools import browserbase_rendered_extract
        result = browserbase_rendered_extract.invoke({
            "url": "https://example.com",
            "instruction": "get all text",
        })

    assert result == "Extracted content"
    sh.sessions.end.assert_called_once_with("sh-456")
    mock_bb.sessions.update.assert_called_once_with("bb-123", status="REQUEST_RELEASE")
