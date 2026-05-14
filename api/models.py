from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    thread_id: str = Field(default="default", min_length=1, max_length=128)

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be blank")
        return v.strip()

    @field_validator("thread_id")
    @classmethod
    def thread_id_safe(cls, v: str) -> str:
        # Allow only alphanumeric, hyphens, underscores
        if not re.match(r"^[\w\-]+$", v):
            raise ValueError("thread_id must contain only letters, digits, hyphens, or underscores")
        return v


class ApproveRequest(BaseModel):
    decision: Literal["approve", "reject"]
    task: str = Field(default="", max_length=5_000)

    @field_validator("task")
    @classmethod
    def strip_task(cls, v: str) -> str:
        return v.strip()
