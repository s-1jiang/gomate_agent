"""Offline runtime smoke for blank DeepSeek JSON responses and bounded recovery."""

import json
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.deepseek import DeepSeekClient
from app.main import create_app


def main():
    calls = []

    async def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        text = " \n\t "
        if len(calls) == 2:
            assert "JSON Schema" in payload["messages"][-1]["content"]
            text = json.dumps({"kind": "clarify", "answer": "请先告诉我中山广场所在的城市。"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": text},
                    }
                ]
            },
        )

    with tempfile.TemporaryDirectory(prefix="gomate-response-") as directory:
        config = Settings(
            _env_file=None,
            database_path=Path(directory) / "smoke.db",
            task_execution_mode="inline",
            deepseek_api_key="fake-key",
        )
        app = create_app(config)
        app.state.chat.model = DeepSeekClient(config, transport=httpx.MockTransport(provider))
        with TestClient(app) as client:
            credentials = {"username": "response_smoke", "password": "test-only-password"}
            assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
            token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
            path = f"/api/v1/conversations/{session}/messages"
            body = {"content": "想去中山广场玩到晚上九点，怎么安排？", "client_message_id": "one"}
            accepted = client.post(path, headers=headers, json=body)
            assert accepted.status_code == 202
            run = client.get("/api/v1/runs/" + accepted.json()["id"], headers=headers).json()
            assert run["status"] == "succeeded", run
            assert (run["llm_calls"], run["external_requests"], run["tool_calls"]) == (2, 2, 1)
            messages = client.get(path, headers=headers).json()
            assert (
                len(messages) == 2 and messages[-1]["content"] == "请先告诉我中山广场所在的城市。"
            )
            assert client.post(path, headers=headers, json=body).json()["id"] == run["id"]
            assert len(calls) == 2
    print("PASS: blank JSON content recovered as clarification, not a fabricated itinerary")
    print("PASS: one extra request, original budget and message idempotency; no external calls")


if __name__ == "__main__":
    main()
