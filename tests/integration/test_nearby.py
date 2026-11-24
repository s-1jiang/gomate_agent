import json
from dataclasses import dataclass, field

import httpx
import pytest

from app.integrations.amap import AMapClient
from app.integrations.deepseek import DeepSeekClient


@dataclass
class Scenario:
    calls: list = field(default_factory=list)
    searches: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    revise_first: bool = False
    route_missing: bool = False


def poi(key, name, longitude, latitude=30.2):
    return {
        "id": key,
        "name": name,
        "location": f"{longitude},{latitude}",
        "citycode": "0571",
        "cityname": "杭州市",
        "address": "示例路",
        "type": "服务",
    }


@pytest.fixture
def nearby(client, settings):
    scenario = Scenario()
    settings.deepseek_api_key = "fake"
    settings.amap_web_service_key = "fake"

    async def model(request):
        body = json.loads(request.content)
        scenario.calls.append(body)
        system = body["messages"][0]["content"]
        if "可使用三种格式" in system:
            choice = "凌水校区" in body["messages"][-1]["content"]
            answer = {
                "kind": "nearby",
                "city": "杭州市",
                "anchor_name": "示例大学(凌水校区)" if choice else "示例大学",
                "tasks": [
                    {"agent": "dining", "keyword": "餐厅", "instruction": "推荐吃饭地点"},
                    {"agent": "activity", "keyword": "台球", "instruction": "饭后打台球，距离近"},
                ],
            }
        elif "只负责自己的任务" in system:
            task = json.loads(body["messages"][-1]["content"])
            answer = {"city": task["city"], "keyword": task["assignment"]["keyword"], "limit": 5}
        else:
            data = json.loads(body["messages"][-1]["content"])
            scenario.reviews.append(data)
            if scenario.revise_first and len(scenario.reviews) == 1:
                answer = {
                    "decision": "revise",
                    "selected_ids": [],
                    "revisions": [
                        {"task_id": "task-1", "task_version": 1, "feedback": "选择更方便衔接的餐厅"}
                    ],
                }
            else:
                chosen = [
                    next(p for p in data["candidates"] if p["task_id"] == task["task_id"])
                    for task in data["tasks"]
                ]
                answer = {
                    "decision": "approve",
                    "answer": "先吃饭，再去附近打台球。",
                    "selected_ids": [p["evidence_id"] for p in chosen],
                }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    async def maps(request):
        params = request.url.params
        scenario.searches.append(
            {
                "path": request.url.path,
                "params": {key: value for key, value in params.items() if key != "key"},
            }
        )
        if request.url.path == "/v5/place/text":
            if "凌水校区" in params["keywords"]:
                rows = [
                    poi("L", "示例大学(凌水校区)", 120.1),
                    poi("LC", "示例大学(凌水校区技术中心)", 120.101),
                    poi("LB", "示例大学凌水校区西区1号楼", 120.102),
                ]
            else:
                rows = [
                    poi("L", "示例大学(凌水校区)", 120.1),
                    poi("MED", "示例大学医学部", 120.12),
                    poi("Y", "示例大学一二九校区", 120.2),
                ]
            return httpx.Response(200, json={"status": "1", "pois": rows})
        if request.url.path == "/v5/place/around":
            assert params["radius"] == "2000" and params["city_limit"] == "true"
            longitude = float(params["location"].split(",")[0])
            area = "L" if longitude == 120.1 else "Y"
            category = params["keywords"]
            rows = [
                poi(area + category, area + category, longitude + 0.001),
                poi("FAR", "远处的无关商家", 125.1),
            ]
            return httpx.Response(200, json={"status": "1", "pois": rows})
        assert request.url.path == "/v5/direction/walking"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {
                    "paths": []
                    if scenario.route_missing
                    else [
                        {
                            "distance": "700",
                            "cost": {"duration": "600"},
                            "steps": [
                                {
                                    "instruction": "沿路前往台球馆",
                                    "polyline": "120.1,30.2;120.101,30.2",
                                }
                            ],
                        }
                    ]
                },
            },
        )

    client.app.state.chat.model = DeepSeekClient(settings, transport=httpx.MockTransport(model))
    client.app.state.chat.map_provider = AMapClient(settings, transport=httpx.MockTransport(maps))
    return scenario


def send(client, headers, path, text, key):
    response = client.post(path, headers=headers, json={"content": text, "client_message_id": key})
    assert response.status_code == 202
    run = client.get("/api/v1/runs/" + response.json()["id"], headers=headers).json()
    messages = client.get(path, headers=headers).json()
    assert run["status"] == "succeeded", run
    return run, messages[-1]


def conversation(client, headers):
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    return f"/api/v1/conversations/{session}/messages"


def test_ambiguous_university_returns_real_recommendations_by_campus(client, login, nearby):
    headers = login()
    path = conversation(client, headers)
    run, message = send(
        client, headers, path, "示例大学附近有什么好吃的，吃完想打台球，推荐距离近的方案", "first"
    )
    result = message["map_result"]
    groups = result["recommendation_groups"]
    assert result["status"] == "approved" and len(groups) == 2
    assert [group["area"]["poi_id"] for group in groups] == ["L", "Y"]
    assert [place["label"] for place in result["places"]] == ["M1", "M2", "M3", "M4"]
    assert [group["place_ids"] for group in groups] == [["L餐厅", "L台球"], ["Y餐厅", "Y台球"]]
    assert all(group["route"]["duration_seconds"] == 600 for group in groups)
    assert "请补充" not in message["content"] and "〔地图来源未核实〕" not in message["content"]
    assert "远处的无关商家" not in json.dumps(result, ensure_ascii=False)
    assert len(nearby.reviews) == 2 and all(review["search_area"] for review in nearby.reviews)
    assert run["llm_calls"] == 7
    assert all(row["path"] != "/v5/place/text" for row in nearby.searches[1:])


def test_short_campus_reply_reuses_original_request_and_does_not_ask_again(client, login, nearby):
    headers = login()
    path = conversation(client, headers)
    send(client, headers, path, "示例大学附近吃饭，吃完打台球", "first")
    _, message = send(client, headers, path, "凌水校区", "second")
    groups = message["map_result"]["recommendation_groups"]
    assert len(groups) == 1 and groups[0]["area"]["poi_id"] == "L"
    assert "请补充" not in message["content"]
    route_prompts = [
        call for call in nearby.calls if "可使用三种格式" in call["messages"][0]["content"]
    ]
    assert len(route_prompts) == 1  # A stored campus selection cannot be rerouted city-wide.
    assert "示例大学附近吃饭，吃完打台球" in json.dumps(route_prompts[-1], ensure_ascii=False)


def test_nearby_supervisor_revises_only_needed_agent_with_same_campus(client, login, nearby):
    nearby.revise_first = True
    headers = login()
    run, message = send(
        client, headers, conversation(client, headers), "凌水校区附近吃饭打台球", "first"
    )
    assert message["map_result"]["status"] == "approved"
    assert message["map_result"]["review_rounds"] == 1
    assert any(event["stage"] == "revise" for event in run["workflow_events"])
    assert [
        row["params"]["location"] for row in nearby.searches if row["path"].endswith("around")
    ] == ["120.100000,30.200000"] * 3


def test_optional_connection_failure_keeps_reviewed_recommendations(client, login, nearby):
    nearby.route_missing = True
    headers = login()
    _, message = send(
        client, headers, conversation(client, headers), "凌水校区附近吃饭打台球", "first"
    )
    result = message["map_result"]
    assert result["status"] == "approved" and len(result["places"]) == 2
    assert result["recommendation_groups"][0]["route"] is None
    assert "请补充" not in message["content"]


def test_saved_campus_context_is_not_reused_in_another_conversation(client, login, nearby):
    headers = login()
    first = conversation(client, headers)
    send(client, headers, first, "示例大学附近吃饭打台球", "first")
    second = conversation(client, headers)
    _, message = send(client, headers, second, "凌水校区", "new")
    assert (
        len([call for call in nearby.calls if "可使用三种格式" in call["messages"][0]["content"]])
        == 2
    )
    assert message["map_result"]["recommendation_groups"][0]["area"]["poi_id"] == "L"
    assert len([search for search in nearby.searches if search["path"].endswith("text")]) == 2


def test_old_clarification_conversation_accepts_campus_choice_without_asking_again(
    client, login, nearby
):
    headers = login()
    path = conversation(client, headers)
    send(client, headers, path, "示例大学附近吃饭打台球", "first")
    session = path.split("/")[-2]
    old_result = {
        "status": "needs_clarification",
        "city": "杭州市",
        "places": [],
        "review_rounds": 0,
        "events": [],
        "searched_at": "2026-11-24T00:00:00Z",
    }
    with client.app.state.database.connect(write=True) as connection:
        connection.execute(
            "UPDATE messages SET content=?, map_result_json=? "
            "WHERE session_id=? AND role='assistant'",
            (
                "请补充出发点。候选：示例大学(凌水校区)、示例大学一二九校区。",
                json.dumps(old_result),
                session,
            ),
        )
    _, message = send(client, headers, path, "凌水校区", "second")
    groups = message["map_result"]["recommendation_groups"]
    assert len(groups) == 1 and groups[0]["area"]["poi_id"] == "L"
    assert "请补充" not in message["content"]
