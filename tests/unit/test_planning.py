from datetime import datetime

from app.planning.validator import validate_draft
from app.schemas.planning import Coordinates, PlanDraft, PlanStop, TaskSpec


def task(**changes):
    values = dict(
        city="杭州",
        origin=Coordinates(longitude=120.1, latitude=30.2, coordinate_system="GCJ02"),
        start_at=datetime.fromisoformat("2026-11-21T22:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-11-22T02:00:00+08:00"),
        party_size=2,
        budget_scope="per_person",
        budget_fen=10000,
        locked_poi_ids=["poi-1"],
    )
    return TaskSpec(**(values | changes))


def draft(cost=18000, poi_id="poi-1"):
    return PlanDraft(
        stops=[
            PlanStop(
                poi_id=poi_id,
                arrival_at="2026-11-21T23:00:00+08:00",
                departure_at="2026-11-22T00:30:00+08:00",
                cost_fen=cost,
            )
        ],
        legs=[],
        return_at="2026-11-22T01:00:00+08:00",
    )


def test_cross_midnight_and_per_person_budget():
    result = validate_draft(task(), draft())
    assert result.valid
    assert result.total_known_cost_fen == 18000
    assert "OVER_BUDGET" in validate_draft(task(budget_scope="total"), draft()).errors


def test_unknown_cost_and_locked_stop_are_not_silently_ignored():
    result = validate_draft(task(), draft(cost=None, poi_id="different"))
    assert not result.valid
    assert {"UNKNOWN_COST", "LOCKED_STOP_MISSING"}.issubset(result.errors)
