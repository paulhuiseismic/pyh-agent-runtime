from typing import Literal

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    session_id: str | None = None


class AgentRunResult(BaseModel):
    status: Literal["success"] = "success"
    answer: str
    session_id: str | None = None


class InboundMessage(BaseModel):
    channel_id: str = Field(min_length=1)
    external_message_id: str = Field(min_length=1)
    sender: str = Field(min_length=1)
    text: str = Field(min_length=1)
    conversation_id: str | None = None


class InboundAcceptResult(BaseModel):
    accepted: bool
    duplicate: bool
