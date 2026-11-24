from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.maps import MapSearchResult, WorkflowEvent


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


class LoginCredentials(Credentials):
    remember_me: bool = Field(default=False, strict=True)


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


class RetrievalSource(BaseModel):
    label: str
    cited: bool
    available: bool = True
    source_kind: Literal["private_knowledge"] | None = None
    scope: Literal["user", "session"] | None = None
    document_id: str | None = None
    document_version: int | None = None
    chunk_id: str | None = None
    title: str | None = None
    source_ref: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    excerpt: str | None = None
    content_hash: str | None = None
    document_hash: str | None = None
    retrieval_method: Literal["lexical"] | None = None
    retrieved_at: datetime | None = None


class MessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    client_message_id: str | None
    created_at: datetime
    sources: list[RetrievalSource] = Field(default_factory=list)
    retrieval_status: Literal["no_matches", "retrieved"] | None = None
    map_result: MapSearchResult | None = None


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
    workflow_events: list[WorkflowEvent] = Field(default_factory=list)
