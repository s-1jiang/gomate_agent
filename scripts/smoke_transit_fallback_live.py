"""Opt-in public Dalian route test; no model call or existing database access."""

import argparse
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.integrations.amap import AMapClient
from app.planning.routes import ItineraryRoutes
from app.planning.schedule import build_schedule
from app.schemas.itinerary import ItineraryDraft, TripRequest
from app.schemas.maps import MapPlace
from app.tools.budget import RunBudget


async def check():
    settings = Settings()
    if not settings.amap_web_service_key.get_secret_value():
        raise SystemExit("Missing configured map credential; no provider call made")
    provider = AMapClient(settings)
    budget = RunBudget.create(timeout=60, external=5)
    points = []
    for word, poi_id in (("星海广场", "B019B0AN7O"), ("星海广场沙滩", "B0MR7CXBDG")):
        rows = await provider.search_places(keyword=word, city="大连市", limit=3, budget=budget)
        # Public fixture IDs distinguish the square from its same-named nearby POI.
        exact = [row for row in rows if row.name == word and row.poi_id == poi_id]
        if len(exact) != 1:
            raise SystemExit("Public example could not be resolved uniquely")
        points.append(exact[0])
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(second=0, microsecond=0)
    request = TripRequest(
        days=[{"start_at": now, "end_at": now + timedelta(hours=3)}],
        mode="transit",
        origin_name="星海广场",
        max_walking_meters=2000,
    )

    async def query(start, end, mode, at):
        return await provider.get_route(
            origin=start,
            destination=end,
            mode=mode,
            departure_at=at,
            budget=budget,
        )

    routes = ItineraryRoutes(request, query, budget, walking_fallback_meters=2000)
    beach = MapPlace(
        **points[1].model_dump(), label="M1", task_id="public-example", agent="activity"
    )
    draft = ItineraryDraft(
        title="星海广场散步",
        summary="去沙滩走走。",
        days=[
            {
                "window_index": 0,
                "stops": [
                    {
                        "poi_id": beach.poi_id,
                        "duration_minutes": 60,
                        "reason": "沙滩散步",
                        "activities": [{"text": "沿海边散步"}],
                    }
                ],
            }
        ],
    )
    days = await build_schedule(
        draft, request, {beach.poi_id: beach}, points[0], [], routes.resolve
    )
    leg = days[0].legs[0]
    assert leg.mode == "walking" and leg.source_ref.startswith("amap:route:walking:")
    assert 0 < leg.walking_meters <= 2000 and leg.duration_minutes > 0
    assert days[0].finish_at <= request.days[0].end_at
    print(
        json.dumps(
            {
                "mode": leg.mode,
                "distance_meters": leg.distance_meters,
                "duration_minutes": leg.duration_minutes,
                "external_requests": budget.counts["external"],
            }
        )
    )
    print("PASS: observed public transit-to-walking fallback and computed schedule")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(check())


if __name__ == "__main__":
    main()
