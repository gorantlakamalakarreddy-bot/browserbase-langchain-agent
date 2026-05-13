"""
Full Browserbase + LangChain web browsing agent.

Architecture:
  Main Planner  (ReAct agent, all 4 tools)
      └─► browserbase_interactive_task calls interrupt() before executing
              └─► Approval loop resumes with Command(resume={...})

Run:  python agent.py
"""

from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore", message=".*LangGraph.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*create_react_agent.*")
warnings.filterwarnings("ignore", message=".*AgentStatePydantic.*")

from dotenv import load_dotenv

load_dotenv()

_required = ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "OPENAI_API_KEY")
for _var in _required:
    if not os.getenv(_var):
        raise EnvironmentError(f"Missing required environment variable: {_var}")

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command

from tools import (
    browserbase_fetch,
    browserbase_interactive_task,
    browserbase_rendered_extract,
    browserbase_search,
)

# ---------------------------------------------------------------------------
# LLM + agent
# ---------------------------------------------------------------------------

_MODEL = os.getenv("DEEPAGENT_MODEL", "gpt-4o")
llm = ChatOpenAI(model=_MODEL, temperature=0)

_SYSTEM_PROMPT = """\
You are a web research agent with access to a managed cloud browser.

Follow the cost ladder — always start with the cheapest tool that can do the job:

1. browserbase_search   — first call whenever you need to discover URLs.
2. browserbase_fetch    — use when you have a URL and the page is static HTML.
3. browserbase_rendered_extract — use when the page needs JavaScript to render.
4. browserbase_interactive_task — use ONLY when you must click, type, or submit.
   This tool will pause for human approval before it does anything.

Rules:
- Never fabricate content. Always cite the source URL in your final answer.
- If a cheaper tool returns sufficient content, stop escalating.
- Summarise findings clearly and concisely.
"""

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

_THREAD = {"configurable": {"thread_id": "main-session"}}

# ---------------------------------------------------------------------------
# Approval loop helpers
# ---------------------------------------------------------------------------

def _print_approval_prompt(interrupt_value: dict) -> None:
    print("\n" + "=" * 60)
    print("  APPROVAL REQUIRED")
    print("=" * 60)
    print(f"  Tool : browserbase_interactive_task")
    print(f"  URL  : {interrupt_value.get('url', 'N/A')}")
    print(f"  Task : {interrupt_value.get('task', 'N/A')}")
    print("=" * 60)


def _ask_user(interrupt_value: dict) -> Command:
    _print_approval_prompt(interrupt_value)
    while True:
        choice = input("  [A]pprove  [E]dit task  [R]eject  → ").strip().lower()
        if choice in ("a", "approve"):
            return Command(resume={"decision": "approve", "task": interrupt_value.get("task", "")})
        if choice in ("r", "reject"):
            return Command(resume={"decision": "reject"})
        if choice in ("e", "edit"):
            new_task = input("  New task description: ").strip()
            if new_task:
                return Command(resume={"decision": "approve", "task": new_task})
            print("  Task cannot be empty — try again.")
        else:
            print("  Please enter A, E, or R.")


# ---------------------------------------------------------------------------
# Public run() function
# ---------------------------------------------------------------------------

def run(user_input: str) -> str:
    """Run one turn of the agent, handling any approval interrupts."""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_input}]},
        _THREAD,
    )

    # Handle one or more interrupts (approval gates)
    while hasattr(result, "interrupt") or (isinstance(result, dict) and result.get("__interrupt__")):
        interrupt_events = result.get("__interrupt__", [])
        if not interrupt_events:
            break
        # Each interrupt has a .value dict with tool/url/task
        interrupt_value = interrupt_events[0].value if hasattr(interrupt_events[0], "value") else interrupt_events[0]
        resume_cmd = _ask_user(interrupt_value)
        result = agent.invoke(resume_cmd, _THREAD)

    # Extract the last AI message
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for msg in reversed(messages):
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if role in ("ai", "assistant") and getattr(msg, "content", ""):
            return msg.content
    return str(messages[-1].content) if messages else "No response."


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Browserbase Web Agent  (model: {_MODEL})")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break

        try:
            answer = run(user_input)
            print(f"\nAgent: {answer}\n")
        except Exception as exc:
            print(f"\n[ERROR] {exc}\n")
