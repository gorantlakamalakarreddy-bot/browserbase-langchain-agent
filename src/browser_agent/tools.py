"""
Four browser tools on the cost-efficiency ladder.

  Cheapest  →  browserbase_search           (Search API, no session)
  Cheap     →  browserbase_fetch            (Fetch API, static HTML)
  Expensive →  browserbase_rendered_extract  (Stagehand, JS render, read-only)
  Costliest →  browserbase_interactive_task  (Stagehand agent, fires approval gate)
"""

from __future__ import annotations

import ipaddress
import re
import time
from urllib.parse import urlparse

from browserbase import Browserbase
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from langgraph.types import interrupt
from stagehand import Stagehand

from .config import settings
from .logger import get_logger

log = get_logger("browser_agent.tools")

_bb = Browserbase(api_key=settings.browserbase_api_key)
_model_api_key = settings.openai_api_key or settings.anthropic_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_stagehand() -> Stagehand:
    return Stagehand(
        browserbase_api_key=settings.browserbase_api_key,
        browserbase_project_id=settings.browserbase_project_id,
        model_api_key=_model_api_key,
    )


def _release(session_id: str) -> None:
    try:
        _bb.sessions.update(session_id, status="REQUEST_RELEASE")
        log.info("session released | id=%s", session_id)
    except Exception as exc:
        log.warning("session release failed | id=%s | %s", session_id, exc)


def _validate_url(url: str) -> str:
    """
    Reject non-HTTP/HTTPS URLs and private/internal network addresses (SSRF guard).
    Returns the stripped URL if valid, raises ValueError otherwise.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("URL cannot be empty.")

    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"Malformed URL: {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme {parsed.scheme!r} is not allowed. Use http or https.")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL must include a hostname.")

    # Block well-known internal hostnames
    _blocked = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"}
    if host in _blocked:
        raise ValueError(f"Access to {host!r} is not permitted.")

    # Block IP-literal addresses that are private/loopback/reserved
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"Access to private/reserved address {host!r} is not permitted.")
    except ValueError as exc:
        if "not permitted" in str(exc):
            raise
        # Not an IP literal — hostname is fine

    return url


# ---------------------------------------------------------------------------
# TOOL 1 — browserbase_search
# ---------------------------------------------------------------------------


@tool
def browserbase_search(query: str, num_results: int = 5) -> str:
    """
    Search the web via Browserbase Search API. No browser session created.

    Always call this first when no URL is known. Returns titles and URLs only.
    Follow up with browserbase_fetch or browserbase_rendered_extract to read pages.

    Args:
        query: Natural-language search query.
        num_results: Results to return (1-10).
    """
    query = (query or "").strip()
    if not query:
        return "Error: search query cannot be empty."

    num_results = max(1, min(10, num_results))
    log.info("search | query=%r | n=%d", query, num_results)
    t0 = time.perf_counter()

    try:
        response = _bb.search.web(query=query, num_results=num_results)
    except Exception as exc:
        log.error("search API error | %s", exc)
        return f"Search failed: {type(exc).__name__}. Please try again."

    elapsed = time.perf_counter() - t0
    log.info("search done | results=%d | %.2fs", len(response.results), elapsed)

    if not response.results:
        return "No results found."

    return "\n".join(f"{i + 1}. {r.title}\n   {r.url}" for i, r in enumerate(response.results))


# ---------------------------------------------------------------------------
# TOOL 2 — browserbase_fetch
# ---------------------------------------------------------------------------


@tool
def browserbase_fetch(url: str, use_proxy: bool = False, max_chars: int = 12_000) -> str:
    """
    Fetch a static web page via Browserbase Fetch API. No full browser session.

    Strips scripts/styles and returns clean body text. Use for static HTML,
    docs, and landing pages. Escalate to browserbase_rendered_extract if the
    page needs JavaScript to show content.

    Args:
        url: Target URL (must be http or https).
        use_proxy: Enable residential proxy for geo-locked content.
        max_chars: Maximum characters to return (default 12,000).
    """
    try:
        url = _validate_url(url)
    except ValueError as exc:
        return f"Invalid URL: {exc}"

    log.info("fetch | url=%s | proxy=%s", url, use_proxy)
    t0 = time.perf_counter()

    try:
        resp = _bb.fetch_api.create(url=url, proxies=use_proxy)
    except Exception as exc:
        log.error("fetch API error | url=%s | %s", url, exc)
        return f"Fetch failed: {type(exc).__name__}. Please try again."

    soup = BeautifulSoup(resp.content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s{3,}", "\n\n", soup.get_text(separator="\n")).strip()[:max_chars]

    log.info(
        "fetch done | status=%d | chars=%d | %.2fs",
        resp.status_code,
        len(text),
        time.perf_counter() - t0,
    )
    return f"[HTTP {resp.status_code}]\n\n{text}"


# ---------------------------------------------------------------------------
# TOOL 3 — browserbase_rendered_extract
# ---------------------------------------------------------------------------


@tool
def browserbase_rendered_extract(url: str, instruction: str) -> str:
    """
    Open a full Chromium browser session, execute JavaScript, and extract
    content based on a natural-language instruction. Read-only — no clicks.

    Use for SPAs, dashboards, Twitter, LinkedIn, and JS-heavy pages.

    Args:
        url: Target URL (must be http or https).
        instruction: What to extract, e.g. 'get all pricing tiers and features'.
    """
    try:
        url = _validate_url(url)
    except ValueError as exc:
        return f"Invalid URL: {exc}"

    instruction = (instruction or "").strip()
    if not instruction:
        return "Error: instruction cannot be empty."

    log.info("rendered_extract | url=%s", url)
    t0 = time.perf_counter()

    sh = _new_stagehand()
    bb_session = _bb.sessions.create(project_id=settings.browserbase_project_id)
    log.info("bb session created | id=%s", bb_session.id)

    sh_session_id = ""
    try:
        sh_resp = sh.sessions.start(
            model_name=settings.stagehand_model,
            browserbase_session_id=bb_session.id,
        )
        sh_session_id = sh_resp.data.session_id

        sh.sessions.navigate(sh_session_id, url=url)
        result = sh.sessions.extract(sh_session_id, instruction=instruction)

        log.info("rendered_extract done | %.2fs", time.perf_counter() - t0)
        return str(result.data.result)
    except Exception as exc:
        log.error("rendered_extract error | url=%s | %s", url, exc)
        return (
            f"Extraction failed: {type(exc).__name__}. The page may have changed or blocked access."
        )
    finally:
        if sh_session_id:
            try:
                sh.sessions.end(sh_session_id)
            except Exception:
                pass
        _release(bb_session.id)


# ---------------------------------------------------------------------------
# TOOL 4 — browserbase_interactive_task
# ---------------------------------------------------------------------------


@tool
def browserbase_interactive_task(url: str, task: str) -> str:
    """
    Open a Chromium session and perform a multi-step interactive task via
    Stagehand AI agent. Supports clicking, typing, forms, logins, navigation
    (up to 20 steps). ALWAYS triggers the Human Approval Gate first.

    Use ONLY when search, fetch, or rendered_extract cannot do the job.

    Args:
        url: Starting URL (must be http or https).
        task: Plain-English description of every step to perform.
    """
    try:
        url = _validate_url(url)
    except ValueError as exc:
        return f"Invalid URL: {exc}"

    task = (task or "").strip()
    if not task:
        return "Error: task description cannot be empty."

    log.info("interactive_task | url=%s | awaiting approval", url)

    decision = interrupt(
        {
            "tool": "browserbase_interactive_task",
            "url": url,
            "task": task,
            "message": "Interactive browser action requires your approval.",
        }
    )

    if isinstance(decision, dict) and decision.get("decision") == "reject":
        log.info("interactive_task | rejected by user")
        return "Action rejected by user. No browser session was opened."

    if isinstance(decision, dict) and decision.get("task"):
        task = decision["task"].strip() or task

    log.info("interactive_task | approved | url=%s", url)
    t0 = time.perf_counter()

    sh = _new_stagehand()
    bb_session = _bb.sessions.create(project_id=settings.browserbase_project_id)
    log.info("bb session created | id=%s", bb_session.id)

    sh_session_id = ""
    try:
        sh_resp = sh.sessions.start(
            model_name=settings.stagehand_agent_model,
            browserbase_session_id=bb_session.id,
        )
        sh_session_id = sh_resp.data.session_id

        sh.sessions.navigate(sh_session_id, url=url)
        result = sh.sessions.execute(
            sh_session_id,
            agent_config={"model": settings.stagehand_agent_model},
            execute_options={"instruction": task, "max_steps": 20},
        )

        log.info("interactive_task done | %.2fs", time.perf_counter() - t0)
        return str(result.data.result)
    except Exception as exc:
        log.error("interactive_task error | url=%s | %s", url, exc)
        return f"Interactive task failed: {type(exc).__name__}."
    finally:
        if sh_session_id:
            try:
                sh.sessions.end(sh_session_id)
            except Exception:
                pass
        _release(bb_session.id)
