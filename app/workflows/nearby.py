import json
import logging
import re
from datetime import UTC, datetime

from app.agents.map_specialist import MapSpecialist, MapTask, structured_complete
from app.core.errors import AppError
from app.integrations.contracts import ChatMessage
from app.planning.places import match_origin, normalized_name, recommendation_areas
from app.schemas.maps import (
    AreaSelection,
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
    if state.get("nearby_mode") == "alternatives":
        return None  # Let Supervisor interpret selections among individual shop alternatives.
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
        recommendation_request=None,
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

        recommendation_request = recommendation_request or {
            "mode": decision.nearby_mode,
            "requested_count": decision.recommendation_count,
            "more_options": decision.more_options,
        }
        if (
            decision.nearby_mode == "alternatives"
            and not decision.anchor_name
            and areas_override is None
        ):
            return await self.search(
                decision=decision.model_copy(update={"kind": "search"}),
                prompt=prompt,
                auth=auth,
                run=run,
                budget=budget,
                emit=emit,
                recommendation_request=recommendation_request,
                review_goal="比较多家同类地点。根据用户数量要求给出所有值得推荐的候选，不生成固定两处的串行行程。",
            )

        gateway = MapToolGateway(
            self.provider, max_parallel=self.settings.max_parallel_tools_per_run
        )
        primary, discovery_answer, discovery_rounds = None, "", 0
        primary_by_id = {}
        if primary_destination is not None:
            primary = MapPlace(
                **primary_destination.model_dump(),
                label="anchor",
                task_id="anchor",
                agent=decision.tasks[0].agent,
            )
            if decision.nearby_mode == "combine":
                primary_by_id[primary.poi_id] = primary
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
                review_goal="先选择符合用户目标的主要目的地。需要比较多个组合时可选多处，数量由你判断；后续分别围绕它们安排活动。",
                recommendation_request={
                    **recommendation_request,
                    "selection_scope": "primary_destination",
                },
            )
            if discovery.status != "approved" or not discovery.places:
                return discovery_answer, discovery
            if len(decision.tasks) == 1:
                discovery.recommendation_context = NearbyContext(
                    anchor_name="", tasks=decision.tasks, nearby_mode="alternatives"
                )
                return discovery_answer, discovery
            primary_by_id = {place.poi_id: place for place in discovery.places}
            discovery_answer = without_listing(discovery_answer, discovery.places)
            discovery_rounds = discovery.review_rounds
            areas = [base_place(place) for place in discovery.places]
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
        if not primary_by_id and len(areas) > 1:
            selection = await structured_complete(
                self.model,
                [
                    ChatMessage(
                        role="system",
                        content="你是 Supervisor，选择推荐区域。依据用户目标和实际候选选择区域。"
                        "数量由你判断。"
                        "一般可考虑1—3个便于比较，这是建议而非上限；用户明确要求和候选差异优先。"
                        "多推荐店铺不等于增加区域；已指定校区时保留区域。只选提供的主体地点，不编造来源。"
                        '只输出 JSON：{"area_ids":["原样复制实际候选的poi_id"]}，不输出思考过程。',
                    ),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "areas": [area.model_dump(mode="json") for area in areas],
                                "area_count_hint": decision.area_limit,
                                "recommendation_request": recommendation_request,
                                "user_context": [message.model_dump() for message in prompt[1:]],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                budget,
                AreaSelection,
            )
            observed_areas = {area.poi_id: area for area in areas}
            if not set(selection.area_ids).issubset(observed_areas):
                raise AppError("INVALID_REVIEW", "区域审查引用了未查询的地点", 502)
            areas = [observed_areas[poi_id] for poi_id in dict.fromkeys(selection.area_ids)]
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
                anchor_name=decision.anchor_name,
                tasks=decision.tasks,
                destination=base_place(next(iter(primary_by_id.values())))
                if len(primary_by_id) == 1
                else None,
                destinations=[base_place(place) for place in primary_by_id.values()],
                nearby_mode=decision.nearby_mode,
            ),
        )
        labels = {}
        # All model-selected options share the original budget, deadline and review process.
        for area in areas:
            primary = primary_by_id.get(area.poi_id)
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
                        recommendation_request={
                            **recommendation_request,
                            "selection_scope": "nearby_activities" if primary else "area_options",
                        },
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
            chosen = list(observed.values())  # Keep every approved ID and its model-selected order.
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
            if decision.nearby_mode == "combine" and len(chosen) == 2:
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
