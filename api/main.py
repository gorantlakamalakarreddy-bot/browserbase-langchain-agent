"""
FastAPI application — REST + SSE streaming interface for the browser agent.

Endpoints:
  GET  /api/health                      → health check
  POST /api/chat                        → start a chat turn (SSE stream)
  POST /api/approve/{thread_id}         → resume after approval gate (SSE stream)
  GET  /                                → serves the frontend SPA
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

from api.models import ApproveRequest, ChatRequest
from browser_agent.agent import agent, extract_final_message
from browser_agent.logger import get_logger

log = get_logger("api")

app = FastAPI(title="Browserbase Web Agent", version="1.0.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_graph(input_, thread_id: str):
    """Yield SSE events from a LangGraph astream_events call."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for event in agent.astream_events(input_, config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                raw_input = event["data"].get("input", {})
                yield _sse({
                    "type": "tool_start",
                    "tool": name,
                    "input": str(raw_input)[:300],
                })

            elif kind == "on_tool_end":
                yield _sse({"type": "tool_end", "tool": name})

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse({"type": "token", "content": chunk.content})

    except Exception as exc:
        log.warning("stream error: %s", exc)

    # Check for pending interrupt (approval gate)
    state = agent.get_state(config)
    for task in state.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            iv = task.interrupts[0].value
            log.info("interrupt pending | thread=%s | url=%s", thread_id, iv.get("url"))
            yield _sse({"type": "approval_required", "thread_id": thread_id, **iv})
            return

    # Normal completion — extract final AI message
    messages = state.values.get("messages", [])
    for msg in reversed(messages):
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if role in ("ai", "assistant") and getattr(msg, "content", ""):
            yield _sse({"type": "done", "content": msg.content})
            return

    yield _sse({"type": "done", "content": "No response generated."})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "model": agent.get_graph().name if hasattr(agent, "get_graph") else "ready"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    log.info("chat | thread=%s | message=%r", req.thread_id, req.message[:80])
    input_ = {"messages": [{"role": "user", "content": req.message}]}

    return StreamingResponse(
        _stream_graph(input_, req.thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/approve/{thread_id}")
async def approve(thread_id: str, req: ApproveRequest):
    log.info("approve | thread=%s | decision=%s", thread_id, req.decision)
    resume = {"decision": req.decision}
    if req.task:
        resume["task"] = req.task

    return StreamingResponse(
        _stream_graph(Command(resume=resume), thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Mount frontend — MUST be last so API routes take precedence
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
