"""
LangGraph ReAct agent wiring all four browser tools together.
Imported by the API layer and the CLI runner.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message=".*create_react_agent.*")
warnings.filterwarnings("ignore", message=".*AgentStatePydantic.*")

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from .config import settings
from .logger import get_logger
from .tools import (
    browserbase_fetch,
    browserbase_interactive_task,
    browserbase_rendered_extract,
    browserbase_search,
)

log = get_logger("browser_agent.agent")

_SYSTEM_PROMPT = """\
You are a web research agent with access to a managed cloud browser.

Follow the cost ladder — always use the cheapest tool that can do the job:

1. browserbase_search          — first call whenever you need to discover URLs.
2. browserbase_fetch           — use when the page is static HTML.
3. browserbase_rendered_extract — use when the page requires JavaScript to render.
4. browserbase_interactive_task — use ONLY when you must click, type, or submit.
   This tool will pause for human approval before executing.

Rules:
- Never fabricate content. Always cite the source URL in your final answer.
- If a cheaper tool returns sufficient content, do not escalate.
- Summarise findings clearly and concisely in Markdown.
"""

llm = ChatOpenAI(model=settings.planner_model, temperature=0, api_key=settings.openai_api_key)
checkpointer = MemorySaver()

agent = create_react_agent(
    model=llm,
    tools=[
        browserbase_search,
        browserbase_fetch,
        browserbase_rendered_extract,
        browserbase_interactive_task,
    ],
    prompt=_SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

log.info("agent ready | model=%s", settings.planner_model)


def extract_final_message(result: dict) -> str:
    """Pull the last AI message text out of a graph result dict."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if role in ("ai", "assistant") and getattr(msg, "content", ""):
            return msg.content
    return ""
