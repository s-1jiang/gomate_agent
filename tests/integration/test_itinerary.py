import json
from dataclasses import dataclass, field

import httpx
import pytest

from app.integrations.amap import AMapClient
from app.integrations.deepseek import DeepSeekClient
from app.integrations.tavily import TavilyClient


@dataclass
class Scenario:
    web: bool = False
    long_first: bool = False
    revise_first: bool = False
    always_conflict: bool = False
    forged_source: bool = False
    forged_place: bool = False
    stale_review: bool = False
    no_origin: bool = False
    ambiguous_origin: bool = False
    route_failure: bool = False
    web_failure: bool = False
    calls: list = field(default_factory=list)
    drafts: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    routes: list = field(default_factory=list)
    queries: list = field(default_factory=list)


def poi(poi_id, name, lon=120.15):
    return {
        "id": poi_id,
        "name": name,
        "location": f"{lon},30.25",
        "citycode": "0571",
        "cityname": "杭州市",
        "address": "测试地址",
        "type": "风景名胜",
    }


@pytest.fixture
def itinerary_scenario(client, settings):
    scenario = Scenario()
    settings.deepseek_api_key = "fake-deepseek"
    settings.amap_web_service_key = "fake-amap"

    async def model(request):
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        data = body["messages"][-1]["content"]
        scenario.calls.append(body)
        if "可使用三种格式" in system:
            answer = {
                "kind": "plan",
                "city": "杭州市",
                "tasks": [{"agent": "activity", "keyword": "公园", "instruction": "安排轻松游玩"}],
                "trip": {
                    "days": [
                        {
                            "start_at": "2026-11-25T09:00:00+08:00",
                            "end_at": "2026-11-25T13:00:00+08:00",
                        }
                    ],
                    "origin_name": "" if scenario.no_origin else "杭州东站",
                    "return_to_origin": not scenario.no_origin,
                    "mode": "transit",
                    "party_size": 2,
                },
            }
        elif "只负责自己的任务" in system:
            answer = {"keyword": "公园", "city": "杭州市", "limit": 5}
        elif "你是行程策划 Agent" in system:
            payload = json.loads(data)
            scenario.drafts.append(payload)
            first = len(scenario.drafts) == 1
            long = scenario.always_conflict or (first and scenario.long_first)
            sources = payload["web_sources"]
            stops = []
            for index, name in enumerate(("A", "B")):
                ids = [source["label"] for source in sources if source["poi_id"] == name]
                if scenario.forged_source:
                    ids = ["W999"]
                stops.append(
                    {
                        "poi_id": "FAKE" if scenario.forged_place else name,
                        "duration_minutes": 240 if long else (75 if index == 0 else 60),
                        "reason": "安排轻松散步与休息",
                        "activities": [{"text": "沿步道慢走拍照", "evidence_ids": ids}],
                        "practical_info": [{"text": "出发前确认预约", "evidence_ids": []}],
                    }
                )
            answer = {
                "title": "杭州半日游",
                "summary": "两站慢游，含返程；费用未核验。",
                "days": [{"window_index": 0, "stops": stops}],
            }
        elif "审查完整游玩行程" in system:
            payload = json.loads(data)
            scenario.reviews.append(payload)
            revise = scenario.revise_first and len(scenario.reviews) == 1
            answer = {
                "task_version": 99 if scenario.stale_review else payload["task_version"],
                "decision": "revise" if revise else "approve",
                "feedback": "请保留第一站并增加休息安排" if revise else "",
                "answer": "行程已审查",
            }
        else:
            payload = json.loads(data)
            answer = {
                "decision": "approve",
                "answer": "候选地点已核对",
                "selected_ids": [row["evidence_id"] for row in payload["candidates"]],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    async def maps(request):
        if request.url.path == "/v5/place/text":
            if request.url.params["keywords"] == "杭州东站":
                rows = [poi("O", "杭州东站", 120.1)]
                if scenario.ambiguous_origin:
                    rows = [poi("O", "东站北广场"), poi("O2", "东站南广场")]
            else:
                rows = [poi("A", "湖畔公园"), poi("B", "文化公园", 120.2)]
            return httpx.Response(200, json={"status": "1", "pois": rows})
        assert request.url.path == "/v5/direction/transit/integrated"
        assert request.url.params["city1"] == request.url.params["city2"] == "0571"
        assert request.url.params["date"] == "2026-11-25"
        assert request.url.params["show_fields"] == "cost,polyline"
        scenario.routes.append(dict(request.url.params))
        if scenario.route_failure:
            return httpx.Response(200, json={"status": "1", "route": {"transits": []}})
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {
                    "transits": [
                        {
                            "distance": "2000",
                            "cost": {"duration": "1200"},
                            "segments": [
                                {
                                    "walking": {"distance": "100", "steps": []},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "地铁1号线",
                                                "polyline": "120.1,30.25;120.2,30.25",
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                },
            },
        )

    async def web(request):
        body = json.loads(request.content)
        assert request.url == "https://api.tavily.com/search"
        assert request.headers["authorization"] == "Bearer fake-tavily"
        assert body["include_answer"] is False and body["search_depth"] == "basic"
        assert "PRIVATE_CANARY" not in body["query"]
        scenario.queries.append(body["query"])
        if scenario.web_failure:
            return httpx.Response(401)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "公园介绍",
                        "url": "https://parks.example.org/" + str(len(scenario.queries)),
                        "content": "园内有步道，适合慢走。",
                    },
                    {"title": "bad", "url": "javascript:alert(1)", "content": "bad"},
                    {"title": "private", "url": "https://127.0.0.1/admin", "content": "bad"},
                ]
            },
        )

    service = client.app.state.chat
    service.model = DeepSeekClient(settings, transport=httpx.MockTransport(model))
    service.map_provider = AMapClient(settings, transport=httpx.MockTransport(maps))
    service.web_provider = TavilyClient(settings, transport=httpx.MockTransport(web))
    return scenario


def execute(client, headers):
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    body = {
        "content": "明天杭州东站9点出发，13点前返回，安排轻松的游玩。PRIVATE_CANARY",
        "client_message_id": "trip",
    }
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 202
    run = client.get("/api/v1/runs/" + response.json()["id"], headers=headers).json()
    return run, client.get(path, headers=headers).json(), path, body


def test_full_itinerary_uses_route_time_and_persists_replay_without_extra_calls(
    client, login, itinerary_scenario
):
    scenario = itinerary_scenario
    headers = login()
    run, messages, path, body = execute(client, headers)
    assert run["status"] == "succeeded", run
    result = messages[-1]["map_result"]
    plan = result["itinerary"]
    day = plan["days"][0]
    assert day["stops"][0]["arrival_at"] == "2026-11-25T09:30:00+08:00"
    assert day["stops"][0]["departure_at"] == "2026-11-25T10:45:00+08:00"
    assert day["finish_at"] == "2026-11-25T12:45:00+08:00"
    assert day["spare_minutes"] == 15 and len(day["legs"]) == 3
    assert day["legs"][-1]["destination_poi_id"] == "O"
    assert day["legs"][0]["paths"] == [[[120.1, 30.25], [120.2, 30.25]]]
    assert plan["origin"]["poi_id"] == "O"
    assert any("未启用联网检索" in warning for warning in plan["warnings"])
    assert result["events"] == run["workflow_events"]
    assert (run["llm_calls"], run["external_requests"], run["tool_calls"]) == (5, 10, 6)
    assert client.post(path, headers=headers, json=body).json()["id"] == run["id"]
    assert len(scenario.calls) == 5 and len(scenario.routes) == 3
    assert client.get(path, headers=login("other")).status_code == 404


def test_time_conflict_returns_to_planner_without_repeating_research(
    client, login, itinerary_scenario
):
    scenario = itinerary_scenario
    scenario.long_first = True
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    assert len(scenario.drafts) == 2
    assert "超出截止时间" in scenario.drafts[-1]["feedback"]
    assert scenario.drafts[-1]["previous_draft"]["days"][0]["stops"][0]["duration_minutes"] == 240
    assert messages[-1]["map_result"]["itinerary"]["revision_count"] == 1
    assert len(scenario.reviews) == 1


def test_supervisor_can_send_only_itinerary_back_for_semantic_revision(
    client, login, itinerary_scenario
):
    scenario = itinerary_scenario
    scenario.revise_first = True
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    assert scenario.drafts[-1]["feedback"] == "请保留第一站并增加休息安排"
    assert messages[-1]["map_result"]["itinerary"]["revision_count"] == 1
    assert len(scenario.routes) == 3  # same departure times reuse only this run's observations


@pytest.mark.parametrize("invalid", ["always_conflict", "forged_source", "forged_place"])
def test_conflicting_or_unobserved_plan_never_published(client, login, itinerary_scenario, invalid):
    setattr(itinerary_scenario, invalid, True)
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    result = messages[-1]["map_result"]
    assert result["status"] == "revision_limit"
    assert result["itinerary"] is None and not result["places"]
    assert len(itinerary_scenario.drafts) == 3


def test_web_sources_bound_to_place_and_private_context_not_sent(
    client, login, settings, itinerary_scenario
):
    settings.tavily_api_key = "fake-tavily"
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    plan = messages[-1]["map_result"]["itinerary"]
    assert [row["label"] for row in plan["web_sources"]] == ["W1", "W2"]
    assert plan["days"][0]["stops"][0]["activities"][0]["evidence_ids"] == ["W1"]
    assert all(row["url"].startswith("https://parks.example.org/") for row in plan["web_sources"])
    assert len(itinerary_scenario.queries) == 2 and run["tool_calls"] == 8
    assert "fake-tavily" not in json.dumps(messages)


def test_web_failure_degrades_to_explicit_suggestions(client, login, settings, itinerary_scenario):
    settings.tavily_api_key = "fake-tavily"
    itinerary_scenario.web_failure = True
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    plan = messages[-1]["map_result"]["itinerary"]
    assert not plan["web_sources"]
    assert any("鉴权失败" in warning for warning in plan["warnings"])


@pytest.mark.parametrize("case", ["ambiguous_origin", "route_failure"])
def test_unknown_origin_or_route_clarifies_without_fabricated_times(
    client, login, itinerary_scenario, case
):
    setattr(itinerary_scenario, case, True)
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    result = messages[-1]["map_result"]
    assert result["status"] == "needs_clarification" and result["itinerary"] is None


def test_no_origin_does_not_invent_outbound_or_return_travel(client, login, itinerary_scenario):
    itinerary_scenario.no_origin = True
    run, messages, _, _ = execute(client, login())
    assert run["status"] == "succeeded", run
    plan = messages[-1]["map_result"]["itinerary"]
    assert plan["origin"] is None and len(plan["days"][0]["legs"]) == 1
    assert any("未提供出发点" in warning for warning in plan["warnings"])


def test_stale_plan_review_fails_without_answer(client, login, itinerary_scenario):
    itinerary_scenario.stale_review = True
    run, messages, _, _ = execute(client, login())
    assert run["error_code"] == "STALE_REVIEW" and len(messages) == 1


def test_itinerary_keeps_original_run_budget(client, login, settings, itinerary_scenario):
    settings.max_llm_calls_per_run = 3
    run, messages, _, _ = execute(client, login())
    assert run["error_code"] == "BUDGET_EXCEEDED"
    assert run["llm_calls"] == 3 and len(messages) == 1
