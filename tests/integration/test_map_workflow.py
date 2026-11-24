import asyncio
import json
from dataclasses import dataclass, field

import httpx
import pytest

from app.core.errors import AppError
from app.core.identity import AuthContext
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository
from app.integrations.amap import AMapClient
from app.integrations.deepseek import DeepSeekClient
from app.schemas.maps import SearchArguments
from app.tools.budget import RunBudget
from app.tools.context import ToolContext
from app.tools.map_gateway import MapToolGateway


@dataclass
class Scenario:
    tasks: list = field(
        default_factory=lambda: [
            {
                "agent": "dining",
                "keyword": "咖啡馆",
                "instruction": "搜索咖啡馆",
            }
        ]
    )
    city: str = "杭州市"
    reviews: list = field(default_factory=lambda: ["approve"])
    model_calls: list = field(default_factory=list)
    map_calls: list = field(default_factory=list)
    workers: list = field(default_factory=list)
    review_count: int = 0
    map_payload: dict | None = None
    wrong_city: bool = False


@pytest.fixture
def map_scenario(client, settings):
    settings.deepseek_api_key = "fake-model-key"
    settings.amap_web_service_key = "fake-web-secret"
    scenario = Scenario()

    async def model_handler(request):
        body = json.loads(request.content)
        scenario.model_calls.append(body)
        assert body["response_format"] == {"type": "json_object"}
        system = body["messages"][0]["content"]
        if "搜索实际地点" in system:
            answer = {"kind": "search", "city": scenario.city, "tasks": scenario.tasks}
        elif "只负责自己的任务" in system:
            task = json.loads(body["messages"][-1]["content"])
            scenario.workers.append(task)
            answer = {
                "city": "北京市" if scenario.wrong_city else task["city"],
                "keyword": "安静咖啡馆"
                if task["task_version"] > 1
                else task["assignment"]["keyword"],
                "limit": 5,
            }
        else:
            data = json.loads(body["messages"][-1]["content"])
            mode = scenario.reviews[min(scenario.review_count, len(scenario.reviews) - 1)]
            scenario.review_count += 1
            answer = {
                "decision": "approve",
                "answer": "以下地点来自高德查询。",
                "selected_ids": [item["evidence_id"] for item in data["candidates"]],
                "revisions": [],
            }
            if mode in {"revise", "stale"}:
                answer = {
                    "decision": "revise",
                    "revisions": [
                        {
                            "task_id": "task-1",
                            "task_version": (
                                99 if mode == "stale" else data["tasks"][0]["task_version"]
                            ),
                            "feedback": "请改用安静咖啡馆重新查询",
                        }
                    ],
                    "selected_ids": [],
                }
            elif mode == "forged":
                answer["selected_ids"] = ["unobserved-poi"]
            elif mode == "clarify":
                answer = {"decision": "clarify", "answer": "请补充具体区域。", "selected_ids": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    async def map_handler(request):
        assert request.url.host == "restapi.amap.com"
        assert request.url.path == "/v5/place/text"
        assert request.url.params["key"] == "fake-web-secret"
        assert request.url.params["city_limit"] == "true"
        assert request.url.params["region"] == scenario.city
        keyword = request.url.params["keywords"]
        scenario.map_calls.append(keyword)
        payload = (
            scenario.map_payload
            if scenario.map_payload is not None
            else {
                "status": "1",
                "pois": [
                    {
                        "id": {"咖啡馆": "B001", "公园": "B002", "安静咖啡馆": "B003"}.get(
                            keyword, "B004"
                        ),
                        "name": "静园咖啡" if "咖啡" in keyword else "河边公园",
                        "location": "120.15,30.25",
                        "citycode": "0571",
                        "cityname": "杭州市",
                        "adname": "西湖区",
                        "address": "示例路 10 号",
                        "type": "餐饮服务",
                    }
                ],
            }
        )
        return httpx.Response(200, json=payload)

    client.app.state.chat.model = DeepSeekClient(
        settings, transport=httpx.MockTransport(model_handler)
    )
    client.app.state.chat.map_provider = AMapClient(
        settings, transport=httpx.MockTransport(map_handler)
    )
    return scenario


def perform(client, headers, text="在杭州找咖啡馆"):
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    response = client.post(
        path, headers=headers, json={"content": text, "client_message_id": "one"}
    )
    assert response.status_code == 202
    run = client.get(f"/api/v1/runs/{response.json()['id']}", headers=headers).json()
    messages = client.get(path, headers=headers).json()
    return run, messages, path


def test_supervisor_delegates_reviews_and_persists_only_observed_places(
    client, login, map_scenario
):
    headers = login()
    run, messages, path = perform(client, headers)
    assert run["status"] == "succeeded"
    result = messages[-1]["map_result"]
    assert result["status"] == "approved"
    assert result["places"][0]["poi_id"] == "B001"
    assert result["places"][0]["location"]["coordinate_system"] == "GCJ02"
    assert result["places"][0]["agent"] == "dining"
    assert result["places"][0]["source_ref"] == "amap:poi:B001"
    assert [event["stage"] for event in result["events"]] == [
        "route",
        "dispatch",
        "search",
        "review",
        "complete",
    ]
    assert run["workflow_events"] == result["events"]
    assert (run["llm_calls"], run["external_requests"], run["tool_calls"]) == (3, 4, 2)
    replay = client.post(
        path, headers=headers, json={"content": "在杭州找咖啡馆", "client_message_id": "one"}
    )
    assert replay.json()["id"] == run["id"]
    assert len(map_scenario.map_calls) == 1
    assert "fake-web-secret" not in json.dumps(messages)
    assert client.get(path, headers=headers).json()[-1]["map_result"] == result


def test_only_rejected_task_is_revised_and_receives_feedback_and_previous_result(
    client, login, map_scenario
):
    map_scenario.tasks.append({"agent": "activity", "keyword": "公园", "instruction": "搜索公园"})
    map_scenario.reviews = ["revise", "approve"]
    run, messages, _ = perform(client, login())
    assert run["status"] == "succeeded"
    assert sorted(map_scenario.map_calls) == sorted(["咖啡馆", "安静咖啡馆", "公园"])
    revised = [item for item in map_scenario.workers if item["task_version"] == 2]
    assert len(revised) == 1 and revised[0]["assignment"]["agent"] == "dining"
    assert revised[0]["revision_feedback"] == "请改用安静咖啡馆重新查询"
    assert revised[0]["previous_result"]["places"][0]["poi_id"] == "B001"
    result = messages[-1]["map_result"]
    assert result["review_rounds"] == 1
    assert {place["poi_id"] for place in result["places"]} == {"B003", "B002"}
    assert any(
        event["stage"] == "revise" and event["task_version"] == 2 for event in result["events"]
    )


def test_revision_limit_returns_no_unapproved_places(client, login, map_scenario, settings):
    map_scenario.reviews = ["revise"]
    settings.max_review_rounds = 1
    run, messages, _ = perform(client, login())
    assert run["status"] == "succeeded"
    assert len(map_scenario.map_calls) == 2
    assert messages[-1]["map_result"]["status"] == "revision_limit"
    assert messages[-1]["map_result"]["places"] == []
    assert "B001" not in messages[-1]["content"]


@pytest.mark.parametrize("mode,code", [("forged", "INVALID_REVIEW"), ("stale", "STALE_REVIEW")])
def test_fabricated_evidence_and_stale_review_cannot_publish(
    client, login, map_scenario, mode, code
):
    map_scenario.reviews = [mode]
    run, messages, _ = perform(client, login())
    assert run["status"] == "failed" and run["error_code"] == code
    assert len(messages) == 1


def test_specialist_cannot_change_supervisor_city(client, login, map_scenario):
    map_scenario.wrong_city = True
    run, messages, _ = perform(client, login())
    assert run["error_code"] == "AGENT_SCOPE_CHANGED"
    assert not map_scenario.map_calls and len(messages) == 1


def test_missing_city_and_supervisor_clarification_do_not_publish_places(
    client, login, map_scenario
):
    map_scenario.city = ""
    run, messages, _ = perform(client, login())
    assert run["status"] == "succeeded" and not map_scenario.map_calls
    assert messages[-1]["map_result"]["status"] == "needs_clarification"


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"status": "0", "infocode": "10001", "info": "SECRET_CANARY"}, "MAP_AUTH_FAILED"),
        ({"status": "0", "infocode": "10003"}, "MAP_RATE_LIMITED"),
        (
            {"status": "1", "pois": [{"id": "bad", "name": "invalid", "location": "999,999"}]},
            "INVALID_MAP_OUTPUT",
        ),
    ],
)
def test_provider_errors_are_distinct_from_empty_results(
    client, login, map_scenario, payload, code
):
    map_scenario.map_payload = payload
    run, messages, _ = perform(client, login())
    assert run["error_code"] == code and run["status"] == "failed"
    assert "SECRET_CANARY" not in run["error_message"]
    assert len(messages) == 1 and len(map_scenario.map_calls) == 1


def test_no_results_is_a_reviewed_empty_response(client, login, map_scenario):
    map_scenario.map_payload = {"status": "1", "pois": []}
    run, messages, _ = perform(client, login())
    assert run["status"] == "succeeded"
    assert messages[-1]["map_result"]["status"] == "no_results"
    assert messages[-1]["map_result"]["places"] == []


def test_shared_budget_cannot_be_reset_by_agents_or_review(client, login, map_scenario, settings):
    settings.max_llm_calls_per_run = 2
    run, messages, _ = perform(client, login())
    assert run["error_code"] == "BUDGET_EXCEEDED"
    assert run["llm_calls"] == 2 and len(map_scenario.map_calls) == 1
    assert len(messages) == 1


def test_map_messages_and_trace_are_owned_by_the_original_user(client, login, map_scenario):
    alice = login("alice")
    run, _, path = perform(client, alice)
    bob = login("bob")
    assert client.get(path, headers=bob).status_code == 404
    assert client.get(f"/api/v1/runs/{run['id']}", headers=bob).status_code == 404


def test_supervisor_has_no_direct_map_tool_permission(client):
    class Provider:
        async def search_places(self, **kwargs):
            raise AssertionError("Unauthorized tool reached provider")

    async def scenario():
        gateway = MapToolGateway(Provider())
        context = ToolContext(
            AuthContext("user", "user"),
            "session",
            "run",
            "supervisor",
            "request",
            frozenset({"map:search"}),
        )
        budget = RunBudget.create()
        with pytest.raises(AppError) as error:
            await gateway.search(context, SearchArguments(keyword="公园", city="杭州"), budget)
        assert error.value.code == "TOOL_FORBIDDEN"
        assert budget.counts["tool"] == 1 and budget.counts["external"] == 0

    asyncio.run(scenario())


def test_cancelling_inflight_map_request_discards_reply(client, settings, map_scenario):
    database = client.app.state.database
    user = AuthRepository(database).register("cancel_user", "test-only-hash")
    auth = AuthContext(user["id"], "cancel_user")
    session = ConversationRepository(database, auth).create("map")["id"]
    repository = RunRepository(database, auth)
    run, _ = repository.accept(session, "one", "搜索咖啡馆", settings)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def slow(request):
            entered.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return httpx.Response(200, json={"status": "1", "pois": []})

        service = client.app.state.chat
        service.map_provider = AMapClient(settings, transport=httpx.MockTransport(slow))
        job = asyncio.create_task(service.run(auth, run["id"]))
        await asyncio.wait_for(entered.wait(), 3)
        repository.cancel(run["id"])
        service.cancel(auth, run["id"])
        await asyncio.wait_for(job, 3)
        assert cancelled.is_set()

    asyncio.run(scenario())
    assert repository.get(run["id"])["status"] == "cancelled"
    assert len(ConversationRepository(database, auth).messages(session, 100, None)) == 1
