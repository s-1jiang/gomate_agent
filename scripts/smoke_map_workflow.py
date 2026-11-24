"""Offline Supervisor/map smoke using a temporary database and fake provider credentials."""

import json
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.amap import AMapClient
from app.integrations.deepseek import DeepSeekClient
from app.main import create_app


def main():
    calls, searches = [], []
    reviews = 0

    async def model(request):
        nonlocal reviews
        body = json.loads(request.content)
        calls.append(body)
        system = body["messages"][0]["content"]
        if "搜索实际地点" in system:
            value = {
                "kind": "search",
                "city": "杭州市",
                "tasks": [
                    {"agent": "dining", "keyword": "咖啡馆", "instruction": "搜索咖啡馆"},
                    {"agent": "activity", "keyword": "公园", "instruction": "搜索公园"},
                ],
            }
        elif "只负责自己的任务" in system:
            task = json.loads(body["messages"][-1]["content"])
            value = {
                "city": "杭州市",
                "limit": 5,
                "keyword": "安静咖啡馆"
                if task["task_version"] == 2
                else task["assignment"]["keyword"],
            }
            if task["task_version"] == 2:
                assert task["revision_feedback"] and task["previous_result"]
        else:
            data = json.loads(body["messages"][-1]["content"])
            reviews += 1
            if reviews == 1:
                value = {
                    "decision": "revise",
                    "selected_ids": [],
                    "revisions": [
                        {
                            "task_id": "task-1",
                            "task_version": 1,
                            "feedback": "改用安静咖啡馆查询",
                        }
                    ],
                }
            else:
                value = {
                    "decision": "approve",
                    "answer": "已完成地点搜索。",
                    "revisions": [],
                    "selected_ids": [item["evidence_id"] for item in data["candidates"]],
                }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    async def maps(request):
        assert request.url.host == "restapi.amap.com" and request.url.path == "/v5/place/text"
        assert request.url.params["key"] == "fake-web-key"
        keyword = request.url.params["keywords"]
        searches.append(keyword)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": {"咖啡馆": "B001", "公园": "B002", "安静咖啡馆": "B003"}[keyword],
                        "name": keyword,
                        "location": "120.15,30.25",
                        "cityname": "杭州市",
                        "citycode": "0571",
                        "address": "示例路",
                        "type": "示例类别",
                    }
                ],
            },
        )

    with tempfile.TemporaryDirectory(prefix="gomate-map-") as temporary:
        settings = Settings(
            _env_file=None,
            database_path=Path(temporary) / "smoke.db",
            deepseek_api_key="fake-model-key",
            amap_web_service_key="fake-web-key",
        )
        application = create_app(settings)
        application.state.chat.model = DeepSeekClient(
            settings, transport=httpx.MockTransport(model)
        )
        application.state.chat.map_provider = AMapClient(
            settings, transport=httpx.MockTransport(maps)
        )
        with TestClient(application) as client:
            credentials = {"username": "map_smoke", "password": "smoke-test-password-123"}
            assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
            token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
            path = f"/api/v1/conversations/{session}/messages"
            payload = {"content": "在杭州找咖啡馆和公园", "client_message_id": "smoke-one"}
            run = client.post(path, headers=headers, json=payload).json()
            state = client.get(f"/api/v1/runs/{run['id']}", headers=headers).json()
            assert state["status"] == "succeeded", state["error_code"]
            answer = client.get(path, headers=headers).json()[-1]
            result = answer["map_result"]
            assert result["status"] == "approved" and result["review_rounds"] == 1
            assert {place["poi_id"] for place in result["places"]} == {"B002", "B003"}
            assert sorted(searches) == sorted(["咖啡馆", "公园", "安静咖啡馆"])
            assert state["workflow_events"] == result["events"]
            assert client.post(path, headers=headers, json=payload).json()["id"] == run["id"]
            assert len(calls) == 6
            assert (state["llm_calls"], state["external_requests"], state["tool_calls"]) == (
                6,
                9,
                4,
            )
            assert "fake-web-key" not in json.dumps(answer)
            print("PASS: Supervisor dispatch, review, targeted revision and map evidence")
            print(
                "PASS: persisted trace, shared budgets and idempotency; no external provider calls"
            )


if __name__ == "__main__":
    main()
