from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.core.identity import AuthContext


class SearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: Literal["user", "session"]
    session_id: str | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    document_version: int
    text: str
    source_ref: str


class PrivateRetriever(Protocol):
    """Implementations must authorize the scope and filter BEFORE top-k/reranking."""

    async def search(
        self, *, auth: AuthContext, scope: SearchScope, query: str, limit: int
    ) -> list[SearchHit]: ...
