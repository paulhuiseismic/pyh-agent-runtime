from typing import Literal

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    session_id: str | None = None


class AgentRunResult(BaseModel):
    status: Literal["success"] = "success"
    answer: str
    session_id: str | None = None
