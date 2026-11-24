from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.itinerary import Itinerary, RouteObservation, TripRequest
from app.schemas.planning import Place

Specialist = Literal["places", "activity", "dining"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Assignment(StrictModel):
    agent: Specialist
    keyword: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=500)


class NearbyContext(StrictModel):
    anchor_name: str
    tasks: list[Assignment] = Field(min_length=1, max_length=2)
    destination: Place | None = None


class SupervisorDecision(StrictModel):
    kind: Literal["answer", "clarify", "search", "plan", "nearby"]
    answer: str = Field(default="", max_length=16000)
    city: str = Field(default="", max_length=80)
    tasks: list[Assignment] = Field(default_factory=list, max_length=2)
    trip: TripRequest | None = None
    anchor_name: str = Field(default="", max_length=80)
    area_limit: int | None = Field(default=None, ge=1, le=2)

    @model_validator(mode="after")
    def check_decision(self):
        if self.kind in {"search", "plan", "nearby"} and not self.tasks:
            raise ValueError("Search requires a delegated task")
        if self.kind not in {"search", "plan", "nearby"} and (not self.answer or self.tasks):
            raise ValueError("Answers require text and cannot contain tasks")
        if self.kind == "plan" and self.trip is None:
            raise ValueError("Itinerary requires a time window")
        if self.kind != "plan" and self.trip is not None:
            raise ValueError("Only planning accepts a trip")
        return self


class SearchArguments(StrictModel):
    keyword: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    limit: int = Field(default=5, ge=1, le=5)


class RevisionRequest(StrictModel):
    task_id: str
    task_version: int = Field(ge=1)
    feedback: str = Field(min_length=1, max_length=500)


class SupervisorReview(StrictModel):
    decision: Literal["approve", "revise", "clarify"]
    answer: str = Field(default="", max_length=16000)
    # The supervisor can only select references to provider observations, never author POIs.
    selected_ids: list[str] = Field(default_factory=list, max_length=10)
    revisions: list[RevisionRequest] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def check_review(self):
        if self.decision == "revise":
            if not self.revisions or self.selected_ids:
                raise ValueError("Revision requires feedback and cannot publish places")
        elif not self.answer or self.revisions:
            raise ValueError("A completed review requires an answer without revisions")
        if self.decision == "clarify" and self.selected_ids:
            raise ValueError("Clarification cannot publish places")
        return self


class WorkflowEvent(BaseModel):
    stage: Literal[
        "route",
        "dispatch",
        "search",
        "review",
        "revise",
        "complete",
        "clarify",
        "limit",
        "research",
        "plan",
        "travel",
        "validate",
    ]
    agent: Literal["supervisor", "places", "activity", "dining", "itinerary"]
    task_id: str | None = None
    task_version: int | None = None
    summary: str = Field(max_length=600)


class MapPlace(Place):
    label: str
    task_id: str
    agent: Specialist


class RecommendationGroup(BaseModel):
    area: Place
    answer: str
    place_ids: list[str]
    route: RouteObservation | None = None


class MapSearchResult(BaseModel):
    status: Literal["approved", "no_results", "revision_limit", "needs_clarification"]
    city: str
    places: list[MapPlace] = Field(default_factory=list)
    review_rounds: int = Field(ge=0)
    events: list[WorkflowEvent] = Field(default_factory=list)
    searched_at: datetime
    itinerary: Itinerary | None = None
    recommendation_groups: list[RecommendationGroup] = Field(default_factory=list, max_length=2)
    recommendation_context: NearbyContext | None = None
