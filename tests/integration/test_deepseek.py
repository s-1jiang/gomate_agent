import asyncio
import json

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
            assert json.loads(request.content)["max_tokens"] == settings.chat_max_output_tokens
            assert json.loads(request.content)["thinking"] == {"type": "disabled"}
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
        (401, {"error": {"message": "PROVIDER_SECRET_CANARY"}}, "PROVIDER_AUTH_FAILED"),
        (402, {}, "PROVIDER_BALANCE_LOW"),
        (400, {}, "PROVIDER_BAD_REQUEST"),
        (500, {}, "PROVIDER_UNAVAILABLE"),
        (200, {"choices": []}, "INVALID_PROVIDER_RESPONSE"),
        (
            200,
            {"choices": [{"message": {"content": "cut"}, "finish_reason": "length"}]},
            "LLM_OUTPUT_TRUNCATED",
        ),
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


@pytest.mark.parametrize("content", ["", "   \n\t", None])
def test_blank_json_output_is_identified_without_exposing_reasoning(settings, content, caplog):
    settings.deepseek_api_key = "fake-test-key"

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": content,
                            "reasoning_content": "INTERNAL_REASONING_CANARY",
                        },
                    }
                ]
            },
        )

    async def scenario():
        budget = RunBudget.create()
        with pytest.raises(AppError) as error:
            await DeepSeekClient(settings, transport=httpx.MockTransport(handler)).complete(
                [ChatMessage(role="user", content="JSON please")],
                budget,
                json_mode=True,
            )
        assert error.value.code == "EMPTY_MODEL_OUTPUT"
        assert "空内容" in error.value.message
        assert budget.counts == {"tool": 0, "llm": 1, "external": 1}

    asyncio.run(scenario())
    assert "EMPTY_MODEL_OUTPUT" in caplog.text
    assert "INTERNAL_REASONING_CANARY" not in caplog.text
    assert "fake-test-key" not in caplog.text


@pytest.mark.parametrize(
    "reason,code",
    [
        ("content_filter", "MODEL_REFUSED"),
        ("insufficient_system_resource", "PROVIDER_BUSY"),
        ("aborted", "PROVIDER_GENERATION_ABORTED"),
        ("tool_calls", "INVALID_PROVIDER_RESPONSE"),
    ],
)
def test_non_success_finish_reason_is_not_an_answer_or_a_blank_retry(settings, reason, code):
    settings.deepseek_api_key = "fake-test-key"

    async def handler(request):
        return httpx.Response(
            200, json={"choices": [{"finish_reason": reason, "message": {"content": None}}]}
        )

    async def scenario():
        budget = RunBudget.create()
        with pytest.raises(AppError) as error:
            await DeepSeekClient(settings, transport=httpx.MockTransport(handler)).complete(
                [], budget
            )
        assert error.value.code == code
        assert budget.counts["llm"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"choices": [None]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": {"secret": "SECRET_RESPONSE_CANARY"}}}]},
    ],
)
def test_malformed_envelopes_do_not_crash_or_disclose_content(settings, payload, caplog):
    settings.deepseek_api_key = "fake-test-key"

    async def handler(request):
        return httpx.Response(
            200, content=json.dumps(payload).encode(), headers={"content-type": "application/json"}
        )

    async def scenario():
        with pytest.raises(AppError) as error:
            await DeepSeekClient(settings, transport=httpx.MockTransport(handler)).complete(
                [], RunBudget.create()
            )
        assert error.value.code == "INVALID_PROVIDER_RESPONSE"
        assert "SECRET_RESPONSE_CANARY" not in str(error.value)

    asyncio.run(scenario())
    assert "SECRET_RESPONSE_CANARY" not in caplog.text


def test_non_json_provider_body_is_classified_without_echo(settings, caplog):
    settings.deepseek_api_key = "fake-test-key"

    async def handler(request):
        return httpx.Response(200, text="<html>SECRET_RESPONSE_CANARY</html>")

    async def scenario():
        with pytest.raises(AppError) as error:
            await DeepSeekClient(settings, transport=httpx.MockTransport(handler)).complete(
                [], RunBudget.create()
            )
        assert error.value.code == "INVALID_PROVIDER_RESPONSE"

    asyncio.run(scenario())
    assert "SECRET_RESPONSE_CANARY" not in caplog.text
