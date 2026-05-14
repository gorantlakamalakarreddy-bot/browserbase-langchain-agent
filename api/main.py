"""
FastAPI application — REST + SSE streaming interface for the browser agent.

Endpoints:
  GET  /api/health                      -> health check
  POST /api/chat                        -> start a chat turn (SSE stream)
  POST /api/approve/{thread_id}         -> resume after approval gate (SSE stream)
  GET  /                                -> serves the frontend SPA
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from starlette.middleware.base import BaseHTTPMiddleware

from api.models import ApproveRequest, ChatRequest
from browser_agent.agent import agent
from browser_agent.config import settings
from browser_agent.logger import get_logger

log = get_logger("api")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup | model=%s | cors=%s", settings.planner_model, settings.cors_origins)
    yield
    log.info("shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


app = FastAPI(
    title="Browserbase Web Agent",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)


# ── Middlewares ──────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


class _MaxBodySize(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit."""

    async def dispatch(self, request: Request, call_next: object):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and int(cl) > settings.max_body_bytes:
                return Response("Request body too large", status_code=413)
        return await call_next(request)  # type: ignore[arg-type]


app.add_middleware(_MaxBodySize)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.update(
        {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
    )
    return response


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_graph(input_, thread_id: str):
    """Yield SSE events from a LangGraph astream_events call then emit done/interrupt."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for event in agent.astream_events(input_, config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                raw_input = event["data"].get("input", {})
                yield _sse(
                    {
                        "type": "tool_start",
                        "tool": name,
                        "input": str(raw_input)[:300],
                    }
                )

            elif kind == "on_tool_end":
                yield _sse({"type": "tool_end", "tool": name})

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse({"type": "token", "content": chunk.content})

    except Exception as exc:
        log.warning("stream interrupted | thread=%s | %s", thread_id, type(exc).__name__)

    # Check for pending interrupt (approval gate)
    try:
        state = agent.get_state(config)
    except Exception as exc:
        log.error("get_state failed | %s", exc)
        yield _sse({"type": "error", "message": "Internal error retrieving agent state."})
        return

    for task in state.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            iv = task.interrupts[0].value
            log.info("interrupt pending | thread=%s | url=%s", thread_id, iv.get("url"))
            yield _sse({"type": "approval_required", "thread_id": thread_id, **iv})
            return

    # Normal completion — extract last AI message from state
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
    try:
        graph_name = agent.get_graph().name
    except Exception:
        graph_name = "LangGraph"
    return {"status": "ok", "model": settings.planner_model, "graph": graph_name}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    log.info("chat | thread=%s | len=%d", req.thread_id, len(req.message))
    input_ = {"messages": [{"role": "user", "content": req.message}]}

    return StreamingResponse(
        _stream_graph(input_, req.thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/approve/{thread_id}")
async def approve(thread_id: str, req: ApproveRequest):
    # Re-validate thread_id from path (the model validator applies only to body fields)
    import re as _re

    if not _re.match(r"^[\w\-]+$", thread_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid thread_id")

    log.info("approve | thread=%s | decision=%s", thread_id, req.decision)
    resume: dict = {"decision": req.decision}
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
