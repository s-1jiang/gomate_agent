from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.schemas.itinerary import RouteObservation
from app.schemas.planning import Place
from app.tools.budget import RunBudget


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str


class LanguageModel(Protocol):
    async def complete(
        self, messages: list[ChatMessage], budget: RunBudget, *, json_mode: bool = False
    ) -> str: ...


class MapProvider(Protocol):
    """Target contract: implement AMap REST calls behind the trusted tool gateway."""

    async def search_places(
        self, *, keyword: str, city: str, limit: int, budget: RunBudget
    ) -> list[Place]: ...

    async def get_route(
        self,
        *,
        origin: Place,
        destination: Place,
        mode: str,
        departure_at: datetime,
        budget: RunBudget,
    ) -> RouteObservation: ...
