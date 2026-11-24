"""Offline installed-image smoke: complete itinerary, route time and Supervisor rework."""

import argparse
import json
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.amap import AMapClient
from app.integrations.tavily import TavilyClient
from app.main import create_app


class ScriptedModel:
    def __init__(self):
        self.drafts, self.reviews = 0, 0

    async def complete(self, messages, budget, **kwargs):
        await budget.reserve("llm")
        await budget.reserve("external")
        system = messages[0].content
        if "可使用三种格式" in system:
            value = {
                "kind": "plan",
                "city": "杭州市",
                "tasks": [{"agent": "activity", "keyword": "公园", "instruction": "轻松半日游"}],
                "trip": {
                    "days": [
                        {
                            "start_at": "2026-11-25T09:00:00+08:00",
                            "end_at": "2026-11-25T13:00:00+08:00",
                        }
                    ],
                    "origin_name": "杭州东站",
                    "return_to_origin": True,
                    "mode": "transit",
                    "party_size": 2,
                    "assumptions": ["每段交通额外预留10分钟缓冲"],
                },
            }
        elif "只负责自己的任务" in system:
            value = {"keyword": "公园", "city": "杭州市", "limit": 5}
        elif "你是行程策划 Agent" in system:
            data = json.loads(messages[-1].content)
            self.drafts += 1
            if self.drafts > 1:
                assert data["feedback"] and data["previous_draft"]
            stops = []
            for poi_id in ("A", "B"):
                refs = [
                    source["label"] for source in data["web_sources"] if source["poi_id"] == poi_id
                ]
                stops.append(
                    {
                        "poi_id": poi_id,
                        "duration_minutes": 75 if poi_id == "A" else 60,
                        "reason": "安排慢走和休息，减少赶路。",
                        "activities": [
                            {"text": "沿步道散步拍照", "evidence_ids": refs},
                            {"text": "找合适的位置坐一会儿", "evidence_ids": []},
                        ],
                        "practical_info": [{"text": "出发前确认开放与预约", "evidence_ids": []}],
                    }
                )
            value = {
                "title": "杭州半日安排",
                "summary": "两站慢游，留出返程时间。费用待核实。",
                "days": [{"window_index": 0, "stops": stops}],
            }
        elif "审查完整游玩行程" in system:
            data = json.loads(messages[-1].content)
            self.reviews += 1
            value = {
                "task_version": data["task_version"],
                "decision": "revise" if self.reviews == 1 else "approve",
                "feedback": "保留第一站，明确留出休息" if self.reviews == 1 else "",
            }
        else:
            data = json.loads(messages[-1].content)
            value = {
                "decision": "approve",
                "answer": "候选地点已审查",
                "selected_ids": [row["evidence_id"] for row in data["candidates"]],
            }
        return json.dumps(value, ensure_ascii=False)


async def maps(request):
    if request.url.path == "/v5/place/text":
        items = (
            [("O", "杭州东站", "120.1,30.25")]
            if request.url.params["keywords"] == "杭州东站"
            else [("A", "湖畔公园", "120.15,30.25"), ("B", "文化公园", "120.2,30.25")]
        )
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": key,
                        "name": name,
                        "location": position,
                        "citycode": "0571",
                        "cityname": "杭州市",
                        "address": "示例路",
                        "type": "风景名胜",
                    }
                    for key, name, position in items
                ],
            },
        )
    assert request.url.path == "/v5/direction/transit/integrated"
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
                                "walking": {"distance": "100"},
                                "bus": {
                                    "buslines": [
                                        {
                                            "name": "地铁1号线",
                                            "polyline": request.url.params["origin"]
                                            + ";"
                                            + request.url.params["destination"],
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
    query = json.loads(request.content)["query"]
    park = "A" if "湖畔公园" in query else "B"
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "title": "示例公园介绍",
                    "url": "https://parks.example.org/" + park,
                    "content": "示例资料：园内设有步道，可散步游览。",
                }
            ]
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gomate-itinerary-") as directory:
        settings = Settings(
            _env_file=None,
            database_path=Path(directory) / "smoke.db",
            deepseek_api_key="fake",
            amap_web_service_key="fake",
            tavily_api_key="fake",
            amap_min_interval_seconds=0,
        )
        app = create_app(settings)
        model = ScriptedModel()
        app.state.chat.model = model
        app.state.chat.map_provider = AMapClient(settings, transport=httpx.MockTransport(maps))
        app.state.chat.web_provider = TavilyClient(settings, transport=httpx.MockTransport(web))
        with TestClient(app) as client:
            credentials = {"username": "smoke", "password": "fake-password-only"}
            assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
            token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
            path = f"/api/v1/conversations/{session}/messages"
            body = {
                "content": "明天从杭州东站9点出发13点返回，安排轻松半日游",
                "client_message_id": "trip",
            }
            accepted = client.post(path, headers=headers, json=body)
            run = client.get("/api/v1/runs/" + accepted.json()["id"], headers=headers).json()
            assert run["status"] == "succeeded", run
            result = client.get(path, headers=headers).json()[-1]["map_result"]
            plan = result["itinerary"]
            assert plan["days"][0]["finish_at"] == "2026-11-25T12:45:00+08:00"
            assert plan["revision_count"] == 1 and len(plan["web_sources"]) == 2
            assert len(plan["days"][0]["legs"]) == 3
            assert client.post(path, headers=headers, json=body).json()["id"] == run["id"]
            assert model.drafts == model.reviews == 2
            assert (run["llm_calls"], run["external_requests"], run["tool_calls"]) == (7, 14, 8)
            if options.output:
                options.output.parent.mkdir(parents=True, exist_ok=True)
                options.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    print("PASS: complete itinerary, travel/stay times, return and web evidence")
    print("PASS: Supervisor revision, shared budget and persisted idempotency; no external calls")


if __name__ == "__main__":
    main()
