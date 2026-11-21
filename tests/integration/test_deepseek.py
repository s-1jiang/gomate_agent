import asyncio

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.contracts import ChatMessage
from app.integrations.deepseek import DeepSeekClient
from app.tools.budget import RunBudget


def test_deepseek_request_format_budget_and_reasoning_not_returned(settings):
    settings.deepseek_api_key = "fake-test-key"

    async def scenario():
        requests = []

        async def handler(request):
            requests.append(request)
            assert str(request.url) == "https://api.deepseek.com/chat/completions"
            assert request.headers["Authorization"] == "Bearer fake-test-key"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "answer",
                                "reasoning_content": "INTERNAL_REASONING_CANARY",
                            }
                        }
                    ]
                },
            )

        client = DeepSeekClient(settings, transport=httpx.MockTransport(handler))
        budget = RunBudget.create(llm=1)
        result = await client.complete([ChatMessage(role="user", content="hello")], budget)
        assert result == "answer"
        assert budget.counts == {"tool": 0, "llm": 1, "external": 1}
        with pytest.raises(AppError) as exc:
            await client.complete([], budget)
        assert exc.value.code == "BUDGET_EXCEEDED"
        assert len(requests) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,body,code",
    [
        (429, {}, "PROVIDER_RATE_LIMITED"),
        (401, {"error": {"message": "PROVIDER_SECRET_CANARY"}}, "PROVIDER_UNAVAILABLE"),
        (200, {"choices": []}, "INVALID_MODEL_OUTPUT"),
    ],
)
def test_provider_errors_are_distinct_and_not_retried(settings, status, body, code):
    settings.deepseek_api_key = "fake-test-key"

    async def scenario():
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(status, json=body)

        client = DeepSeekClient(settings, transport=httpx.MockTransport(handler))
        with pytest.raises(AppError) as exc:
            await client.complete([], RunBudget.create())
        assert exc.value.code == code
        assert "PROVIDER_SECRET_CANARY" not in str(exc.value)
        assert calls == 1

    asyncio.run(scenario())
