import math
from datetime import timedelta

from app.schemas.itinerary import ScheduledDay, ScheduledLeg, ScheduledStop


class ScheduleConflict(ValueError):
    pass


async def build_schedule(draft, request, places, origin, sources, route):
    """Times and topology are derived from observed routes, never authored by the LLM."""
    indexes = [day.window_index for day in draft.days]
    if indexes != list(range(len(request.days))):
        raise ScheduleConflict("必须按顺序覆盖所有出行日期，不能增减用户的时间窗口")
    stops = [stop for day in draft.days for stop in day.stops]
    if len(stops) > 6:
        raise ScheduleConflict("整个行程最多六个停留时段，请减少不必要的站点")
    for day in draft.days:
        seen_visits = set()
        for stop in day.stops:
            if stop.kind == "visit" and stop.poi_id in seen_visits:
                raise ScheduleConflict("同一天不要重复安排同一景点游览；返回该地休息请标记 break")
            if stop.kind == "visit":
                seen_visits.add(stop.poi_id)
    for stop in stops:
        if stop.poi_id not in places:
            raise ScheduleConflict(
                f"未知 poi_id={stop.poi_id}；只允许：{','.join(places)}。"
                "出发点和返程由程序自动计算，不要放进游玩 stops。"
            )
        allowed = {source.label for source in sources if source.poi_id == stop.poi_id}
        for detail in stop.activities + stop.practical_info:
            if not set(detail.evidence_ids).issubset(allowed):
                raise ScheduleConflict("玩法或实用信息引用了不存在或属于其他地点的网页来源")
    result, label = [], 0
    for day in draft.days:
        window = request.days[day.window_index]
        cursor, previous = window.start_at, origin
        visits, legs = [], []

        async def travel(destination, day_legs=legs):
            nonlocal cursor, previous, label
            if previous is not None and previous.poi_id != destination.poi_id:
                observation = await route(previous, destination, cursor)
                minutes = math.ceil(observation.duration_seconds / 60)
                label += 1
                end = cursor + timedelta(minutes=minutes + request.buffer_minutes)
                day_legs.append(
                    ScheduledLeg(
                        **observation.model_dump(),
                        label=f"T{label}",
                        origin_name=previous.name,
                        destination_name=destination.name,
                        start_at=cursor,
                        end_at=end,
                        duration_minutes=minutes,
                        buffer_minutes=request.buffer_minutes,
                    )
                )
                cursor = end
            previous = destination

        for stop in day.stops:
            place = places[stop.poi_id]
            await travel(place)
            departure = cursor + timedelta(minutes=stop.duration_minutes)
            visits.append(
                ScheduledStop(
                    **stop.model_dump(),
                    label=place.label,
                    name=place.name,
                    arrival_at=cursor,
                    departure_at=departure,
                )
            )
            cursor = departure
        if request.return_to_origin:
            await travel(origin)
        if cursor > window.end_at:
            over = math.ceil((cursor - window.end_at).total_seconds() / 60)
            raise ScheduleConflict(
                f"第{day.window_index + 1}天超出截止时间{over}分钟；"
                "缩短停留、减少站点或选择更近的地点"
            )
        result.append(
            ScheduledDay(
                start_at=window.start_at,
                deadline=window.end_at,
                finish_at=cursor,
                spare_minutes=int((window.end_at - cursor).total_seconds() // 60),
                stops=visits,
                legs=legs,
                total_travel_minutes=sum(leg.duration_minutes for leg in legs),
                total_stay_minutes=sum(stop.duration_minutes for stop in visits),
                total_walking_meters=sum(leg.walking_meters for leg in legs),
            )
        )
    if (
        request.max_walking_meters is not None
        and sum(day.total_walking_meters for day in result) > request.max_walking_meters
    ):
        raise ScheduleConflict(
            "站间路线总步行距离超过用户上限；请减少移动或更换地点，园内步行尚未计入"
        )
    return result
