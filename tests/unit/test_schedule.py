import asyncio
from datetime import datetime

import httpx
import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.integrations.amap import AMapClient
from app.planning.schedule import ScheduleConflict, build_schedule
from app.schemas.itinerary import ItineraryDraft, RouteObservation, TripRequest
from app.schemas.maps import MapPlace
from app.tools.budget import RunBudget


def place(poi_id):
    return MapPlace(
        poi_id=poi_id,
        name=poi_id,
        city_code="0571",
        city="杭州",
        location={"longitude": 120.1, "latitude": 30.2, "coordinate_system": "GCJ02"},
        source_ref="amap:poi:" + poi_id,
        fetched_at="2026-11-25T08:00:00+08:00",
        label="M1",
        task_id="task-1",
        agent="activity",
    )


@pytest.mark.parametrize("mode", ["walking", "driving"])
def test_route_adapter_uses_observed_cost_and_separate_geometry(settings, mode):
    async def handler(request):
        assert request.url.path == "/v5/direction/" + mode
        assert request.url.params["show_fields"] == "cost,polyline"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {
                    "paths": [
                        {
                            "distance": "1234",
                            "cost": {"duration": "601"},
                            "steps": [
                                {"instruction": "沿路步行", "polyline": "120.1,30.2;120.11,30.21"},
                                {"polyline": "120.3,30.3;120.31,30.31"},
                            ],
                        }
                    ]
                },
            },
        )

    settings.amap_web_service_key = "fake"
    budget = RunBudget.create()
    route = asyncio.run(
        AMapClient(settings, transport=httpx.MockTransport(handler)).get_route(
            origin=place("O"),
            destination=place("A"),
            mode=mode,
            departure_at=datetime.fromisoformat("2026-11-25T09:00:00+08:00"),
            budget=budget,
        )
    )
    assert route.duration_seconds == 601 and route.distance_meters == 1234
    assert route.walking_meters == (1234 if mode == "walking" else 0)
    assert len(route.paths) == 2  # Missing geometry never creates a straight connecting road.
    assert budget.counts["external"] == 1


def test_missing_route_duration_is_failure_not_zero_time(settings):
    settings.amap_web_service_key = "fake"

    async def handler(request):
        return httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "100"}]}})

    with pytest.raises(AppError, match="缺少有效的耗时"):
        asyncio.run(
            AMapClient(settings, transport=httpx.MockTransport(handler)).get_route(
                origin=place("O"),
                destination=place("A"),
                mode="walking",
                departure_at=datetime.fromisoformat("2026-11-25T09:00:00+08:00"),
                budget=RunBudget.create(),
            )
        )


def test_schedule_crosses_midnight_rounds_up_and_keeps_return_time():
    request = TripRequest(
        days=[{"start_at": "2026-11-25T23:00:00+08:00", "end_at": "2026-11-26T02:00:00+08:00"}],
        origin_name="O",
        return_to_origin=True,
        mode="walking",
        buffer_minutes=10,
    )
    draft = ItineraryDraft(
        title="夜游",
        summary="示例",
        days=[
            {
                "window_index": 0,
                "stops": [
                    {
                        "poi_id": "A",
                        "duration_minutes": 60,
                        "reason": "慢游",
                        "activities": [{"text": "散步"}],
                    }
                ],
            }
        ],
    )

    async def route(start, end, at):
        return RouteObservation(
            origin_poi_id=start.poi_id,
            destination_poi_id=end.poi_id,
            mode="walking",
            distance_meters=100,
            walking_meters=100,
            duration_seconds=601,
            source_ref="amap:route",
            fetched_at=at,
        )

    days = asyncio.run(build_schedule(draft, request, {"A": place("A")}, place("O"), [], route))
    assert days[0].legs[0].duration_minutes == 11
    assert days[0].finish_at.isoformat() == "2026-11-26T00:42:00+08:00"
    request.max_walking_meters = 100
    with pytest.raises(ScheduleConflict, match="步行距离超过"):
        asyncio.run(build_schedule(draft, request, {"A": place("A")}, place("O"), [], route))


def test_time_windows_require_timezone_and_cannot_overlap():
    for days in (
        [{"start_at": "2026-11-25T09:00:00", "end_at": "2026-11-25T12:00:00"}],
        [{"start_at": "2026-11-25T09:00:00+00:00", "end_at": "2026-11-25T12:00:00+00:00"}],
        [{"start_at": "2026-11-25T12:00:00+08:00", "end_at": "2026-11-25T09:00:00+08:00"}],
        [{"start_at": "2026-11-25T09:00:00+08:00", "end_at": "2026-11-25T12:00:00+08:00"}] * 2,
    ):
        with pytest.raises(ValidationError):
            TripRequest(days=days)


def test_returning_to_same_park_for_a_break_is_valid_and_days_restart_at_origin():
    request = TripRequest(
        days=[
            {"start_at": "2026-11-25T09:00:00+08:00", "end_at": "2026-11-25T13:00:00+08:00"},
            {"start_at": "2026-11-26T09:00:00+08:00", "end_at": "2026-11-26T13:00:00+08:00"},
        ],
        origin_name="O",
        return_to_origin=True,
        mode="walking",
        buffer_minutes=0,
    )

    def stop(key, kind="visit"):
        return {
            "poi_id": key,
            "kind": kind,
            "duration_minutes": 30,
            "reason": "慢游",
            "activities": [{"text": "散步或休息"}],
        }

    draft = ItineraryDraft(
        title="两天",
        summary="示例",
        days=[
            {"window_index": 0, "stops": [stop("A"), stop("B", "meal"), stop("A", "break")]},
            {"window_index": 1, "stops": [stop("A")]},
        ],
    )
    observed = []

    async def route(start, end, at):
        observed.append((start.poi_id, end.poi_id, at))
        return RouteObservation(
            origin_poi_id=start.poi_id,
            destination_poi_id=end.poi_id,
            mode="walking",
            distance_meters=100,
            walking_meters=100,
            duration_seconds=600,
            source_ref="amap:route",
            fetched_at=at,
        )

    days = asyncio.run(
        build_schedule(draft, request, {"A": place("A"), "B": place("B")}, place("O"), [], route)
    )
    assert len(days) == 2 and days[0].stops[-1].kind == "break"
    assert observed[4][0] == "O" and observed[4][2] == request.days[1].start_at
