from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(InputModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password", mode="before")
    @classmethod
    def preserve_password(cls, value: str) -> str:
        # Password spaces are significant, unlike names and conversation titles.
        return value

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class UserOut(BaseModel):
    id: str
    username: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ConversationCreate(InputModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime


class MessageCreate(InputModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=16000)


class MessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    client_message_id: str | None
    created_at: datetime


RunStatus = Literal[
    "queued",
    "running",
    "waiting_user",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
]


class RunOut(BaseModel):
    id: str
    session_id: str
    message_id: str
    status: RunStatus
    tool_calls: int
    external_requests: int
    llm_calls: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
