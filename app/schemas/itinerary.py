from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.planning import Place

Transport = Literal["walking", "driving", "transit"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DayWindow(Strict):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def check_window(self):
        if not timedelta(0) < self.end_at - self.start_at <= timedelta(hours=18):
            raise ValueError("A daily window must be within 18 hours")
        if any(value.utcoffset() != timedelta(hours=8) for value in (self.start_at, self.end_at)):
            raise ValueError("Use China time with +08:00 offset")
        return self


class TripRequest(Strict):
    days: list[DayWindow] = Field(min_length=1, max_length=3)
    origin_name: str = Field(default="", max_length=80)
    return_to_origin: bool = False
    mode: Transport = "transit"
    party_size: int = Field(default=1, ge=1, le=20)
    budget_fen: int | None = Field(default=None, ge=0)
    budget_scope: Literal["per_person", "total"] = "per_person"
    max_walking_meters: int | None = Field(default=None, ge=0, le=100000)
    buffer_minutes: int = Field(default=10, ge=0, le=30)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    requirements: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def check_days(self):
        if self.return_to_origin and not self.origin_name:
            raise ValueError("A return trip needs an origin")
        for previous, current in zip(self.days, self.days[1:], strict=False):
            if current.start_at <= previous.end_at:
                raise ValueError("Day windows must be ordered and separate")
        return self


class ActivityDetail(Strict):
    text: str = Field(min_length=1, max_length=350)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)


class StopDraft(Strict):
    poi_id: str
    duration_minutes: int = Field(ge=15, le=240)
    kind: Literal["visit", "meal", "break"] = "visit"
    reason: str = Field(min_length=1, max_length=350)
    activities: list[ActivityDetail] = Field(min_length=1, max_length=5)
    practical_info: list[ActivityDetail] = Field(default_factory=list, max_length=4)


class DayDraft(Strict):
    window_index: int = Field(ge=0, le=2)
    stops: list[StopDraft] = Field(min_length=1, max_length=5)


class ItineraryDraft(Strict):
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=700)
    days: list[DayDraft] = Field(min_length=1, max_length=3)


class PlanReview(Strict):
    task_version: int = Field(ge=1)
    decision: Literal["approve", "revise", "clarify"]
    feedback: str = Field(default="", max_length=1000)
    answer: str = Field(default="", max_length=700)

    @model_validator(mode="after")
    def check_feedback(self):
        if self.decision != "approve" and not (self.feedback or self.answer):
            raise ValueError("Review needs actionable feedback")
        return self


class WebEvidence(BaseModel):
    label: str
    poi_id: str
    provider: Literal["tavily"] = "tavily"
    title: str
    url: str
    excerpt: str
    fetched_at: AwareDatetime


class RouteObservation(BaseModel):
    origin_poi_id: str
    destination_poi_id: str
    mode: Transport
    distance_meters: int = Field(ge=0, le=2000000)
    walking_meters: int = Field(ge=0, le=2000000)
    duration_seconds: int = Field(ge=0, le=86400)
    instructions: list[str] = Field(default_factory=list)
    paths: list[list[tuple[float, float]]] = Field(default_factory=list)
    source_ref: str
    fetched_at: AwareDatetime


class ScheduledLeg(RouteObservation):
    label: str
    origin_name: str
    destination_name: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    duration_minutes: int
    buffer_minutes: int


class ScheduledStop(StopDraft):
    label: str
    name: str
    arrival_at: AwareDatetime
    departure_at: AwareDatetime


class ScheduledDay(BaseModel):
    start_at: AwareDatetime
    deadline: AwareDatetime
    finish_at: AwareDatetime
    spare_minutes: int
    stops: list[ScheduledStop]
    legs: list[ScheduledLeg]
    total_travel_minutes: int
    total_stay_minutes: int
    total_walking_meters: int


class Itinerary(BaseModel):
    title: str
    summary: str
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    request: TripRequest
    origin: Place | None = None
    days: list[ScheduledDay]
    warnings: list[str]
    web_sources: list[WebEvidence] = Field(default_factory=list)
    revision_count: int
    generated_at: datetime
