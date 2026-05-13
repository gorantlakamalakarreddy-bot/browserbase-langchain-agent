"""
Four browser tools on the cost-efficiency ladder.

  Cheapest  →  browserbase_search          (Search API, no session)
  Cheap     →  browserbase_fetch           (Fetch API, static HTML)
  Expensive →  browserbase_rendered_extract (Stagehand, read-only)
  Costliest →  browserbase_interactive_task (Stagehand agent, fires approval gate)
"""

from __future__ import annotations

import os
import re

from bs4 import BeautifulSoup
from browserbase import Browserbase
from langchain_core.tools import tool
from langgraph.types import interrupt
from stagehand import Stagehand

_bb = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
_project_id = os.environ["BROWSERBASE_PROJECT_ID"]

_STAGEHAND_MODEL = os.getenv("STAGEHAND_MODEL", "openai/gpt-4o")
_STAGEHAND_AGENT_MODEL = os.getenv("STAGEHAND_AGENT_MODEL", "anthropic/claude-sonnet-4-6")
_MODEL_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")


def _new_stagehand(model_api_key: str | None = None) -> Stagehand:
    return Stagehand(
        browserbase_api_key=os.environ["BROWSERBASE_API_KEY"],
        browserbase_project_id=_project_id,
        model_api_key=model_api_key or _MODEL_API_KEY,
    )


def _release_bb_session(session_id: str) -> None:
    try:
        _bb.sessions.update(session_id, status="REQUEST_RELEASE")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TOOL 1 — browserbase_search
# ---------------------------------------------------------------------------

@tool
def browserbase_search(query: str, num_results: int = 5) -> str:
    """
    Search the web via Browserbase Search API. No browser session created.

    Always use this first when no URL is known. Returns titles and URLs only —
    no page content. Use browserbase_fetch or browserbase_rendered_extract to
    read the actual pages.

    Args:
        query: Natural-language search query.
        num_results: Number of results to return (1–10).
    """
    num_results = max(1, min(10, num_results))
    response = _bb.search.web(query=query, num_results=num_results)
    results = response.results
    if not results:
        return "No results found."
    lines = [
        f"{i + 1}. {r.title}\n   {r.url}"
        for i, r in enumerate(results)
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 2 — browserbase_fetch
# ---------------------------------------------------------------------------

@tool
def browserbase_fetch(url: str, use_proxy: bool = False, max_chars: int = 12_000) -> str:
    """
    Fetch a static web page via Browserbase Fetch API. No full browser session.

    Strips scripts/styles and returns clean body text. Use for static HTML,
    docs, and landing pages. Escalate to browserbase_rendered_extract if the
    page requires JavaScript to show its content.

    Args:
        url: Target URL.
        use_proxy: Enable residential proxy for geo-locked content.
        max_chars: Maximum characters to return (default 12,000).
    """
    resp = _bb.fetch_api.create(url=url, proxies=use_proxy)

    soup = BeautifulSoup(resp.content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s{3,}", "\n\n", soup.get_text(separator="\n")).strip()
    text = text[:max_chars]

    return f"[HTTP {resp.status_code}]\n\n{text}"


# ---------------------------------------------------------------------------
# TOOL 3 — browserbase_rendered_extract
# ---------------------------------------------------------------------------

@tool
def browserbase_rendered_extract(url: str, instruction: str) -> str:
    """
    Open a full Chromium browser session, render the page (executes JavaScript),
    and extract content based on a natural-language instruction.

    Read-only — does NOT click, type, or submit anything.
    Use for SPAs, dashboards, Twitter, LinkedIn, and JS-heavy pages.

    Args:
        url: Target URL.
        instruction: What to extract, e.g. 'get all pricing tiers and features'.
    """
    sh = _new_stagehand()
    bb_session = _bb.sessions.create(project_id=_project_id)

    try:
        sh_session = sh.sessions.start(
            model_name=_STAGEHAND_MODEL,
            browserbase_session_id=bb_session.id,
        )
        session_id = sh_session.data.session_id

        sh.sessions.navigate(session_id, url=url)
        result = sh.sessions.extract(session_id, instruction=instruction)
        return str(result.data.result)
    finally:
        try:
            sh.sessions.end(session_id)
        except Exception:
            pass
        _release_bb_session(bb_session.id)


# ---------------------------------------------------------------------------
# TOOL 4 — browserbase_interactive_task
# ---------------------------------------------------------------------------

@tool
def browserbase_interactive_task(url: str, task: str) -> str:
    """
    Open a Chromium session and perform a multi-step interactive task via
    Stagehand's AI agent. Supports clicking, typing, form submission, login
    flows, and multi-step navigation (up to 20 steps).

    ALWAYS triggers the Human Approval Gate before execution begins.
    Use ONLY when search, fetch, or rendered_extract cannot accomplish the goal.

    Args:
        url: Starting URL for the task.
        task: Plain-English description of all steps to perform.
    """
    # Pause execution and surface the pending action for human review.
    decision = interrupt({
        "tool": "browserbase_interactive_task",
        "url": url,
        "task": task,
        "message": "Interactive browser action requires your approval.",
    })

    if isinstance(decision, dict):
        if decision.get("decision") == "reject":
            return "Action rejected by user. No browser session was opened."
        # User may have edited the task
        task = decision.get("task", task)

    sh = _new_stagehand()
    bb_session = _bb.sessions.create(project_id=_project_id)
    session_id: str = ""

    try:
        sh_session = sh.sessions.start(
            model_name=_STAGEHAND_AGENT_MODEL,
            browserbase_session_id=bb_session.id,
        )
        session_id = sh_session.data.session_id

        sh.sessions.navigate(session_id, url=url)
        result = sh.sessions.execute(
            session_id,
            agent_config={"model": _STAGEHAND_AGENT_MODEL},
            execute_options={"instruction": task, "max_steps": 20},
        )
        return str(result.data.result)
    finally:
        if session_id:
            try:
                sh.sessions.end(session_id)
            except Exception:
                pass
        _release_bb_session(bb_session.id)
