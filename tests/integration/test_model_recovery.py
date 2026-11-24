import json

import httpx
import pytest

from app.integrations.deepseek import DeepSeekClient


@pytest.mark.parametrize("recover", [True, False])
def test_blank_supervisor_response_retries_once_and_preserves_run_idempotency(
    client, login, settings, recover
):
    settings.deepseek_api_key = "fake-key"
    calls = []

    async def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["response_format"] == {"type": "json_object"}
        content = "   "
        if recover and len(calls) > 1:
            assert "JSON Schema" in payload["messages"][-1]["content"]
            content = json.dumps({"kind": "clarify", "answer": "请先告诉我中山广场所在的城市。"})
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        )

    client.app.state.chat.model = DeepSeekClient(settings, transport=httpx.MockTransport(handler))
    headers = login()
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    body = {"content": "想去中山广场玩到晚上九点，怎么安排？", "client_message_id": "same-request"}
    accepted = client.post(path, headers=headers, json=body)
    assert accepted.status_code == 202
    run = client.get("/api/v1/runs/" + accepted.json()["id"], headers=headers).json()
    assert len(calls) == 2 and run["llm_calls"] == run["external_requests"] == 2
    assert run["tool_calls"] == 1
    messages = client.get(path, headers=headers).json()
    if recover:
        assert run["status"] == "succeeded" and len(messages) == 2
        assert messages[-1]["content"] == "请先告诉我中山广场所在的城市。"
    else:
        assert run["status"] == "failed" and run["error_code"] == "EMPTY_MODEL_OUTPUT"
        assert "空内容" in run["error_message"] and len(messages) == 1
    assert client.post(path, headers=headers, json=body).json()["id"] == run["id"]
    assert len(calls) == 2
