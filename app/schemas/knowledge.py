from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.api import InputModel


class DocumentCreate(InputModel):
    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(default="", max_length=512)
    content: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1,
        max_length=100_000,
    )
    scope: Literal["user", "session"] = "session"
    session_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self):
        if not self.content.strip():
            raise ValueError("资料正文不能为空")
        if (self.scope == "session") != bool(self.session_id):
            raise ValueError("会话资料必须指定会话；用户知识库不能指定会话")
        return self


class DocumentOut(BaseModel):
    id: str
    title: str
    source_ref: str
    scope: Literal["user", "session"]
    session_id: str | None
    document_version: int
    content_hash: str
    chunk_count: int
    created_at: datetime


class KnowledgeSearch(InputModel):
    session_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=16_000)
    limit: int = Field(default=5, ge=1, le=5)
