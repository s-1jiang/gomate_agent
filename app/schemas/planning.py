from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    coordinate_system: Literal["GCJ02", "WGS84"]


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["amap"] = "amap"
    poi_id: str
    name: str
    city_code: str
    location: Coordinates
    source_ref: str
    fetched_at: AwareDatetime
    address: str = ""
    city: str = ""
    district: str = ""
    category: str = ""


class RouteLeg(BaseModel):
    origin_poi_id: str
    destination_poi_id: str
    mode: Literal["walking", "transit", "driving"]
    distance_meters: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)
    cost_fen: int | None = Field(default=None, ge=0, strict=True)
    coordinate_system: Literal["GCJ02"] = "GCJ02"
    source_ref: str
    fetched_at: AwareDatetime


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str = Field(min_length=1)
    origin: Coordinates
    start_at: AwareDatetime
    end_at: AwareDatetime
    party_size: int = Field(ge=1, le=100)
    budget_scope: Literal["per_person", "total"]
    budget_fen: int = Field(ge=0, strict=True)
    locked_poi_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self

    @property
    def total_budget_fen(self) -> int:
        return self.budget_fen * (self.party_size if self.budget_scope == "per_person" else 1)


class PlanStop(BaseModel):
    poi_id: str
    arrival_at: AwareDatetime
    departure_at: AwareDatetime
    # Total party cost, not per-person. Unknown is never coerced to zero.
    cost_fen: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_window(self):
        if self.departure_at < self.arrival_at:
            raise ValueError("departure_at must not precede arrival_at")
        return self


class PlanDraft(BaseModel):
    stops: list[PlanStop] = Field(min_length=1)
    legs: list[RouteLeg]
    return_at: AwareDatetime


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    total_known_cost_fen: int
    checked_at: datetime
