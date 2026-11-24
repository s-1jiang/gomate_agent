import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.core.errors import AppError
from app.planning.schedule import ScheduleConflict
from app.schemas.itinerary import RouteObservation, TripRequest
from app.schemas.planning import Place
from app.tools.budget import RunBudget

logger = logging.getLogger(__name__)
MODES = {"transit": "公共交通", "walking": "步行", "driving": "驾车"}


class RouteConflict(ScheduleConflict):
    def __init__(self, start, end, mode, departure, reason):
        self.constraint = {
            "origin_poi_id": start.poi_id,
            "destination_poi_id": end.poi_id,
            "mode": mode,
            "departure_at": departure.isoformat(),
            "reason": reason,
        }
        self.user_message = (
            f"{start.name} → {end.name} 暂时没有合适的{MODES[mode]}路线。请调整地点或出行方式。"
        )
        super().__init__(
            f"{start.name}({start.poi_id}) → {end.name}({end.poi_id})：{reason}。"
            "调整顺序或替换非必去地点，不要放宽时间、步行限制、出发点、返程及必去地点要求。"
        )


class ItineraryRoutes:
    """Resolve observed routes within one Run; missing routes are planner feedback."""

    def __init__(
        self,
        request: TripRequest,
        query: Callable[[Place, Place, str, datetime], Awaitable[RouteObservation]],
        budget: RunBudget,
        *,
        walking_fallback_meters: int = 2000,
    ):
        self.request, self.query, self.budget = request, query, budget
        self.walking_limit = walking_fallback_meters
        if request.max_walking_meters is not None:
            self.walking_limit = min(self.walking_limit, request.max_walking_meters)
        self.cache: dict[tuple, RouteObservation | None] = {}

    async def observed(self, start, end, mode, departure):
        self.budget.remaining()
        stamp = departure.isoformat(timespec="minutes") if mode == "transit" else ""
        key = (start.poi_id, end.poi_id, mode, stamp)
        if key in self.cache:
            return self.cache[key]
        # Only repeat transient failures. Auth, quota, malformed data and absence differ.
        for attempt in range(2):
            self.budget.remaining()
            try:
                value = await self.query(start, end, mode, departure)
                self.cache[key] = value
                return value
            except AppError as exc:
                logger.warning("Itinerary route query failed: %s (%s)", exc.code, mode)
                if exc.code == "ROUTE_NOT_FOUND":
                    self.cache[key] = None
                    return None
                if attempt or exc.code not in {"ROUTE_UNAVAILABLE", "ROUTE_TIMEOUT"}:
                    raise
        raise AssertionError("Unreachable route retry state")

    async def resolve(self, start, end, departure):
        mode = self.request.mode
        value = await self.observed(start, end, mode, departure)
        if value is not None:
            return value
        reason = f"该时段未查到{MODES[mode]}路线"
        if mode == "transit" and self.walking_limit > 0:
            walking = await self.observed(start, end, "walking", departure)
            if walking is not None:
                if max(walking.distance_meters, walking.walking_meters) <= self.walking_limit:
                    return walking
                reason += (
                    f"，步行距离{walking.distance_meters}米超过允许的短途步行"
                    f"上限{self.walking_limit}米"
                )
            else:
                reason += "，也未查到步行路线"
        elif mode == "transit":
            reason += "，当前要求不允许额外步行"
        raise RouteConflict(start, end, mode, departure, reason)
