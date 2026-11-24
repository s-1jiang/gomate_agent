import logging
import re
from datetime import UTC, datetime

from app.agents.map_specialist import MapSpecialist, MapTask
from app.core.errors import AppError
from app.planning.places import match_origin, normalized_name, recommendation_areas
from app.schemas.maps import (
    Assignment,
    MapPlace,
    MapSearchResult,
    NearbyContext,
    RecommendationGroup,
    SupervisorDecision,
    WorkflowEvent,
)
from app.schemas.planning import Place
from app.tools.context import ToolContext
from app.tools.map_gateway import MapToolGateway

logger = logging.getLogger(__name__)


def resume_recommendation(text, previous):
    state = previous.get("recommendation_context")
    groups = previous.get("recommendation_groups") or []
    if not state or not groups or len(text) > 80:
        return None
    choice = re.sub(r"^(?:我在|就在|就选|选择|那就|在|选|去)", "", text.strip())
    choice = re.sub(r"(?:附近|这边|就行|即可|吧|呢|。|！|!|？|\?)$", "", choice)
    if not choice:
        return None
    areas = [Place.model_validate(group["area"]) for group in groups]
    ordinal = {"第一个": 0, "第1个": 0, "1": 0, "第二个": 1, "第2个": 1, "2": 1}.get(choice)
    if ordinal is not None:
        area = areas[ordinal] if ordinal < len(areas) else None
    elif normalized_name(choice).endswith("校区"):
        area = match_origin(choice, areas, previous["city"])
    elif any(
        normalized_name(area.name).endswith(normalized_name(choice) + "校区") for area in areas
    ):
        area = match_origin(choice + "校区", areas, previous["city"])
    elif any(normalized_name(area.name) == normalized_name(choice) for area in areas):
        area = match_origin(choice, areas, previous["city"])
    else:
        return None
    if area is None:
        return None
    state = NearbyContext.model_validate(state)
    return SupervisorDecision(
        kind="nearby", city=previous["city"], anchor_name=area.name, tasks=state.tasks
    ), area


def compact_pair(places, first_agent="dining"):
    dining = [place for place in places if place.agent == "dining"]
    activity = [place for place in places if place.agent == "activity"]
    if dining and activity:
        # Preserve Supervisor's ranked choices instead of replacing its preference.
        pair = [dining[0], activity[0]]
        return pair if first_agent == "dining" else list(reversed(pair))
    return places[:2]


def without_listing(answer, places):
    listing = "\n\n" + "\n".join(
        f"[{place.label}] {place.name} — {place.address or '地址暂缺'}" for place in places
    )
    return answer[: -len(listing)] if answer.endswith(listing) else answer


def base_place(place):
    return Place(**place.model_dump(include=set(Place.model_fields)))


class NearbyWorkflow:
    def __init__(self, settings, model, provider, search):
        self.settings, self.model, self.provider, self.search = settings, model, provider, search

    async def execute(
        self,
        *,
        decision,
        prompt,
        auth,
        run,
        budget,
        emit,
        areas_override=None,
        primary_destination=None,
    ):
        city = decision.city or self.settings.default_city
        if not city:
            return "想在哪个城市找？", MapSearchResult(
                status="needs_clarification",
                city="",
                review_rounds=0,
                searched_at=datetime.now(UTC),
            )

        def context(agent, scope):
            return ToolContext(
                auth=auth,
                session_id=run["session_id"],
                run_id=run["id"],
                request_id=run["id"],
                agent_name=agent,
                scopes=frozenset({scope}),
            )

        async def event(stage, agent, summary):
            await emit(WorkflowEvent(stage=stage, agent=agent, summary=summary))

        gateway = MapToolGateway(
            self.provider, max_parallel=self.settings.max_parallel_tools_per_run
        )
        primary, discovery_answer, discovery_rounds = None, "", 0
        if primary_destination is not None:
            primary = MapPlace(
                **primary_destination.model_dump(),
                label="anchor",
                task_id="anchor",
                agent=decision.tasks[0].agent,
            )
        if not decision.anchor_name and areas_override is None:
            await event("dispatch", "supervisor", "先分派专家查找主要目的地，再安排其周边活动")
            first_task = decision.tasks[0]
            discovery_answer, discovery = await self.search(
                decision=SupervisorDecision(kind="search", city=city, tasks=[first_task]),
                prompt=prompt,
                auth=auth,
                run=run,
                budget=budget,
                emit=emit,
                review_goal="先选择一处符合用户偏好的主要目的地。这里只审查第一步，后续活动将围绕它继续搜索。",
            )
            if discovery.status != "approved" or not discovery.places:
                return discovery_answer, discovery
            primary = discovery.places[0]
            discovery_answer = without_listing(discovery_answer, discovery.places)
            if len(discovery.places) > 1:
                discovery_answer = "可以先参考这家。"
            discovery_rounds = discovery.review_rounds
            areas = [base_place(primary)]
        elif areas_override is None:
            await event(
                "dispatch", "supervisor", f"分派给 places Agent：确认 {decision.anchor_name} 的区域"
            )
            lookup = MapTask(
                "area-lookup",
                1,
                Assignment(
                    agent="places",
                    keyword=decision.anchor_name,
                    instruction="查找用户所说的机构或校区主体，保留不同主校区，不找校门、楼宇和技术中心",
                ),
                city,
                fixed_keyword=True,
            )
            outcome = await MapSpecialist(self.model, gateway).execute(
                lookup, context("places", "map:search"), budget
            )
            candidates = [Place.model_validate(place) for place in outcome["places"]]
            areas = recommendation_areas(decision.anchor_name, candidates, city)
        else:
            areas = areas_override
        areas = areas[: decision.area_limit or 2]
        await event("review", "supervisor", f"核对区域候选，保留 {len(areas)} 个区域分别推荐")
        if not areas:
            return "暂时没找到这个区域，可以补充附近的地标。", MapSearchResult(
                status="no_results", city=city, review_rounds=0, searched_at=datetime.now(UTC)
            )

        combined = MapSearchResult(
            status="no_results",
            city=city,
            review_rounds=discovery_rounds,
            searched_at=datetime.now(UTC),
            recommendation_context=NearbyContext(
                anchor_name=primary.name if primary else decision.anchor_name,
                tasks=decision.tasks,
                destination=base_place(primary) if primary else None,
            ),
        )
        labels = {}
        # Two areas share one budget/deadline and normal Supervisor review/rework.
        for area in areas:
            tasks = [
                task.model_copy(
                    update={
                        "instruction": task.instruction
                        + f"。以已确认的{area.name}为中心做周边搜索，关键词只写类别。"
                        "优先方便衔接的地点。"
                    }
                )
                for task in (decision.tasks[1:] if primary else decision.tasks)
            ]
            if tasks:
                child = SupervisorDecision(kind="search", city=city, tasks=tasks)
                try:
                    answer, result = await self.search(
                        decision=child,
                        prompt=prompt,
                        auth=auth,
                        run=run,
                        budget=budget,
                        emit=emit,
                        search_center=area,
                        review_goal="以已确认的主要目的地为中心，只审查后续地点并给出衔接建议。"
                        if primary
                        else "",
                    )
                except AppError as exc:
                    if not primary or not exc.code.startswith(("MAP_", "INVALID_MAP_")):
                        raise
                    logger.warning("Secondary destination search unavailable: %s", exc.code)
                    answer, result = (
                        "",
                        MapSearchResult(
                            status="no_results",
                            city=city,
                            review_rounds=0,
                            searched_at=datetime.now(UTC),
                        ),
                    )
            else:
                answer, result = (
                    discovery_answer,
                    MapSearchResult(
                        status="approved",
                        city=city,
                        places=[],
                        review_rounds=0,
                        searched_at=datetime.now(UTC),
                    ),
                )
            combined.review_rounds += result.review_rounds
            if result.status != "approved" and not primary:
                combined.recommendation_groups.append(
                    RecommendationGroup(
                        area=area,
                        answer="这一带暂未查到合适的组合，可以先参考另一片区域。",
                        place_ids=[],
                    )
                )
                continue
            remap = {}
            answer = without_listing(answer, result.places)
            if primary and result.status != "approved":
                answer = "可以先参考这家；附近的后续地点暂未查到合适的推荐。"
            observed = {
                place.poi_id: place for place in ([primary] if primary else []) + result.places
            }
            if primary:
                observed[primary.poi_id] = primary
            chosen = compact_pair(list(observed.values()), decision.tasks[0].agent)
            if len(chosen) < len(observed):
                answer = "这组地点在同一片区域，可以按顺序前往。"
            for place in chosen:
                if place.poi_id not in labels:
                    labels[place.poi_id] = f"M{len(labels) + 1}"
                    combined.places.append(place.model_copy(update={"label": labels[place.poi_id]}))
            for place in result.places:
                if place.poi_id in {item.poi_id for item in chosen}:
                    remap[place.label] = labels[place.poi_id]
            if not tasks and primary:
                remap[primary.label] = labels[primary.poi_id]
            answer = re.sub(
                r"\[M\d+\]",
                lambda match, remap=remap: (
                    f"[{remap[match[0][1:-1]]}]"
                    if match[0][1:-1] in remap
                    else "〔地图来源未核实〕"
                ),
                answer,
            )
            group = RecommendationGroup(
                area=area, answer=answer, place_ids=[place.poi_id for place in chosen]
            )
            if len(chosen) == 2:
                first, second = chosen
                await event(
                    "dispatch", "supervisor", "分派给 itinerary Agent：查询餐饮与娱乐地点的步行衔接"
                )
                try:
                    group.route = await gateway.route(
                        context("itinerary", "map:route"),
                        origin=first,
                        destination=second,
                        mode="walking",
                        departure_at=datetime.now(UTC),
                        budget=budget,
                    )
                except AppError as exc:
                    if not exc.code.startswith(("ROUTE_", "INVALID_ROUTE_")):
                        raise
                    logger.warning("Optional nearby connection unavailable: %s", exc.code)
                await event("review", "supervisor", "核对地点组合与实际返回的步行衔接")
            combined.recommendation_groups.append(group)
        if combined.places:
            combined.status = "approved"
        text = []
        for group in combined.recommendation_groups:
            text.extend([group.area.name, group.answer])
            text.append(
                "\n".join(
                    f"[{p.label}] {p.name} — {p.address or '地址暂缺'}"
                    for p in combined.places
                    if p.poi_id in group.place_ids
                )
            )
            if group.route:
                text.append(
                    f"两处间步行约 {max(1, (group.route.duration_seconds + 59) // 60)} 分钟，"
                    f"约 {group.route.distance_meters} 米。"
                )
        await event("complete", "supervisor", "已按区域给出经过审查的周边建议")
        return "\n\n".join(text), combined
