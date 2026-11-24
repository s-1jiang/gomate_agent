import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.errors import AppError
from app.planning.routes import ItineraryRoutes, RouteConflict
from app.schemas.itinerary import RouteObservation, TripRequest
from app.schemas.planning import Place
from app.tools.budget import RunBudget

AT = datetime.fromisoformat("2026-11-25T09:00:00+08:00")


def place(poi_id):
    return Place(
        poi_id=poi_id,
        name=poi_id,
        city_code="0571",
        city="杭州",
        location={"longitude": 120.1, "latitude": 30.2, "coordinate_system": "GCJ02"},
        source_ref="amap:poi:" + poi_id,
        fetched_at=AT,
    )


def trip(mode="transit", **kwargs):
    return TripRequest(
        days=[{"start_at": AT, "end_at": AT + timedelta(hours=4)}], mode=mode, **kwargs
    )


def observed(mode, meters=1418, seconds=1134):
    return RouteObservation(
        origin_poi_id="A",
        destination_poi_id="B",
        mode=mode,
        distance_meters=meters,
        walking_meters=meters if mode == "walking" else 100,
        duration_seconds=seconds,
        source_ref=f"amap:route:{mode}:A:B",
        fetched_at=AT,
        paths=[[(120.1, 30.2), (120.11, 30.21)]],
    )


def test_missing_transit_uses_observed_short_walk_and_caches_both_results():
    async def check():
        calls, budget = [], RunBudget.create(tool=2, external=2)

        async def query(start, end, mode, at):
            await budget.reserve("tool")
            await budget.reserve("external")
            calls.append(mode)
            if mode == "transit":
                raise AppError("ROUTE_NOT_FOUND", "No transit")
            return observed(mode)

        routes = ItineraryRoutes(trip(), query, budget)
        first = await routes.resolve(place("A"), place("B"), AT)
        replay = await routes.resolve(place("A"), place("B"), AT)
        assert first == replay and first.mode == "walking"
        assert (first.duration_seconds, first.distance_meters) == (1134, 1418)
        assert first.paths and first.source_ref == "amap:route:walking:A:B"
        assert calls == ["transit", "walking"] and budget.counts["external"] == 2

    asyncio.run(check())


@pytest.mark.parametrize("limit,meters", [(0, 100), (1000, 1418), (None, 2001)])
def test_walk_fallback_never_exceeds_explicit_or_default_limit(limit, meters):
    calls = []

    async def query(start, end, mode, at):
        calls.append(mode)
        if mode == "transit":
            raise AppError("ROUTE_NOT_FOUND", "No transit")
        return observed(mode, meters)

    routes = ItineraryRoutes(trip(max_walking_meters=limit), query, RunBudget.create())
    with pytest.raises(RouteConflict) as error:
        asyncio.run(routes.resolve(place("A"), place("B"), AT))
    assert error.value.constraint["origin_poi_id"] == "A"
    assert "步行" in str(error.value)
    assert calls == (["transit"] if limit == 0 else ["transit", "walking"])


@pytest.mark.parametrize("mode", ["walking", "driving"])
def test_requested_modes_are_not_silently_changed(mode):
    calls = []

    async def query(start, end, actual, at):
        calls.append(actual)
        raise AppError("ROUTE_NOT_FOUND", "No route")

    routes = ItineraryRoutes(trip(mode), query, RunBudget.create())
    with pytest.raises(RouteConflict):
        asyncio.run(routes.resolve(place("A"), place("B"), AT))
    assert calls == [mode]


def test_successful_transit_is_preferred_without_an_extra_walking_query():
    async def query(start, end, mode, at):
        assert mode == "transit"
        return observed(mode)

    value = asyncio.run(
        ItineraryRoutes(trip(), query, RunBudget.create()).resolve(place("A"), place("B"), AT)
    )
    assert value.mode == "transit"


@pytest.mark.parametrize("code", ["ROUTE_TIMEOUT", "ROUTE_UNAVAILABLE"])
def test_transient_failure_retries_once_with_the_same_budget(code):
    async def check():
        budget = RunBudget.create(external=2)

        async def query(start, end, mode, at):
            await budget.reserve("external")
            if budget.counts["external"] == 1:
                raise AppError(code, "Temporary failure")
            return observed(mode)

        routes = ItineraryRoutes(trip(), query, budget)
        value = await routes.resolve(place("A"), place("B"), AT)
        assert value.mode == "transit" and budget.counts["external"] == 2

    asyncio.run(check())


@pytest.mark.parametrize(
    "code",
    [
        "ROUTE_AUTH_FAILED",
        "ROUTE_RATE_LIMITED",
        "INVALID_ROUTE_OUTPUT",
        "BUDGET_EXCEEDED",
        "CANCELLED",
        "RUN_TIMEOUT",
    ],
)
def test_nontransient_failures_do_not_trigger_fallback_or_replanning(code):
    calls = []

    async def query(start, end, mode, at):
        calls.append(mode)
        raise AppError(code, "Do not repeat")

    with pytest.raises(AppError) as error:
        asyncio.run(
            ItineraryRoutes(trip(), query, RunBudget.create()).resolve(place("A"), place("B"), AT)
        )
    assert error.value.code == code and calls == ["transit"]


def test_repeated_transient_failure_stops_after_two_attempts():
    calls = []

    async def query(start, end, mode, at):
        calls.append(mode)
        raise AppError("ROUTE_UNAVAILABLE", "Unavailable")

    with pytest.raises(AppError):
        asyncio.run(
            ItineraryRoutes(trip(), query, RunBudget.create()).resolve(place("A"), place("B"), AT)
        )
    assert calls == ["transit", "transit"]


def test_fallback_cannot_create_new_budget_or_bypass_cancellation_with_cached_data():
    async def check():
        budget = RunBudget.create(external=1)

        async def query(start, end, mode, at):
            await budget.reserve("external")
            raise AppError("ROUTE_NOT_FOUND", "No transit")

        routes = ItineraryRoutes(trip(), query, budget)
        with pytest.raises(AppError) as error:
            await routes.resolve(place("A"), place("B"), AT)
        assert error.value.code == "BUDGET_EXCEEDED"
        await budget.cancel()
        with pytest.raises(AppError) as error:
            await routes.resolve(place("A"), place("B"), AT)
        assert error.value.code == "CANCELLED"

    asyncio.run(check())
