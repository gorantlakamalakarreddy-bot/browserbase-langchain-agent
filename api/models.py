from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ApproveRequest(BaseModel):
    decision: str   # "approve" or "reject"
    task: str = "" # optionally override the task when approving
